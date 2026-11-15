"""
Salt Sw ver.1 - Test History & Integrity (시험 이력 자동 저장 · 무결성 해시)
완료된 시험을 사람이 읽을 수 있는 JSON 한 파일로 history/ 폴더에 자동 저장하고,
SHA-256 해시로 "저장 당시 그대로인지"를 검증한다.

파일 구조
{
  "schema": "salt-sw.test-history/1",
  "record_id": "20261115-130501-123456_SALT-SP-001",
  "created_at": "2026-11-15T13:05:01.123456",
  "meta": { ... 목록 표시용 요약 ... },
  "payload": { 시험 조건 · 시편 · 교정 스냅샷 · 결과 · 원시 데이터 },
  "integrity": {
      "algorithm": "sha256",
      "digest": "...",          # payload 를 정렬·압축한 UTF-8 JSON 의 해시
      "prev_digest": "...",     # 직전 이력의 digest (체인)
      "canonicalization": "json.sort_keys+compact+utf8"
  }
}

무결성 설계
- digest 는 payload 전체(원시 데이터 포함)를 대상으로 계산한다. 값을 하나라도 고치면 검증에 실패한다.
- prev_digest 로 이력이 사슬처럼 연결되므로, 과거 기록을 수정하면 그 뒤 기록의 연결도 함께 깨진다.
  (변조 흔적을 숨기려면 이후 모든 파일을 다시 계산해야 하고, 그 경우에도 최초 digest 를 보관한
   외부 사본과 대조하면 드러난다.)
- 파일을 지우는 기능은 두지 않는다. 이력은 감사 추적(audit trail)이므로 앱에서 임의 삭제하지 않는다.
"""

import hashlib
import hmac
import json
import math
import os
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    BendingType, DataPoint, ExtensometerSettings, HoldingType, Specimen, SpecimenType,
    TestConfig, TestMode, TestResult,
)
from .sequence import SequenceProgram

HISTORY_SCHEMA = "salt-sw.test-history/1"
GENESIS_DIGEST = ""

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_HISTORY_DIR = os.path.join(BASE_DIR, "history")


# ----------------------------------------------------------------------
# 결과 객체
# ----------------------------------------------------------------------
@dataclass
class HistorySummary:
    """목록 표시용 요약 (파일을 열지 않고 보여줄 수 있는 최소 정보)"""
    record_id: str
    created_at: str
    specimen_id: str
    material: str
    mode: str                # TestMode.name
    mode_label: str          # TestMode.value (표시용)
    peak_load_n: float
    peak_stress_mpa: float
    elongation_pct: float
    total_samples: int
    path: str
    digest: str
    prev_digest: str = ""
    sequence_steps: int = 0
    completion_reason: str = ""

    @property
    def short_digest(self) -> str:
        return self.digest[:12] if self.digest else ""

    @property
    def created_display(self) -> str:
        """2026-11-15 13:05:01 형태 표시"""
        return self.created_at.replace("T", " ")[:19]


@dataclass
class IntegrityResult:
    """무결성 검증 결과"""
    record_id: str
    ok: bool
    note: str = ""              # 정상/불일치 사유

    @property
    def label_key(self) -> str:
        return "hist_integrity_ok" if self.ok else "hist_integrity_bad"


@dataclass
class ChainResult:
    """이력 전체 체인 검증 결과"""
    total: int
    ok_count: int
    problems: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass
class HistoryRecord:
    """이력 1건의 전체 내용"""
    summary: HistorySummary
    specimen: Specimen
    config: TestConfig
    result: TestResult
    points: List[DataPoint]
    calibration: Dict[str, Any] = field(default_factory=dict)
    extensometer: Dict[str, Any] = field(default_factory=dict)
    integrity: IntegrityResult = field(default_factory=lambda: IntegrityResult("", True))
    raw: Dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------
