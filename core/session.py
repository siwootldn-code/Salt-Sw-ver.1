"""
Salt Sw ver.1 - Specimen Session & Batch Statistics (시편 세션 · 배치 통계)
한 세션(묶음 시험)에서 완료된 시편들을 보관하고, 겹쳐 그리기(오버레이)와
배치 통계(평균/표준편차/변동계수/최소/최대)를 계산한다.

- 세션 번호는 SP-001, SP-002 ... 순서로 매기고 시편마다 산업용 색상을 하나씩 배정한다.
- 통계는 "보기" 체크된 시편만 대상으로 한다 (선택 시편 기준).
- 표준편차는 표본표준편차(n-1), 변동계수(CV%) = 표준편차 / 평균 x 100 이다.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import DataPoint, Specimen, TestConfig, TestResult

# 산업용 오버레이 색상 (선명하지만 채도가 낮은 계측기 팔레트)
OVERLAY_COLORS: List[str] = [
    "#1D4ED8",  # precision blue
    "#C2410C",  # burnt orange
    "#047857",  # deep green
    "#7C3AED",  # violet
    "#0E7490",  # teal
    "#B91C1C",  # dark red
    "#475569",  # slate
    "#A16207",  # dark amber
]

# 배치 통계 대상 물성: (결과 속성, 단위, 표시 자릿수)
BATCH_METRICS: List[Tuple[str, str, int]] = [
    ("peak_load_n", "N", 1),
    ("peak_stress_mpa", "MPa", 2),
    ("yield_stress_mpa", "MPa", 2),
    ("elastic_modulus_gpa", "GPa", 2),
    ("elongation_pct", "%", 2),
]

METRIC_DECIMALS: Dict[str, int] = {key: decimals for key, _unit, decimals in BATCH_METRICS}
METRIC_UNITS: Dict[str, str] = {key: unit for key, unit, _dec in BATCH_METRICS}


def metric_value(result: Optional[TestResult], key: str) -> Optional[float]:
    """결과 객체에서 통계 대상 값을 꺼낸다 (없으면 None)"""
    if result is None:
        return None
    value = getattr(result, key, None)
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


@dataclass
class MetricStat:
    """한 물성에 대한 배치 통계"""
    key: str
    unit: str
    n: int
    mean: float = 0.0
    std: float = 0.0
    cv_pct: float = 0.0
    minimum: float = 0.0
    maximum: float = 0.0
    values: List[float] = field(default_factory=list)

    @property
    def decimals(self) -> int:
        return METRIC_DECIMALS.get(self.key, 2)

    @property
    def has_data(self) -> bool:
        return self.n > 0

    # ------------------------------------------------------------------
    def formatted(self, field_name: str) -> str:
        """지정 항목을 표시 문자열로 변환 (값이 없으면 '-')"""
        if field_name == "n":
            return str(self.n)
        if not self.has_data:
            return "-"
        if field_name == "mean":
            value = self.mean
        elif field_name == "std":
            value = self.std
        elif field_name == "cv_pct":
            value = self.cv_pct
        elif field_name == "min":
            value = self.minimum
        elif field_name == "max":
            value = self.maximum
        else:
            return "-"
        decimals = 2 if field_name == "cv_pct" else self.decimals
        return f"{value:,.{decimals}f}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "unit": self.unit,
            "n": self.n,
            "mean": round(self.mean, 4),
            "std": round(self.std, 4),
            "cv_pct": round(self.cv_pct, 3),
            "min": round(self.minimum, 4),
            "max": round(self.maximum, 4),
        }


def compute_stat(values: Sequence[float], key: str = "") -> MetricStat:
    """값 목록으로 표본 통계 계산 (표본표준편차 n-1)"""
    clean = [float(v) for v in values if v is not None and not math.isnan(float(v))]
    unit = METRIC_UNITS.get(key, "")
    n = len(clean)
    if n == 0:
        return MetricStat(key=key, unit=unit, n=0)
    mean = sum(clean) / n
    if n > 1:
        variance = sum((v - mean) ** 2 for v in clean) / (n - 1)
        std = math.sqrt(variance)
    else:
        std = 0.0
    cv = (std / abs(mean) * 100.0) if mean != 0 else 0.0
    return MetricStat(
        key=key, unit=unit, n=n, mean=mean, std=std, cv_pct=cv,
        minimum=min(clean), maximum=max(clean), values=clean,
    )


@dataclass
class SessionRecord:
    """세션에 보관된 시편 1건"""
    seq: int
    specimen: Specimen
    config: TestConfig
    result: TestResult
    points: List[DataPoint] = field(default_factory=list)
    color: str = OVERLAY_COLORS[0]
    visible: bool = True
    completed_at: str = ""
    completion_reason: str = ""
    history_id: str = ""
    integrity_digest: str = ""
    step_events: List[dict] = field(default_factory=list)

    # ------------------------------------------------------------------
    @property
    def session_label(self) -> str:
        """세션 표시명 (SP-001, SP-002 ...)"""
        return f"SP-{self.seq:03d}"

    @property
    def specimen_id(self) -> str:
        return self.specimen.specimen_id if self.specimen else ""

    @property
    def test_mode(self) -> str:
        return self.config.mode.name if self.config else ""

    def _excluded_windows(self) -> List[Tuple[float, float]]:
        """
        그래프에서 제외할 구간.
        시퀀스의 복귀(RETURN) 단계는 재료 응답이 아니라 시험 후 크로스헤드 이동이므로
        곡선에는 포함하지 않는다 (원시 데이터 · 이력 · 단계 표에는 그대로 남는다).
        """
        windows: List[Tuple[float, float]] = []
        for event in self.step_events or []:
            if str(event.get("action", "")) == "RETURN":
                try:
                    windows.append((float(event.get("started_at", 0.0)),
                                    float(event.get("ended_at", 0.0))))
                except (TypeError, ValueError):
                    continue
        return windows

    def curve_points(self) -> List[DataPoint]:
        """그래프에 그릴 계측점 (복귀 구간 제외)"""
        windows = self._excluded_windows()
        if not windows:
            return list(self.points)
        return [p for p in self.points if not any(start <= p.time_s <= end for start, end in windows)]

    def curve(self, mode: str = "ss") -> Tuple[List[float], List[float]]:
        """오버레이용 곡선 좌표 (ss: 응력-변형률, ld: 하중-변위)"""
        points = self.curve_points()
        if mode == "ld":
            return [p.displacement_mm for p in points], [p.load_n for p in points]
        return [p.strain_pct for p in points], [p.stress_mpa for p in points]

    def step_markers(self, mode: str = "ss") -> List[Tuple[float, int]]:
        """단계 시작 지점 표시용 (x좌표, 단계번호)"""
        markers: List[Tuple[float, int]] = []
        if not self.step_events or not self.points:
            return markers
        for ev in self.step_events:
            start = float(ev.get("started_at", 0.0))
            point = min(self.points, key=lambda p: abs(p.time_s - start))
            x = point.displacement_mm if mode == "ld" else point.strain_pct
            markers.append((x, int(ev.get("index", 0)) + 1))
        return markers


class SpecimenSession:
    """한 세션의 시편 목록과 배치 통계"""

    def __init__(self):
        self._records: List[SessionRecord] = []

    # ------------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._records)

    @property
    def records(self) -> List[SessionRecord]:
        return list(self._records)

    @property
    def visible_records(self) -> List[SessionRecord]:
        return [r for r in self._records if r.visible]

    def next_seq(self) -> int:
        return (max((r.seq for r in self._records), default=0) + 1)

    def next_color(self) -> str:
        seq = self.next_seq()
        return OVERLAY_COLORS[(seq - 1) % len(OVERLAY_COLORS)]

    def add(self, specimen: Specimen, config: TestConfig, result: TestResult,
            points: Optional[List[DataPoint]] = None, *,
            completion_reason: str = "", history_id: str = "",
            integrity_digest: str = "", step_events: Optional[List[dict]] = None,
            completed_at: Optional[str] = None) -> SessionRecord:
        seq = self.next_seq()
        record = SessionRecord(
            seq=seq,
            specimen=specimen,
            config=config,
            result=result,
            points=list(points or []),
            color=OVERLAY_COLORS[(seq - 1) % len(OVERLAY_COLORS)],
            visible=True,
            completed_at=completed_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            completion_reason=completion_reason,
            history_id=history_id,
            integrity_digest=integrity_digest,
            step_events=list(step_events or getattr(result, "sequence_steps", []) or []),
        )
        self._records.append(record)
        self._records.sort(key=lambda r: r.seq)
        return record

    def get(self, seq: int) -> Optional[SessionRecord]:
        for rec in self._records:
            if rec.seq == seq:
                return rec
        return None

    def remove(self, seq: int) -> bool:
        before = len(self._records)
        self._records = [r for r in self._records if r.seq != seq]
        return len(self._records) < before

    def clear(self) -> None:
        self._records = []

    def set_visible(self, seq: int, visible: bool) -> bool:
        rec = self.get(seq)
        if rec is None:
            return False
        rec.visible = bool(visible)
        return True

    def set_all_visible(self, visible: bool) -> None:
        for rec in self._records:
            rec.visible = bool(visible)

    def has_history_record(self, history_id: str) -> bool:
        return any(r.history_id == history_id for r in self._records)

    # ------------------------------------------------------------------
    def statistics(self, keys: Optional[Sequence[str]] = None) -> List[MetricStat]:
        """보기(선택) 상태인 시편들로 배치 통계 계산"""
        keys = list(keys) if keys else [key for key, _u, _d in BATCH_METRICS]
        visible = self.visible_records
        stats: List[MetricStat] = []
        for key in keys:
            values = [v for v in (metric_value(r.result, key) for r in visible) if v is not None]
            stats.append(compute_stat(values, key))
        return stats

    def statistics_for(self, key: str) -> MetricStat:
        return self.statistics([key])[0]

    def summary_rows(self) -> List[Dict[str, Any]]:
        """엑셀/PDF 요약용 시편별 행 데이터"""
        rows = []
        for rec in self._records:
            res = rec.result
            rows.append({
                "seq": rec.seq,
                "session_label": rec.session_label,
                "specimen_id": rec.specimen_id,
                "material": rec.specimen.material if rec.specimen else "",
                "mode": rec.test_mode,
                "peak_load_n": res.peak_load_n,
                "peak_stress_mpa": res.peak_stress_mpa,
                "yield_stress_mpa": res.yield_stress_mpa,
                "elastic_modulus_gpa": res.elastic_modulus_gpa,
                "elongation_pct": res.elongation_pct,
                "break_displacement_mm": res.break_displacement_mm,
                "energy_joule": res.energy_joule,
                "status": rec.completion_reason,
                "completed_at": rec.completed_at,
                "history_id": rec.history_id,
                "visible": rec.visible,
                "color": rec.color,
                "samples": len(rec.points),
            })
        return rows
