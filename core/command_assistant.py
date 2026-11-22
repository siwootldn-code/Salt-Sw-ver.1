"""
Salt Sw ver.1 - Quick Test Command Assistant (오프라인 자연어 명령 해석)

현장 작업자가 한 줄로 말한 시험 명령에서 시험 종류 · 재질 · 시편 형상/치수 · 제어 방식 ·
속도 · PID 프로필 · 자동 저장 여부를 해석해 '시편 세팅 카드'에 채울 계획(TestCommandPlan)을 만든다.

원칙
- 인터넷 · 유료 API · 외부 모델을 쓰지 않는다. 규칙(정규식) 기반으로 오프라인에서 동작한다.
- 치수가 빠진 명령은 시험 종류와 기본 규격 · 권장 속도만 먼저 잡고, 빠진 치수를
  missing_fields 에 남긴다. 임의로 값을 채워 시험을 시작하지 않는다.
- 작업자가 [시편 세팅 완료 · 시험 시작]을 누르기 전에는 어떤 축도 움직이지 않는다.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .i18n import tr
from .models import BendingType, HoldingType, SpecimenType, TestMode
from .pid_controller import ControlMode


# ----------------------------------------------------------------------
# 재질 사전 (표시 이름 · 강성군)
# 강성군은 PID 프리셋 자동 선택과 권장 속도 산정에 쓴다.
# ----------------------------------------------------------------------
MATERIALS: Dict[str, Tuple[str, str, str]] = {
    "SS400": ("SS400 (일반구조용강)", "SS400 Structural Steel", "metal"),
    "SS275": ("SS275 (일반구조용강)", "SS275 Structural Steel", "metal"),
    "SS330": ("SS330 (일반구조용강)", "SS330 Structural Steel", "metal"),
    "SM490": ("SM490 (용접구조용강)", "SM490 Welded Steel", "metal"),
    "S45C": ("S45C (기계구조용 탄소강)", "S45C Carbon Steel", "metal"),
    "SUS304": ("SUS304 (스테인리스강)", "SUS304 Stainless Steel", "metal"),
    "AL6061": ("AL6061 (알루미늄 합금)", "AL6061 Aluminium Alloy", "metal"),
    "ABS": ("ABS (엔지니어링 플라스틱)", "ABS Engineering Plastic", "polymer"),
    "PC": ("PC (폴리카보네이트)", "PC (Polycarbonate)", "polymer"),
    "PP": ("PP (폴리프로필렌)", "PP (Polypropylene)", "polymer"),
    "PE": ("PE (폴리에틸렌)", "PE (Polyethylene)", "polymer"),
    "PET": ("PET (폴리에스터 필름)", "PET Film", "polymer"),
    "PI": ("PI (폴리이미드 필름)", "PI (Polyimide Film)", "polymer"),
    "NBR": ("NBR (니트릴 고무)", "NBR (Nitrile Rubber)", "elastomer"),
    "EPDM": ("EPDM (에틸렌프로필렌 고무)", "EPDM Rubber", "elastomer"),
    "SILICONE": ("실리콘 고무", "Silicone Rubber", "elastomer"),
}
DEFAULT_MATERIAL = "SS400"

# 규격 코드 없이 부르는 이름
MATERIAL_ALIASES: Tuple[Tuple[str, str], ...] = (
    ("스테인리스", "SUS304"), ("스텐레스", "SUS304"), ("스텐", "SUS304"), ("sus", "SUS304"),
    ("알루미늄", "AL6061"), ("알미늄", "AL6061"),
    ("탄소강", "S45C"), ("기계구조용", "S45C"),
    ("연강", "SS400"), ("일반구조용", "SS400"), ("구조용강", "SS400"),
    ("니트릴", "NBR"), ("고무", "NBR"), ("러버", "NBR"),
    ("실리콘", "SILICONE"), ("실리콘고무", "SILICONE"),
    ("폴리카보네이트", "PC"), ("폴리프로필렌", "PP"), ("폴리에틸렌", "PE"),
    ("폴리이미드", "PI"), ("엔지니어링플라스틱", "ABS"),
)

# 시험 종류별 적용 규격 (카드에 표시)
STANDARDS = {
    TestMode.TENSILE: ("KS B 0802 / ASTM E8", "KS B 0802 / ASTM E8"),
    TestMode.COMPRESSION: ("ASTM E9", "ASTM E9"),
    TestMode.BENDING: ("KS B 0804 / ASTM D790", "KS B 0804 / ASTM D790"),
    TestMode.HOLDING: ("ASTM E139 / ASTM E328", "ASTM E139 / ASTM E328"),
    TestMode.SEQUENCE: ("사내 시퀀스 프로그램", "In-house sequence program"),
}

MODE_KEYWORDS: Tuple[Tuple[TestMode, Tuple[str, ...]], ...] = (
    (TestMode.TENSILE, ("인장", "tensile", "tension", "당김", "당겨")),
    (TestMode.COMPRESSION, ("압축", "compression", "compressive", "compress", "눌러")),
    (TestMode.BENDING, ("굽힘", "휨", "bend", "bending", "flexural")),
    (TestMode.SEQUENCE, ("시퀀스", "sequence", "다단계")),
    (TestMode.HOLDING, ("유지", "크리프", "creep", "relaxation", "이완", "hold")),
)

SHAPE_KEYWORDS: Tuple[Tuple[SpecimenType, Tuple[str, ...]], ...] = (
    (SpecimenType.FLAT, ("판재", "평판", "플랫", "flat", "plate", "sheet", "strip", "판")),
    (SpecimenType.ROUND, ("봉재", "환봉", "둥근", "원형", "round", "bar", "rod", "cylinder")),
    (SpecimenType.TUBE, ("관형", "파이프", "tube", "pipe")),
)

# 제어 방식 기본 목표 속도 (명령에 수치가 없을 때)
DEFAULT_RATE = {
    ControlMode.LOAD_RATE: 6000.0,    # N/min
    ControlMode.STRESS_RATE: 10.0,    # MPa/s
    ControlMode.LOAD_HOLD: 3000.0,    # N/min (접근 속도)
}

# 재질군별 권장 시험 속도 배율 (금속 1배 기준)
SPEED_FACTOR = {"metal": 1.0, "polymer": 4.0, "elastomer": 10.0}

BASE_SPEED_MM_MIN = {
    TestMode.TENSILE: 5.0,
    TestMode.COMPRESSION: 2.0,
    TestMode.BENDING: 2.0,
    TestMode.HOLDING: 5.0,
    TestMode.SEQUENCE: 5.0,
}

MISSING_FIELD_ORDER = ("width", "thickness", "diameter", "gauge_length", "span_length")


def material_label(code: str, lang: str = "KO") -> str:
    """재질 코드 → 화면 표시 이름"""
    entry = MATERIALS.get(str(code or "").upper())
    if not entry:
        return str(code or "")
    return entry[1] if str(lang).upper() == "EN" else entry[0]


def material_family(code: str) -> str:
    entry = MATERIALS.get(str(code or "").upper())
    return entry[2] if entry else "metal"


def standard_label(mode: TestMode, lang: str = "KO") -> str:
    ko, en = STANDARDS.get(mode, ("-", "-"))
    return en if str(lang).upper() == "EN" else ko


def recommended_speed(mode: TestMode, material_code: str, step: float = 0.1) -> float:
    """재질군과 시험 종류에 맞는 권장 시험 속도 (mm/min, 0.1 단위)"""
    speed = BASE_SPEED_MM_MIN.get(mode, 5.0) * SPEED_FACTOR.get(material_family(material_code), 1.0)
    return round(round(speed / step) * step, 2)


def mode_label(mode: TestMode, lang: str = "KO") -> str:
    return tr(lang, f"mode_{mode.name.lower()}", mode.value)


def control_label(control: str, lang: str = "KO") -> str:
    key = {
        ControlMode.DISP.value: "ctl_mode_disp",
        ControlMode.LOAD_RATE.value: "ctl_mode_load",
        ControlMode.STRESS_RATE.value: "ctl_mode_stress",
        ControlMode.LOAD_HOLD.value: "ctl_mode_hold",
    }.get(str(control).upper(), "ctl_mode_disp")
    return tr(lang, key)


def field_label(field_key: str, lang: str = "KO") -> str:
    return tr(lang, f"asst_{field_key}", field_key)


# ----------------------------------------------------------------------
# 해석 결과
# ----------------------------------------------------------------------
@dataclass
class TestCommandPlan:
    """명령 1건을 해석한 시험 계획 (시편 세팅 카드의 초기값)"""
    mode: TestMode = TestMode.TENSILE
    material_code: str = DEFAULT_MATERIAL
    specimen_type: SpecimenType = SpecimenType.FLAT

    width_mm: Optional[float] = None
    thickness_mm: Optional[float] = None
    diameter_mm: Optional[float] = None
    gauge_length_mm: Optional[float] = None
    span_length_mm: Optional[float] = None

    bending_type: BendingType = BendingType.THREE_POINT
    holding_type: HoldingType = HoldingType.LOAD_HOLD

    control_mode: str = ControlMode.DISP.value
    target_rate: float = 0.0
    test_speed_mm_min: float = 5.0
    target_holding_val: float = 1000.0
    holding_duration_s: float = 60.0

    pid_profile_id: str = "metal"
    auto_export: bool = True

    missing_fields: List[str] = field(default_factory=list)
    notes: List[Dict[str, Any]] = field(default_factory=list)
    raw_text: str = ""
    lang: str = "KO"

    # ------------------------------------------------------------------
    @property
    def is_complete(self) -> bool:
        """시편 치수가 모두 채워져 바로 시험할 수 있는지"""
        return not self.missing_fields

    @property
    def uses_pid(self) -> bool:
        return str(self.control_mode).upper() != ControlMode.DISP.value

    def missing_labels(self, lang: str = "KO") -> List[str]:
        return [field_label(key, lang) for key in self.missing_fields]

    def note_texts(self, lang: str = "KO") -> List[str]:
        texts: List[str] = []
        for note in self.notes:
            template = tr(lang, str(note.get("key", "")), "")
            if not template:
                continue
            try:
                texts.append(template.format(**note.get("args", {})))
            except (KeyError, IndexError, ValueError):
                texts.append(template)
        return texts


# ----------------------------------------------------------------------
# 해석기
# ----------------------------------------------------------------------
class CommandAssistant:
    """오프라인 자연어 시험 명령 해석기"""

    @staticmethod
    def parse(text: str, lang: str = "KO") -> TestCommandPlan:
        raw = str(text or "").strip()
        normalized = _normalize(raw)
        plan = TestCommandPlan(raw_text=raw, lang=lang)

        # 1) 재질 → 해석된 재질 문자열은 숫자 해석에서 빠지도록 공백으로 지운다.
        code, span = _find_material(normalized)
        work = normalized
        if code and span:
            plan.material_code = code
            work = normalized[:span[0]] + " " * (span[1] - span[0]) + normalized[span[1]:]
        else:
            plan.notes.append({"key": "asst_note_mat_default", "args": {}})

        # 2) 시험 종류
        mode = _find_mode(normalized)
        if mode is None:
            mode = TestMode.TENSILE
            plan.notes.append({"key": "asst_note_mode_default", "args": {}})
        plan.mode = mode
        if mode is TestMode.BENDING:
            plan.bending_type = _find_bending_type(normalized)
        if mode is TestMode.SEQUENCE:
            plan.notes.append({"key": "asst_note_sequence", "args": {}})

        # 3) 시편 형상
        shape = _find_shape(normalized)
        if shape is SpecimenType.TUBE:
            shape = SpecimenType.FLAT
            plan.notes.append({"key": "asst_note_shape_tube", "args": {}})
        plan.specimen_type = shape or SpecimenType.FLAT

        # 4) 치수
        plan.width_mm = _number(r"(?:폭|너비|width)\s*[:=]?\s*(\d+(?:\.\d+)?)", work)
        plan.thickness_mm = _number(
            r"(?:두께|thickness|thk)\s*[:=]?\s*(\d+(?:\.\d+)?)", work)
        if plan.thickness_mm is None:
            plan.thickness_mm = _number(r"(?:^|\s)t\s*[:=]?\s*(\d+(?:\.\d+)?)(?=\s|$|mm)", work)
        plan.diameter_mm = _number(
            r"(?:직경|지름|외경|diameter|dia\.?|∅|Ø|φ|phi)\s*[:=]?\s*(\d+(?:\.\d+)?)", work)
        plan.gauge_length_mm = _number(
            r"(?:표점\s*거리|표점|gauge\s*length|gauge|gl|l0)\s*[:=]?\s*(\d+(?:\.\d+)?)", work)
        plan.span_length_mm = _number(
            r"(?:지간\s*거리|지간|지지대\s*간격|스팬|support\s*span|span)\s*[:=]?\s*(\d+(?:\.\d+)?)", work)

        # "12.5x3.2" 처럼 곱셈 표기로만 준 경우 폭 × 두께로 본다
        pair = _dimension_pair(work)
        if pair:
            if plan.width_mm is None:
                plan.width_mm = pair[0]
            if plan.thickness_mm is None:
                plan.thickness_mm = pair[1]

        if plan.specimen_type is SpecimenType.ROUND and plan.diameter_mm is None:
            # 봉재인데 직경 표기가 없으면 첫 단독 치수를 직경으로 본다
            plan.diameter_mm = _first_plain_dimension(work)

        # 5) 제어 방식과 속도
        _detect_control(plan, work)

        # 6) PID 프로필 (명령에 없으면 재질 강성군에 맞춘다)
        _detect_pid(plan, normalized)

        # 7) 자동 저장 여부
        if _contains_any(normalized, ("저장하지 마", "저장 안", "자동 저장 안", "자동저장 안",
                                      "no auto", "don't save", "do not save")):
            plan.auto_export = False
        elif _contains_any(normalized, ("저장", "save", "auto")):
            plan.auto_export = True

        # 8) 누락 치수 정리
        plan.missing_fields = _missing_fields(plan)
        return plan


# ----------------------------------------------------------------------
# 내부 도우미
# ----------------------------------------------------------------------
def _normalize(text: str) -> str:
    """전각 기호를 반각으로 바꾸고 소문자로 맞춘 작업 문자열"""
    table = str.maketrans({
        "×": "x", "✕": "x", "Ｘ": "x", "＊": "*",
        "／": "/", "．": ".", "，": ",", "　": " ",
        "Ø": "Ø", "φ": "φ",
    })
    return text.translate(table).strip().lower()


def _contains_any(text: str, words) -> bool:
    return any(word in text for word in words)


def _find_material(text: str) -> Tuple[Optional[str], Optional[Tuple[int, int]]]:
    """재질 코드/이름을 찾아 (코드, 위치) 반환"""
    for code in sorted(MATERIALS, key=len, reverse=True):
        match = re.search(r"(?<![a-z0-9])" + re.escape(code.lower()) + r"(?![a-z0-9])", text)
        if match:
            return code, (match.start(), match.end())
    for alias, code in sorted(MATERIAL_ALIASES, key=lambda item: len(item[0]), reverse=True):
        match = re.search(re.escape(alias.lower()), text)
        if match:
            return code, (match.start(), match.end())
    return None, None


def _word_index(text: str, word: str) -> int:
    """영문 키워드는 단어 경계로 찾는다 (threshold 안의 hold 같은 오인 방지)"""
    if re.fullmatch(r"[a-z0-9 .\-]+", word):
        match = re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text)
        return match.start() if match else -1
    return text.find(word)


def _find_mode(text: str) -> Optional[TestMode]:
    """가장 먼저 나온 시험 종류 키워드 (유지 keyword는 다른 모드가 없을 때만)"""
    found: List[Tuple[int, int, TestMode]] = []
    for priority, (mode, words) in enumerate(MODE_KEYWORDS):
        for word in words:
            index = _word_index(text, word)
            if index >= 0:
                found.append((priority, index, mode))
    if not found:
        return None
    # 인장/압축/굽힘/시퀀스가 있으면 유지보다 우선한다.
    found.sort(key=lambda item: (item[2] is TestMode.HOLDING, item[1], item[0]))
    return found[0][2]


def _find_bending_type(text: str) -> BendingType:
    if _contains_any(text, ("4점", "4-point", "4 point", "four point", "4p")):
        return BendingType.FOUR_POINT
    if _contains_any(text, ("3점", "3-point", "3 point", "three point", "3p")):
        return BendingType.THREE_POINT
    return BendingType.THREE_POINT


def _find_shape(text: str) -> Optional[SpecimenType]:
    best: Optional[Tuple[int, SpecimenType]] = None
    for shape, words in SHAPE_KEYWORDS:
        for word in words:
            index = _word_index(text, word)
            if index >= 0 and (best is None or index < best[0]):
                best = (index, shape)
    return best[1] if best else None


def _number(pattern: str, text: str) -> Optional[float]:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _dimension_pair(text: str) -> Optional[Tuple[float, float]]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*[x*]\s*(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def _first_plain_dimension(text: str) -> Optional[float]:
    """키워드 없이 '10mm' 처럼 단독으로 쓴 치수 하나"""
    candidates = [
        float(value) for value in re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*mm(?!\s*/)", text)
    ]
    return candidates[0] if candidates else None


def _detect_control(plan: TestCommandPlan, text: str) -> None:
    """제어 방식 · 목표 속도 · 유지 조건 해석"""
    # 1) 하중 속도 (N/min)
    match = re.search(r"(\d+(?:\.\d+)?)\s*(kn|n)\s*/\s*(?:min|분)", text)
    if match or _contains_any(text, ("하중 속도", "load rate", "n/min")):
        plan.control_mode = ControlMode.LOAD_RATE.value
        if match:
            value = float(match.group(1)) * (1000.0 if match.group(2) == "kn" else 1.0)
            plan.target_rate = value
        else:
            plan.target_rate = DEFAULT_RATE[ControlMode.LOAD_RATE]
            plan.notes.append({"key": "asst_note_rate_default",
                               "args": {"value": f"{plan.target_rate:,.0f}", "unit": "N/min"}})
        plan.test_speed_mm_min = recommended_speed(plan.mode, plan.material_code)
        return

    # 2) 응력 속도 (MPa/s)
    match = re.search(r"(\d+(?:\.\d+)?)\s*mpa\s*/\s*(?:s|sec|초)", text)
    if match or _contains_any(text, ("응력 속도", "stress rate", "mpa/s")):
        plan.control_mode = ControlMode.STRESS_RATE.value
        if match:
            plan.target_rate = float(match.group(1))
        else:
            plan.target_rate = DEFAULT_RATE[ControlMode.STRESS_RATE]
            plan.notes.append({"key": "asst_note_rate_default",
                               "args": {"value": f"{plan.target_rate:g}", "unit": "MPa/s"}})
        plan.test_speed_mm_min = recommended_speed(plan.mode, plan.material_code)
        return

    # 3) 하중 유지 (크리프)
    if _contains_any(text, ("하중 유지", "load hold", "크리프", "creep")):
        plan.mode = TestMode.HOLDING
        plan.holding_type = HoldingType.LOAD_HOLD
        plan.control_mode = ControlMode.LOAD_HOLD.value
        plan.target_rate = DEFAULT_RATE[ControlMode.LOAD_HOLD]
        plan.test_speed_mm_min = recommended_speed(plan.mode, plan.material_code)
        target = _hold_target(text)
        if target is not None:
            plan.target_holding_val = target
        duration = _hold_duration(text)
        if duration is not None:
            plan.holding_duration_s = duration
        return

    # 4) 변위 유지 (응력 이완)
    if _contains_any(text, ("변위 유지", "disp hold", "이완", "relaxation")):
        plan.mode = TestMode.HOLDING
        plan.holding_type = HoldingType.DISP_HOLD
        plan.control_mode = ControlMode.DISP.value
        duration = _hold_duration(text)
        if duration is not None:
            plan.holding_duration_s = duration
        speed = _number(r"(\d+(?:\.\d+)?)\s*mm\s*/\s*(?:min|분)", text)
        if speed is not None:
            plan.test_speed_mm_min = speed
        else:
            plan.test_speed_mm_min = recommended_speed(plan.mode, plan.material_code)
            plan.notes.append({"key": "asst_note_speed_default",
                               "args": {"value": f"{plan.test_speed_mm_min:g}"}})
        return

    # 5) 변위 속도 (기본)
    speed = _number(r"(\d+(?:\.\d+)?)\s*mm\s*/\s*(?:min|분)", text)
    if speed is not None:
        plan.test_speed_mm_min = speed
    elif _contains_any(text, ("mm/min", "mm / min")):
        plan.test_speed_mm_min = recommended_speed(plan.mode, plan.material_code)
        plan.notes.append({"key": "asst_note_speed_default",
                           "args": {"value": f"{plan.test_speed_mm_min:g}"}})
    else:
        plan.test_speed_mm_min = recommended_speed(plan.mode, plan.material_code)
        plan.notes.append({"key": "asst_note_speed_default",
                           "args": {"value": f"{plan.test_speed_mm_min:g}"}})



def _hold_target(text: str) -> Optional[float]:
    match = re.search(r"(?:목표|유지)\s*(?:하중)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(kn|n)\b", text)
    if not match:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(kn|n)\s*(?:유지|에서|으로|hold)", text)
    if not match:
        return None
    return float(match.group(1)) * (1000.0 if match.group(2) == "kn" else 1.0)


def _hold_duration(text: str) -> Optional[float]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:초|sec|seconds?|s)(?![a-z0-9])", text)
    if not match:
        return None
    return float(match.group(1))


def _detect_pid(plan: TestCommandPlan, text: str) -> None:
    """PID 프로필 명시 또는 재질 강성군에 맞춘 자동 선택"""
    explicit = None
    if _contains_any(text, ("pid 1", "연질", "soft", "elastomer")):
        explicit = "elastomer"
    elif _contains_any(text, ("pid 2", "중질", "필름", "medium", "film")):
        explicit = "film"
    elif _contains_any(text, ("pid 3", "고강성", "금속", "metal")):
        explicit = "metal"

    if explicit:
        plan.pid_profile_id = explicit
        return

    family = material_family(plan.material_code)
    plan.pid_profile_id = {"metal": "metal", "polymer": "film", "elastomer": "elastomer"}[family]
    if plan.uses_pid:
        plan.notes.append({
            "key": "asst_note_pid_material",
            "args": {"pid": tr(plan.lang, f"asst_pid_{plan.pid_profile_id}", plan.pid_profile_id)},
        })


def _missing_fields(plan: TestCommandPlan) -> List[str]:
    missing: List[str] = []
    if plan.specimen_type is SpecimenType.ROUND:
        if not plan.diameter_mm:
            missing.append("diameter")
    else:
        if not plan.width_mm:
            missing.append("width")
        if not plan.thickness_mm:
            missing.append("thickness")
    if not plan.gauge_length_mm:
        missing.append("gauge_length")
    if plan.mode is TestMode.BENDING and not plan.span_length_mm:
        missing.append("span_length")
    return [key for key in MISSING_FIELD_ORDER if key in missing]


def parse_command(text: str, lang: str = "KO") -> TestCommandPlan:
    """명령 문자열 → 시험 계획 (편의 함수)"""
    return CommandAssistant.parse(text, lang)