# 직렬화 도우미
# ----------------------------------------------------------------------
def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def specimen_to_dict(specimen: Specimen) -> Dict[str, Any]:
    return {
        "specimen_id": specimen.specimen_id,
        "material": specimen.material,
        "specimen_type": specimen.specimen_type.name,
        "width_mm": specimen.width_mm,
        "thickness_mm": specimen.thickness_mm,
        "diameter_mm": specimen.diameter_mm,
        "gauge_length_mm": specimen.gauge_length_mm,
    }


def specimen_from_dict(raw: Dict[str, Any]) -> Specimen:
    raw = raw or {}
    try:
        stype = SpecimenType[str(raw.get("specimen_type", "FLAT"))]
    except KeyError:
        stype = SpecimenType.FLAT
    return Specimen(
        specimen_id=str(raw.get("specimen_id", "")),
        material=str(raw.get("material", "")),
        specimen_type=stype,
        width_mm=_f(raw.get("width_mm"), 12.5),
        thickness_mm=_f(raw.get("thickness_mm"), 3.0),
        diameter_mm=_f(raw.get("diameter_mm"), 10.0),
        gauge_length_mm=_f(raw.get("gauge_length_mm"), 50.0),
    )


def config_to_dict(config: TestConfig) -> Dict[str, Any]:
    return {
        "mode": config.mode.name,
        "test_speed_mm_min": config.test_speed_mm_min,
        "fracture_drop_ratio": config.fracture_drop_ratio,
        "max_displacement_mm": config.max_displacement_mm,
        "sampling_rate_hz": config.sampling_rate_hz,
        "bending_type": config.bending_type.name,
        "span_length_mm": config.span_length_mm,
        "holding_type": config.holding_type.name,
        "target_holding_val": config.target_holding_val,
        "holding_duration_s": config.holding_duration_s,
        "extensometer": asdict(config.ext),
        "sequence": config.sequence.to_dict(),
    }


def config_from_dict(raw: Dict[str, Any]) -> TestConfig:
    raw = raw or {}
    try:
        mode = TestMode[str(raw.get("mode", "TENSILE"))]
    except KeyError:
        mode = TestMode.TENSILE
    try:
        btype = BendingType[str(raw.get("bending_type", "THREE_POINT"))]
    except KeyError:
        btype = BendingType.THREE_POINT
    try:
        htype = HoldingType[str(raw.get("holding_type", "LOAD_HOLD"))]
    except KeyError:
        htype = HoldingType.LOAD_HOLD

    ext_raw = raw.get("extensometer") if isinstance(raw.get("extensometer"), dict) else {}
    ext = ExtensometerSettings()
    for key, value in ext_raw.items():
        if hasattr(ext, key):
            setattr(ext, key, value)

    return TestConfig(
        mode=mode,
        test_speed_mm_min=_f(raw.get("test_speed_mm_min"), 5.0),
        fracture_drop_ratio=_f(raw.get("fracture_drop_ratio"), 0.5),
        max_displacement_mm=_f(raw.get("max_displacement_mm"), 50.0),
        sampling_rate_hz=_i(raw.get("sampling_rate_hz"), 20),
        bending_type=btype,
        span_length_mm=_f(raw.get("span_length_mm"), 100.0),
        holding_type=htype,
        target_holding_val=_f(raw.get("target_holding_val"), 1000.0),
        holding_duration_s=_f(raw.get("holding_duration_s"), 60.0),
        ext=ext,
        sequence=SequenceProgram.from_dict(raw.get("sequence")),
    )


def result_to_dict(result: TestResult) -> Dict[str, Any]:
    data = asdict(result)
    data["test_mode"] = result.test_mode.name
    data["test_mode_label"] = result.test_mode.value
    return data


def result_from_dict(raw: Dict[str, Any]) -> TestResult:
    raw = raw or {}
    try:
        mode = TestMode[str(raw.get("test_mode", "TENSILE"))]
    except KeyError:
        mode = TestMode.TENSILE
    valid = {f.name for f in fields(TestResult)}
    kwargs = {k: v for k, v in raw.items() if k in valid and k != "test_mode"}
    kwargs["test_mode"] = mode
    for required, default in (("specimen_id", ""), ("material", ""), ("area_mm2", 1.0),
                              ("gauge_length_mm", 50.0)):
        kwargs.setdefault(required, default)
    if not isinstance(kwargs.get("sequence_steps"), list):
        kwargs["sequence_steps"] = []
    return TestResult(**kwargs)


def points_to_list(points: List[DataPoint]) -> List[List[Any]]:
    """원시 데이터를 압축 배열로 직렬화"""
    out: List[List[Any]] = []
    for p in points:
        out.append([
            round(p.time_s, 3),
            round(p.displacement_mm, 4),
            round(p.load_n, 2),
            round(p.stress_mpa, 2),
            round(p.strain_pct, 3),
            round(p.ext_disp_mm, 4),
            round(p.ext_strain_pct, 3),
            round(p.ext_raw, 4),
            bool(p.ext_valid),
        ])
    return out


def points_from_list(rows: List[Any]) -> List[DataPoint]:
    points: List[DataPoint] = []
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        values = list(row) + [0.0] * (9 - len(row))
        points.append(DataPoint(
            time_s=_f(values[0]),
            displacement_mm=_f(values[1]),
            load_n=_f(values[2]),
            stress_mpa=_f(values[3]),
            strain_pct=_f(values[4]),
            ext_disp_mm=_f(values[5]),
            ext_strain_pct=_f(values[6]),
            ext_raw=_f(values[7]),
            ext_valid=bool(values[8]),
        ))
    return points


def canonical_bytes(payload: Dict[str, Any]) -> bytes:
    """정렬 + 압축 JSON(UTF-8) 정규화 - 해시 대상"""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_digest(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _slug(text: str, limit: int = 24) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9가-힣-]+", "-", str(text or "")).strip("-")
    return (cleaned or "SPECIMEN")[:limit]


# ----------------------------------------------------------------------
# 이력 저장소
# ----------------------------------------------------------------------
class TestHistoryStore:
    """history/ 폴더 기반 시험 이력 저장·조회·검증"""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or DEFAULT_HISTORY_DIR
        self._summary_cache: Dict[str, Tuple[float, HistorySummary]] = {}

    # ------------------------------------------------------------------
    def _ensure_dir(self) -> bool:
        try:
            os.makedirs(self.base_dir, exist_ok=True)
            return True
        except OSError as e:
            print(f"[TestHistoryStore] 이력 폴더 생성 실패: {e}")
            return False

    def path_for(self, record_id: str) -> str:
        return os.path.join(self.base_dir, f"{record_id}.json")

    def count(self) -> int:
        return len(self.list())

    def last_digest(self) -> str:
        summaries = self.list()
        return summaries[0].digest if summaries else GENESIS_DIGEST

    # ------------------------------------------------------------------
    def save(self, specimen: Specimen, config: TestConfig, result: TestResult,
             points: List[DataPoint], *, completion_reason: str = "",
             calibration: Optional[Dict[str, Any]] = None,
             ext_snapshot: Optional[Dict[str, Any]] = None,
             sequence_events: Optional[List[dict]] = None,
             created_at: Optional[datetime] = None) -> Optional[HistorySummary]:
        """시험 1건을 이력 파일로 저장 (digest + prev_digest 체인)"""
        if not self._ensure_dir():
            return None

        now = created_at or datetime.now()
        created_iso = now.isoformat(timespec="microseconds")
        record_id = f"{now.strftime('%Y%m%d-%H%M%S-%f')}_{_slug(specimen.specimen_id)}"

        prev_digest = self.last_digest()
        steps = sequence_events if sequence_events is not None else (result.sequence_steps or [])

        payload: Dict[str, Any] = {
            "test": {
                "mode": config.mode.name,
                "mode_label": config.mode.value,
                "completion_reason": completion_reason,
            },
            "specimen": specimen_to_dict(specimen),
            "config": config_to_dict(config),
            "extensometer": ext_snapshot if ext_snapshot is not None else asdict(config.ext),
            "calibration": calibration or {},
            "sequence_steps": steps,
            "result": result_to_dict(result),
            "points": points_to_list(points),
            "point_count": len(points),
        }
        digest = compute_digest(payload)

        meta = {
            "specimen_id": specimen.specimen_id,
            "material": specimen.material,
            "mode": config.mode.name,
            "mode_label": config.mode.value,
            "peak_load_n": result.peak_load_n,
            "peak_stress_mpa": result.peak_stress_mpa,
            "elongation_pct": result.elongation_pct,
            "total_samples": len(points),
            "sequence_steps": len(steps),
            "completion_reason": completion_reason,
        }

        doc = {
            "schema": HISTORY_SCHEMA,
            "record_id": record_id,
            "created_at": created_iso,
            "meta": meta,
            "payload": payload,
            "integrity": {
                "algorithm": "sha256",
                "digest": digest,
                "prev_digest": prev_digest,
                "canonicalization": "json.sort_keys+compact+utf8",
            },
        }

        path = self.path_for(record_id)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"[TestHistoryStore] 이력 저장 실패: {e}")
            return None

        summary = self._summary_from_doc(doc, path)
        self._summary_cache[path] = (os.path.getmtime(path), summary)
        return summary

    # ------------------------------------------------------------------
    def list(self) -> List[HistorySummary]:
        """이력 목록 (최신 순)"""
        if not os.path.isdir(self.base_dir):
            return []
        summaries: List[HistorySummary] = []
        for name in os.listdir(self.base_dir):
            if not name.lower().endswith(".json"):
                continue
            path = os.path.join(self.base_dir, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            cached = self._summary_cache.get(path)
            if cached and cached[0] == mtime:
                summaries.append(cached[1])
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    doc = json.load(f)
            except (OSError, ValueError) as e:
                print(f"[TestHistoryStore] 이력 파일을 읽지 못했습니다 ({name}): {e}")
                continue
            if not isinstance(doc, dict) or doc.get("schema") != HISTORY_SCHEMA:
                continue
            summary = self._summary_from_doc(doc, path)
            self._summary_cache[path] = (mtime, summary)
            summaries.append(summary)
        summaries.sort(key=lambda s: (s.created_at, s.record_id), reverse=True)
        return summaries

    def _summary_from_doc(self, doc: Dict[str, Any], path: str) -> HistorySummary:
        meta = doc.get("meta") or {}
        integrity = doc.get("integrity") or {}
        return HistorySummary(
            record_id=str(doc.get("record_id", os.path.basename(path).replace(".json", ""))),
            created_at=str(doc.get("created_at", "")),
            specimen_id=str(meta.get("specimen_id", "")),
            material=str(meta.get("material", "")),
            mode=str(meta.get("mode", "")),
            mode_label=str(meta.get("mode_label", "")),
            peak_load_n=_f(meta.get("peak_load_n")),
            peak_stress_mpa=_f(meta.get("peak_stress_mpa")),
            elongation_pct=_f(meta.get("elongation_pct")),
            total_samples=_i(meta.get("total_samples")),
            path=path,
            digest=str(integrity.get("digest", "")),
            prev_digest=str(integrity.get("prev_digest", "")),
            sequence_steps=_i(meta.get("sequence_steps")),
            completion_reason=str(meta.get("completion_reason", "")),
        )

    # ------------------------------------------------------------------
    def _read_doc(self, record_id: str) -> Optional[Dict[str, Any]]:
        path = self.path_for(record_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if isinstance(doc, dict):
                return doc
        except (OSError, ValueError) as e:
            print(f"[TestHistoryStore] 이력 파일 손상 ({record_id}): {e}")
        return None

    def load(self, record_id: str) -> Optional[HistoryRecord]:
        """이력 1건을 불러와 시험 객체로 복원 (무결성 결과도 함께 담는다)"""
        doc = self._read_doc(record_id)
        if doc is None:
            return None
        payload = doc.get("payload") or {}
        integrity_doc = doc.get("integrity") or {}
        summary = self._summary_from_doc(doc, self.path_for(record_id))

        integrity = self._verify_doc(doc)
        specimen = specimen_from_dict(payload.get("specimen") or {})
        config = config_from_dict(payload.get("config") or {})
        result = result_from_dict(payload.get("result") or {})
        points = points_from_list(payload.get("points") or [])
        if not result.sequence_steps:
            result.sequence_steps = payload.get("sequence_steps") or []

        return HistoryRecord(
            summary=summary,
            specimen=specimen,
            config=config,
            result=result,
            points=points,
            calibration=payload.get("calibration") or {},
            extensometer=payload.get("extensometer") or {},
            integrity=integrity,
            raw=integrity_doc if isinstance(integrity_doc, dict) else {},
        )

    # ------------------------------------------------------------------
    def verify(self, record_id: str) -> IntegrityResult:
        doc = self._read_doc(record_id)
        if doc is None:
            return IntegrityResult(record_id, False, "파일을 읽을 수 없음")
        return self._verify_doc(doc)

    def _verify_doc(self, doc: Dict[str, Any]) -> IntegrityResult:
        record_id = str(doc.get("record_id", ""))
        integrity = doc.get("integrity") or {}
        stored = str(integrity.get("digest", ""))
        payload = doc.get("payload")
        if not isinstance(payload, dict) or not stored:
            return IntegrityResult(record_id, False, "해시 정보 없음")
        try:
            actual = compute_digest(payload)
        except (TypeError, ValueError) as e:
            return IntegrityResult(record_id, False, f"해시 계산 실패: {e}")
        if hmac.compare_digest(stored, actual):
            return IntegrityResult(record_id, True, "")
        return IntegrityResult(record_id, False, "저장 후 내용이 변경됨")

    def verify_all(self) -> Dict[str, IntegrityResult]:
        """모든 이력의 무결성 검증 결과"""
        return {s.record_id: self.verify(s.record_id) for s in self.list()}

    def verify_chain(self) -> ChainResult:
        """전체 체인 검증: 개별 해시 + prev_digest 연결"""
        summaries = sorted(self.list(), key=lambda s: (s.created_at, s.record_id))
        problems: List[str] = []
        previous = GENESIS_DIGEST
        ok_count = 0
        for summary in summaries:
            doc = self._read_doc(summary.record_id)
            if doc is None:
                problems.append(f"{summary.record_id}: 파일 없음")
                continue
            verity = self._verify_doc(doc)
            integrity = doc.get("integrity") or {}
            prev = str(integrity.get("prev_digest", ""))
            payload = doc.get("payload")
            try:
                current = compute_digest(payload) if isinstance(payload, dict) else ""
            except (TypeError, ValueError):
                current = ""
            if not verity.ok:
                problems.append(f"{summary.record_id}: 해시 불일치")
            if prev != previous:
                problems.append(f"{summary.record_id}: 직전 이력 연결 끊김")
            if verity.ok and prev == previous:
                ok_count += 1
            previous = current or str(integrity.get("digest", ""))
        return ChainResult(total=len(summaries), ok_count=ok_count, problems=problems)

    # ------------------------------------------------------------------
    def record_to_session_input(self, record: HistoryRecord) -> Dict[str, Any]:
        """이력 -> 세션(오버레이) 추가용 인자 묶음"""
        return {
            "specimen": record.specimen,
            "config": record.config,
            "result": record.result,
            "points": record.points,
            "completion_reason": record.summary.completion_reason,
            "history_id": record.summary.record_id,
            "integrity_digest": record.summary.digest,
            "step_events": record.result.sequence_steps,
            "completed_at": record.summary.created_display,
        }
