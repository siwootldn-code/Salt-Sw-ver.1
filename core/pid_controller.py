"""
Salt Sw ver.1 - 소프트 PID 하중·응력 속도 제어 (Soft-PID + 강성 피드포워드)

왜 필요한가
- 봉신 P2020 / P2014 는 RS-232 텍스트 프로토콜이고 패킷 주기는 20~50 Hz 수준이다.
  1~5 kHz 폐루프처럼 빠른 보정은 불가능하므로, 통신 지연 20~50 ms 를 감안해
  목표 하중 속도(N/min) · 응력 속도(MPa/s) · 하중 유지를 부드럽게 따라가야 한다.
- 같은 게인으로 플라스틱과 금속을 제어하면 플라스틱은 둔하고 금속은 오버슈트가 난다.
  시편 강성 k(N/mm)가 재질군마다 수십 배에서 수만 배까지 차이나기 때문이다.
  그래서 재질군별 PID 3종(PID 1 연질 / PID 2 중질 / PID 3 고강성)을 따로 저장·불러온다.

제어 구조 (2단)
1) 강성 피드포워드
   하중 속도 R(N/s)을 만들려면 크로스헤드 변위 속도 v = R / k (mm/s)가 필요하다.
   k는 (a) 재질 탄성계수와 시편 제원으로 계산한 초기 추정값, (b) 시험 초반 예비 하중 구간에서
   측정한 ΔF/Δx 로 구한 실측값을 쓴다. 실측값이 나오면 그쪽을 우선한다.
   실시간 속도 변경이 되지 않는 컨트롤러에서는 이 값 하나로 고정 속도를 정해 안전하게 폴백한다.
2) Soft-PID 보정
   피드포워드로 만든 기준 속도에 남은 오차만 보정한다. 게인은 '추정 강성으로 환산한 변위 오차(mm)'
   기준으로 정의해 기종·시편 크기가 달라도 같은 프리셋을 쓸 수 있게 했다.
   - Anti-Windup: 적분 기여분과 출력에 한계를 둔다.
   - Slew rate limit: 속도 명령 변화율을 제한해 기계 충격과 진동을 막는다.
   - Damping zone: 목표에 가까워지면 게인을 낮춰 오버슈트를 줄인다 (금속 프리셋에서 강하게).

정직한 한계
- 판정 주기는 통신 패킷 주기(20~50 Hz)다. 그보다 빠른 과도 응답은 제어하지 않는다.
- 최소 속도(min_speed_mm_min)보다 느린 속도가 필요한 조건에서는 크로스헤드가 멈추므로
  정밀한 저속 하중 제어가 되지 않는다. 이런 조건은 목표 속도를 올리거나 시편을 바꿔야 한다.
- 강성은 시편이 항복한 뒤 줄어든다. 피드포워드 기준 속도가 어긋나므로 PID 보정이 커지며,
  소성역에서는 추종 오차가 커지는 것이 정상이다.
"""

import json
import math
import os
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ----------------------------------------------------------------------
# 제어 방식
# ----------------------------------------------------------------------
class ControlMode(Enum):
    """크로스헤드 제어 방식"""
    DISP = "DISP"                # 변위 속도 제어 (기존 방식, mm/min)
    LOAD_RATE = "LOAD_RATE"      # 하중 속도 제어 (N/min 또는 N/s)
    STRESS_RATE = "STRESS_RATE"  # 응력 속도 제어 (MPa/s)
    LOAD_HOLD = "LOAD_HOLD"      # 하중 유지 (목표 하중까지 접근 후 유지)

    @property
    def uses_pid(self) -> bool:
        return self is not ControlMode.DISP

    @property
    def is_rate(self) -> bool:
        return self in (ControlMode.LOAD_RATE, ControlMode.STRESS_RATE)

    @classmethod
    def parse(cls, value: Any) -> "ControlMode":
        if isinstance(value, ControlMode):
            return value
        text = str(value or "").strip().upper()
        for member in cls:
            if member.value == text or member.name == text:
                return member
        return cls.DISP


class ControlPhase:
    """제어 단계 (램프 / 유지 / 종료)"""
    RAMP = "RAMP"
    HOLD = "HOLD"
    FINISHED = "FINISHED"


# ----------------------------------------------------------------------
# 재질별 PID 프리셋
# ----------------------------------------------------------------------
@dataclass
class PIDProfile:
    """
    재질군별 PID 게인 묶음.

    kp, ki, kd 는 '강성으로 환산한 변위 오차(mm)' 기준 게인이다.
      보정 속도(mm/s) = kp·e_mm + ki·∫e_mm dt + kd·d(e_mm)/dt
    이렇게 두면 시편 크기나 기종이 달라도 같은 프리셋을 그대로 쓸 수 있다.
    """
    id: str
    name_ko: str
    name_en: str
    kp: float
    ki: float
    kd: float
    damping_zone_ratio: float = 0.03   # 목표 근접 판정 비율 (목표 하중 대비)
    max_speed_mm_min: float = 100.0    # 이 모드에서 허용하는 최대 속도
    min_speed_mm_min: float = 0.01     # 이 모드에서 실제로 낼 수 있는 최소 속도
    anti_windup_limit: float = 0.30    # 적분 기여분 한계 (최대 속도 대비 비율)

    # ------------------------------------------------------------------
    def copy(self) -> "PIDProfile":
        return replace(self)

    def name(self, lang: str = "KO") -> str:
        return self.name_en if str(lang).upper() == "EN" else self.name_ko

    def label(self, lang: str = "KO") -> str:
        """선택 목록에 쓰는 표기 (예: 'PID 3: 고강성 (금속)')"""
        return self.name(lang)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any], fallback: Optional["PIDProfile"] = None) -> "PIDProfile":
        base = fallback or DEFAULT_PROFILES["metal"]
        if not isinstance(raw, dict):
            return base.copy()
        return cls(
            id=str(raw.get("id") or base.id),
            name_ko=str(raw.get("name_ko") or base.name_ko),
            name_en=str(raw.get("name_en") or base.name_en),
            kp=_f(raw.get("kp"), base.kp),
            ki=_f(raw.get("ki"), base.ki),
            kd=_f(raw.get("kd"), base.kd),
            damping_zone_ratio=max(0.0, _f(raw.get("damping_zone_ratio"), base.damping_zone_ratio)),
            max_speed_mm_min=max(1e-4, _f(raw.get("max_speed_mm_min"), base.max_speed_mm_min)),
            min_speed_mm_min=max(0.0, _f(raw.get("min_speed_mm_min"), base.min_speed_mm_min)),
            anti_windup_limit=max(0.0, _f(raw.get("anti_windup_limit"), base.anti_windup_limit)),
        )

    def clamp_speed(self, speed_mm_min: float) -> float:
        """프로필 속도 한계 적용 (최소 속도보다 느린 명령은 정지로 처리)"""
        speed = max(-self.max_speed_mm_min, min(self.max_speed_mm_min, speed_mm_min))
        if speed != 0.0 and abs(speed) < self.min_speed_mm_min:
            return 0.0
        return speed


def _default_profiles() -> Dict[str, PIDProfile]:
    return {
        "elastomer": PIDProfile(
            id="elastomer",
            name_ko="PID 1: 연질 (플라스틱·고무·스프링)",
            name_en="PID 1: Soft (plastic, rubber, spring)",
            kp=1.60, ki=2.00, kd=0.03,
            damping_zone_ratio=0.08,
            max_speed_mm_min=500.0, min_speed_mm_min=0.05,
            anti_windup_limit=0.50,
        ),
        "film": PIDProfile(
            id="film",
            name_ko="PID 2: 중질 (필름·복합재)",
            name_en="PID 2: Medium (film, composite)",
            kp=1.40, ki=1.80, kd=0.06,
            damping_zone_ratio=0.05,
            max_speed_mm_min=200.0, min_speed_mm_min=0.02,
            anti_windup_limit=0.40,
        ),
        "metal": PIDProfile(
            id="metal",
            name_ko="PID 3: 고강성 (금속)",
            name_en="PID 3: High stiffness (metal)",
            kp=1.40, ki=1.40, kd=0.06,
            damping_zone_ratio=0.02,
            max_speed_mm_min=5.0, min_speed_mm_min=0.001,
            anti_windup_limit=0.15,
        ),
    }


DEFAULT_PROFILES: Dict[str, PIDProfile] = _default_profiles()
PROFILE_ORDER = ("elastomer", "film", "metal")
DEFAULT_PROFILE_ID = "metal"


class PIDProfileManager:
    """
    PID 게인 프로필 저장/불러오기 (pid_profiles.json).

    - 파일이 없거나 손상되어도 기본 프리셋으로 동작한다.
    - 프리셋 3종은 항상 유지하고, 게인 값만 덮어쓴다.
    - 저장 위치는 프로젝트 폴더(실행 파일 옆)이며 .gitignore 대상이다.
    """

    FILE_VERSION = 1

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, "pid_profiles.json")
        self.config_path = config_path
        self.profiles: Dict[str, PIDProfile] = {pid: p.copy() for pid, p in DEFAULT_PROFILES.items()}
        self.load()

    # ------------------------------------------------------------------
    def load(self) -> Dict[str, PIDProfile]:
        """파일 로드 (없거나 손상되면 기본값 유지)"""
        self.profiles = {pid: p.copy() for pid, p in DEFAULT_PROFILES.items()}
        if not os.path.exists(self.config_path):
            return self.profiles
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as exc:  # 손상 파일은 기본값으로 대체
            print(f"[PIDProfileManager] PID 프로필 로드 실패 (기본값 사용): {exc}")
            return self.profiles
        if not isinstance(raw, dict):
            return self.profiles
        section = raw.get("profiles")
        if not isinstance(section, dict):
            return self.profiles
        for pid, base in DEFAULT_PROFILES.items():
            saved = section.get(pid)
            if isinstance(saved, dict):
                merged = base.to_dict()
                merged.update({k: v for k, v in saved.items() if k in merged})
                merged["id"] = pid
                self.profiles[pid] = PIDProfile.from_dict(merged, base)
        return self.profiles

    def save(self) -> bool:
        """현재 프로필을 JSON으로 저장"""
        payload = {
            "version": self.FILE_VERSION,
            "profiles": {pid: p.to_dict() for pid, p in self.profiles.items()},
        }
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=4, ensure_ascii=False)
            return True
        except Exception as exc:
            print(f"[PIDProfileManager] PID 프로필 저장 실패: {exc}")
            return False

    # ------------------------------------------------------------------
    def get(self, profile_id: str) -> PIDProfile:
        """프로필 조회 (없으면 기본 프리셋)"""
        if profile_id in self.profiles:
            return self.profiles[profile_id]
        return DEFAULT_PROFILES.get(DEFAULT_PROFILE_ID, PIDProfile(
            id="metal", name_ko="PID 3: 고강성 (금속)", name_en="PID 3: High stiffness (metal)",
            kp=1.40, ki=1.40, kd=0.06,
        )).copy()

    def list(self) -> List[PIDProfile]:
        """프리셋 순서대로 목록 반환"""
        out = [self.profiles[pid] for pid in PROFILE_ORDER if pid in self.profiles]
        extra = [p for pid, p in self.profiles.items() if pid not in PROFILE_ORDER]
        return out + extra

    def update(self, profile_id: str, **gains: float) -> PIDProfile:
        """게인 수정 후 저장 (kp, ki, kd, damping_zone_ratio, ...)"""
        profile = self.get(profile_id).copy()
        for key, value in gains.items():
            if hasattr(profile, key) and key not in ("id", "name_ko", "name_en"):
                setattr(profile, key, float(value))
        profile.max_speed_mm_min = max(1e-4, profile.max_speed_mm_min)
        profile.min_speed_mm_min = max(0.0, profile.min_speed_mm_min)
        profile.anti_windup_limit = max(0.0, profile.anti_windup_limit)
        profile.damping_zone_ratio = max(0.0, profile.damping_zone_ratio)
        self.profiles[profile_id] = profile
        self.save()
        return profile

    def reset_defaults(self, save: bool = True) -> Dict[str, PIDProfile]:
        """기본 프리셋으로 복원"""
        self.profiles = {pid: p.copy() for pid, p in DEFAULT_PROFILES.items()}
        if save:
            self.save()
        return self.profiles

    def is_default(self, profile_id: str) -> bool:
        """해당 프로필이 기본값과 같은지"""
        base = DEFAULT_PROFILES.get(profile_id)
        current = self.profiles.get(profile_id)
        if base is None or current is None:
            return False
        return current.to_dict() == base.to_dict()


# ----------------------------------------------------------------------
# 강성 피드포워드
# ----------------------------------------------------------------------
# 재질 표기에서 찾는 대표 탄성계수 (MPa). 시편 제원으로 초기 강성을 어림한다.
MATERIAL_MODULUS_MPA: Dict[str, float] = {
    "SS400": 205000.0, "SS275": 205000.0, "SS330": 205000.0, "SM490": 205000.0,
    "S45C": 207000.0, "SUS304": 193000.0, "SUS316": 193000.0, "AL6061": 69000.0,
    "AL5052": 69000.0, "CU": 118000.0, "BRASS": 100000.0, "TI": 110000.0,
    "NYLON": 2800.0, "PA66": 3000.0, "POM": 3100.0, "PC": 2400.0, "ABS": 2200.0,
    "PP": 1500.0, "PE": 900.0, "PET": 3000.0, "PI": 3500.0, "CFRP": 70000.0,
    "GFRP": 25000.0, "NBR": 5.0, "EPDM": 4.0, "SILICONE": 3.0, "NR": 4.0,
    "RUBBER": 5.0, "고무": 5.0,
}


def material_modulus_mpa(material_text: str) -> float:
    """재질 문자열에서 대표 탄성계수를 찾는다 (없으면 금속 기본값 205 GPa)

    긴 표기를 먼저 본다 (예: 'PET' 를 'PE' 로 잘못 읽지 않도록).
    """
    text = (material_text or "").upper().replace(" ", "")
    for key in sorted(MATERIAL_MODULUS_MPA, key=len, reverse=True):
        if key in text:
            return MATERIAL_MODULUS_MPA[key]
    return 205000.0


def estimate_stiffness(e_mpa: float, area_mm2: float, gauge_mm: float) -> float:
    """탄성계수와 시편 제원으로 초기 강성 k(N/mm)를 어림한다: k = E·A / L0"""
    if e_mpa <= 0 or area_mm2 <= 0 or gauge_mm <= 0:
        return 0.0
    return e_mpa * area_mm2 / gauge_mm


class StiffnessFeedForward:
    """
    시편 강성 k(N/mm) 추정기.

    - 예비 하중 구간의 (변위, 하중) 표본으로 원점 통과 최소자승 기울기를 구한다.
    - 하중 변화가 충분히 커야 추정값을 인정한다 (노이즈·유격 방지).
    - 초기 추정값(재질 탄성계수 기반)이 있으면 실측값이 나올 때까지 그 값을 쓴다.
    """

    WINDOW = 60          # 기울기 계산에 쓰는 최근 표본 수
    MIN_LOAD_SPAN_N = 2.0  # 추정을 인정하는 최소 하중 폭 (N)
    MIN_DISP_SPAN_MM = 2e-5
    MIN_STIFFNESS = 1e-3
    MAX_STIFFNESS = 5e7

    def __init__(self, prior_n_per_mm: float = 0.0, window: int = WINDOW,
                 min_load_span_n: float = MIN_LOAD_SPAN_N):
        self.prior = max(0.0, float(prior_n_per_mm or 0.0))
        self.window = max(4, int(window))
        self.min_load_span_n = max(0.0, float(min_load_span_n))
        self._samples: List[Tuple[float, float]] = []
        self._estimate: float = 0.0
        self._source = "prior" if self.prior > 0 else "none"

    # ------------------------------------------------------------------
    def reset(self):
        self._samples.clear()
        self._estimate = 0.0
        self._source = "prior" if self.prior > 0 else "none"

    def set_prior(self, prior_n_per_mm: float):
        self.prior = max(0.0, float(prior_n_per_mm or 0.0))
        if self._estimate <= 0:
            self._source = "prior" if self.prior > 0 else "none"

    @property
    def stiffness(self) -> float:
        """현재 사용할 강성 (실측 → 초기 추정 → 0)"""
        if self._estimate > 0:
            return self._estimate
        return self.prior

    @property
    def source(self) -> str:
        """'measure' | 'prior' | 'none'"""
        if self._estimate > 0:
            return "measure"
        return "prior" if self.prior > 0 else "none"

    @property
    def is_measured(self) -> bool:
        return self._estimate > 0

    def speed_mm_min_for(self, rate_n_s: float) -> float:
        """목표 하중 속도(N/s)에 대응하는 기준 변위 속도(mm/min)"""
        k = self.stiffness
        if k <= 0:
            return 0.0
        return abs(rate_n_s) / k * 60.0

    # ------------------------------------------------------------------
    def update(self, load_n: float, disp_mm: float) -> float:
        """표본 추가 후 현재 강성 추정값 반환"""
        self._samples.append((float(disp_mm), float(load_n)))
        if len(self._samples) > self.window:
            self._samples.pop(0)
        estimate = self._least_squares_slope()
        if estimate > 0:
            if self._estimate <= 0:
                self._estimate = estimate
            else:
                # 급격한 변화(항복 등)는 천천히 반영한다
                self._estimate = 0.8 * self._estimate + 0.2 * estimate
        return self.stiffness

    def _least_squares_slope(self) -> float:
        if len(self._samples) < 4:
            return 0.0
        x0, y0 = self._samples[0]
        disp_span = max(s[0] for s in self._samples) - min(s[0] for s in self._samples)
        load_span = max(s[1] for s in self._samples) - min(s[1] for s in self._samples)
        if disp_span < self.MIN_DISP_SPAN_MM or load_span < self.min_load_span_n:
            return 0.0
        sxx = sxy = 0.0
        for x, y in self._samples:
            dx = x - x0
            dy = y - y0
            sxx += dx * dx
            sxy += dx * dy
        if sxx <= 0:
            return 0.0
        k = sxy / sxx
        if not (self.MIN_STIFFNESS <= k <= self.MAX_STIFFNESS):
            return 0.0
        return k


# ----------------------------------------------------------------------
# Soft-PID 컨트롤러
# ----------------------------------------------------------------------
@dataclass
class ControllerStatus:
    """제어 상태 스냅샷 (화면 표시·기록용)"""
    mode: str = ControlMode.DISP.value
    phase: str = ControlPhase.RAMP
    setpoint_load_n: float = 0.0
    measured_load_n: float = 0.0
    error_n: float = 0.0
    error_pct: float = 0.0
    speed_mm_min: float = 0.0
    feedforward_mm_min: float = 0.0
    correction_mm_min: float = 0.0
    stiffness_n_per_mm: float = 0.0
    stiffness_source: str = "none"
    elapsed_s: float = 0.0
    hold_elapsed_s: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SoftPIDController:
    """
    하중 속도 · 응력 속도 · 하중 유지용 소프트 PID 컨트롤러.

    update(dt, load_n, disp_mm) 를 통신 패킷 주기에 맞춰 호출하면
    다음 구간에 적용할 크로스헤드 속도(mm/min)를 돌려준다.
    """

    DERIVATIVE_FILTER_S = 0.15   # 미분항 저역 통과 시정수
    ACTUATOR_LAG_S = 0.08        # 서보·기계 응답 지연 (제동 거리 계산용)
    MEASUREMENT_FILTER_S = 0.03  # 계측값 저역 통과 시정수 (제어 진동 억제)
    BRAKING_MARGIN = 1.4         # 제동 거리 안전 여유

    def __init__(self, profile: PIDProfile, mode: ControlMode = ControlMode.LOAD_RATE,
                 target_rate_n_s: float = 0.0, target_load_n: float = 0.0,
                 area_mm2: float = 1.0, comm_delay_ms: float = 35.0,
                 control_rate_hz: float = 25.0, stiffness_prior_n_per_mm: float = 0.0,
                 live_speed_control: bool = True, hold_duration_s: float = 0.0):
        self.profile = profile.copy()
        self.mode = ControlMode.parse(mode)
        self.target_rate_n_s = max(0.0, float(target_rate_n_s))
        self.target_load_n = max(0.0, float(target_load_n))
        self.area_mm2 = max(1e-6, float(area_mm2))
        self.comm_delay_ms = max(0.0, float(comm_delay_ms))
        self.control_rate_hz = min(200.0, max(1.0, float(control_rate_hz)))
        self.live_speed_control = bool(live_speed_control)
        self.hold_duration_s = max(0.0, float(hold_duration_s))

        self.ff = StiffnessFeedForward(stiffness_prior_n_per_mm)
        self.reset()

    # ------------------------------------------------------------------
    def reset(self):
        """시험 시작 상태로 초기화"""
        self.ff.reset()
        self.phase = ControlPhase.RAMP
        self.setpoint_load_n = 0.0
        self.measured_load_n = 0.0
        self.error_n = 0.0
        self.speed_mm_min = 0.0
        self.feedforward_mm_min = 0.0
        self.correction_mm_min = 0.0
        self.integral = 0.0                 # ∫e_mm dt (mm·s)
        self._prev_error_mm = 0.0
        self._error_rate = 0.0              # d(e_mm)/dt 저역 통과 값 (mm/s)
        self._load_filtered = 0.0           # 계측값 저역 통과 상태
        self._started = False
        self.elapsed_s = 0.0
        self.hold_elapsed_s = 0.0
        self._saturated = False
        # 속도 변화율 한계 (mm/min per s): 최대 속도까지 약 0.4초에 도달하는 수준
        self.slew_mm_min_per_s = max(0.2, self.profile.max_speed_mm_min / 0.4)

    def set_target_rate(self, rate_n_s: float):
        """시험 중 목표 하중 속도 변경 (N/s)"""
        self.target_rate_n_s = max(0.0, float(rate_n_s))

    def braking_load_n(self, stiffness_n_per_mm: float) -> float:
        """
        현재 속도로 정지하는 동안 더해지는 하중 (N).
        목표에 이 값보다 가까워지면 기준 속도를 줄여 오버슈트를 막는다.
        """
        k = stiffness_n_per_mm
        if k <= 0:
            return 0.0
        speed_mm_s = abs(self.speed_mm_min) / 60.0
        decel_s = abs(self.speed_mm_min) / max(1e-6, self.slew_mm_min_per_s)
        travel_mm = 0.5 * speed_mm_s * decel_s + speed_mm_s * self.ACTUATOR_LAG_S
        return k * travel_mm * self.BRAKING_MARGIN

    @property
    def stiffness_n_per_mm(self) -> float:
        return self.ff.stiffness

    @property
    def is_finished(self) -> bool:
        return self.phase == ControlPhase.FINISHED

    @property
    def feedforward_speed_mm_min(self) -> float:
        """초기 강성으로 환산한 기준 변위 속도 (실시간 제어 미지원 시 고정 속도)"""
        if self.phase == ControlPhase.HOLD:
            return 0.0
        return self.ff.speed_mm_min_for(self.target_rate_n_s)

    # ------------------------------------------------------------------
    def update(self, dt: float, load_n: float, disp_mm: float,
               disp_valid: bool = True) -> float:
        """
        제어 1주기 계산. 반환값은 다음 주기에 적용할 속도(mm/min).

        disp_valid=False 는 변위 채널이 없는 단일 하중 스트림일 때다.
        이때는 강성 실측을 하지 않고 초기 추정값(재질·제원)만 사용한다.
        """
        if self.phase == ControlPhase.FINISHED:
            self.speed_mm_min = 0.0
            return 0.0

        dt = min(max(float(dt), 1e-4), 0.5)
        self.elapsed_s += dt
        # 계측 잡음으로 속도 명령이 떨지 않도록 저역 통과한 값을 쓴다
        if not self._started or self.MEASUREMENT_FILTER_S <= 0:
            self._load_filtered = float(load_n)
        else:
            alpha_meas = min(1.0, dt / self.MEASUREMENT_FILTER_S)
            self._load_filtered += (float(load_n) - self._load_filtered) * alpha_meas
        load_n = self._load_filtered
        self.measured_load_n = float(load_n)
        if self.phase == ControlPhase.HOLD:
            self.hold_elapsed_s += dt

        # 1) 강성 추정 (피드포워드 기준)
        if disp_valid:
            self.ff.update(load_n, disp_mm)
        k = self.ff.stiffness

        # 2) 목표 하중 곡선 (램프 → 유지)
        rate = 0.0 if self.phase == ControlPhase.HOLD else self.target_rate_n_s
        if self.phase == ControlPhase.HOLD:
            self.setpoint_load_n = self.target_load_n
        else:
            rate_cmd = rate
            if self.target_load_n > 0:
                # 통신 지연만큼 하중이 더 올라가므로 그만큼 앞서 판단한다
                load_ahead = load_n + self.target_rate_n_s * (self.comm_delay_ms / 1000.0)
                remaining = min(self.target_load_n - self.setpoint_load_n,
                                self.target_load_n - load_ahead)
                tolerance = max(1e-6, self.target_load_n * 0.002)
                if remaining <= tolerance:
                    # 목표 도달: 유지 단계로 전환
                    self.setpoint_load_n = self.target_load_n
                    self.phase = ControlPhase.HOLD
                    self.hold_elapsed_s = 0.0
                    rate_cmd = 0.0
                else:
                    # 목표에 가까우면 제동 거리만큼 미리 감속한다 (오버슈트 억제)
                    brake = self.braking_load_n(k)
                    if brake > 0 and remaining < brake:
                        rate_cmd = rate * max(0.0, remaining / brake)
                    self.setpoint_load_n += rate_cmd * dt
            else:
                self.setpoint_load_n += rate_cmd * dt
            rate = rate_cmd
            if self.phase == ControlPhase.HOLD:
                self.hold_elapsed_s = 0.0

        error_n = self.setpoint_load_n - load_n
        self.error_n = error_n
        e_mm = error_n / k if k > 0 else 0.0

        # 3) 유지 시간 종료 판정
        if self.phase == ControlPhase.HOLD and self.hold_duration_s > 0 \
                and self.hold_elapsed_s >= self.hold_duration_s:
            self.phase = ControlPhase.FINISHED
            self.speed_mm_min = 0.0
            return 0.0

        # 4) 기준 속도 (피드포워드)
        ff_mm_s = 0.0
        if self.phase != ControlPhase.HOLD and k > 0:
            ff_mm_s = rate / k

        # 5) 목표 근접 시 게인 완화 (조기 감속)
        kp, ki, kd = self.profile.kp, self.profile.ki, self.profile.kd
        zone = self.profile.damping_zone_ratio * self.target_load_n
        if zone > 0 and abs(error_n) < zone:
            scale = max(0.25, abs(error_n) / zone)
            kp, ki, kd = kp * scale, ki * scale, kd * scale

        # 6) 미분항 (저역 통과)
        raw_rate = (e_mm - self._prev_error_mm) / dt if self._started else 0.0
        alpha = min(1.0, dt / self.DERIVATIVE_FILTER_S)
        self._error_rate += (raw_rate - self._error_rate) * alpha
        self._prev_error_mm = e_mm

        # 7) 적분항 (Anti-Windup: 기여분 한계)
        i_cap_mm_s = self.profile.anti_windup_limit * (self.profile.max_speed_mm_min / 60.0)
        if ki > 0 and i_cap_mm_s > 0:
            self.integral = max(-i_cap_mm_s / ki, min(i_cap_mm_s / ki, self.integral))
        i_term = ki * self.integral

        correction_mm_s = kp * e_mm + i_term + kd * self._error_rate
        command_mm_s = ff_mm_s + correction_mm_s

        # 8) 포화 판정 후 조건부 적분 (적분 와인드업 방지)
        limit_mm_s = self.profile.max_speed_mm_min / 60.0
        saturated = abs(command_mm_s) > limit_mm_s and (command_mm_s * error_n > 0)
        self._saturated = saturated
        if not saturated:
            self.integral += e_mm * dt
            if ki > 0 and i_cap_mm_s > 0:
                self.integral = max(-i_cap_mm_s / ki, min(i_cap_mm_s / ki, self.integral))

        # 9) 속도 변화율 제한 (기계 충격 방지)
        target_mm_min = command_mm_s * 60.0
        if not self._started:
            self._started = True
            speed = target_mm_min
        else:
            max_step = self.slew_mm_min_per_s * dt
            speed = max(self.speed_mm_min - max_step, min(self.speed_mm_min + max_step, target_mm_min))

        speed = self.profile.clamp_speed(speed)
        self.speed_mm_min = speed
        self.feedforward_mm_min = ff_mm_s * 60.0
        self.correction_mm_min = (speed - self.feedforward_mm_min)
        return speed

    # ------------------------------------------------------------------
    def status(self) -> ControllerStatus:
        error_pct = 0.0
        ref = self.target_load_n if self.target_load_n > 0 else self.setpoint_load_n
        if ref > 0:
            error_pct = abs(self.error_n) / ref * 100.0
        return ControllerStatus(
            mode=self.mode.value,
            phase=self.phase,
            setpoint_load_n=round(self.setpoint_load_n, 2),
            measured_load_n=round(self.measured_load_n, 2),
            error_n=round(self.error_n, 2),
            error_pct=round(error_pct, 2),
            speed_mm_min=round(self.speed_mm_min, 3),
            feedforward_mm_min=round(self.feedforward_mm_min, 3),
            correction_mm_min=round(self.correction_mm_min, 3),
            stiffness_n_per_mm=round(self.stiffness_n_per_mm, 1),
            stiffness_source=self.ff.source,
            elapsed_s=round(self.elapsed_s, 2),
            hold_elapsed_s=round(self.hold_elapsed_s, 2),
        )

    def status_text(self, lang: str = "KO") -> str:
        """화면 하단 표시용 한 줄 요약"""
        from .i18n import tr
        st = self.status()
        source = tr(lang, f"pid_src_{st.stiffness_source}")
        if st.stiffness_n_per_mm > 0:
            stiffness = f"{st.stiffness_n_per_mm:,.0f} N/mm ({source})"
        else:
            stiffness = tr(lang, "pid_src_none")
        if str(lang).upper() == "EN":
            return (f"Stiffness {stiffness} · FF {st.feedforward_mm_min:.3f} mm/min · "
                    f"trim {st.correction_mm_min:+.3f} mm/min · {st.measured_load_n:,.1f} N "
                    f"(target {st.setpoint_load_n:,.1f} N)")
        return (f"강성 {stiffness} · 기준 속도 {st.feedforward_mm_min:.3f} mm/min · "
                f"보정 {st.correction_mm_min:+.3f} mm/min · 현재 {st.measured_load_n:,.1f} N "
                f"(목표 {st.setpoint_load_n:,.1f} N)")


def build_controller(config: Any, specimen: Any,
                     profile_manager: Optional[PIDProfileManager] = None,
                     profile: Optional[PIDProfile] = None) -> Optional[SoftPIDController]:
    """
    TestConfig 로부터 컨트롤러를 만든다 (제어 방식이 변위 제어면 None).

    - 하중 속도: config.target_rate (N/min) → N/s
    - 응력 속도: config.target_rate (MPa/s) × 단면적 → N/s
    - 하중 유지: 목표 하중 config.target_holding_val, 접근 속도 config.target_rate (N/min)
    """
    mode = ControlMode.parse(getattr(config, "control_mode", ControlMode.DISP.value))
    if not mode.uses_pid:
        return None

    manager = profile_manager or PIDProfileManager()
    chosen = profile or manager.get(getattr(config, "pid_profile_id", DEFAULT_PROFILE_ID))
    if profile is None and getattr(config, "pid_gains", None):
        chosen = chosen.copy()
        for key, value in dict(config.pid_gains).items():
            if hasattr(chosen, key):
                try:
                    setattr(chosen, key, float(value))
                except (TypeError, ValueError):
                    pass

    area = specimen.cross_sectional_area_mm2
    gauge = max(0.1, specimen.gauge_length_mm)
    prior = estimate_stiffness(material_modulus_mpa(getattr(specimen, "material", "")), area, gauge)

    target_rate_n_s = 0.0
    target_load = 0.0
    if mode is ControlMode.LOAD_RATE:
        target_rate_n_s = max(0.0, float(getattr(config, "target_rate", 0.0))) / 60.0
    elif mode is ControlMode.STRESS_RATE:
        target_rate_n_s = max(0.0, float(getattr(config, "target_rate", 0.0))) * area
    elif mode is ControlMode.LOAD_HOLD:
        target_rate_n_s = max(0.0, float(getattr(config, "target_rate", 0.0))) / 60.0
        target_load = max(0.0, float(getattr(config, "target_holding_val", 0.0)))
        if target_load <= 0:
            target_load = max(0.0, float(getattr(config, "target_load_n", 0.0)))

    return SoftPIDController(
        profile=chosen,
        mode=mode,
        target_rate_n_s=target_rate_n_s,
        target_load_n=target_load,
        area_mm2=area,
        comm_delay_ms=float(getattr(config, "comm_delay_ms", 35.0)),
        control_rate_hz=float(getattr(config, "control_rate_hz", 25.0)),
        stiffness_prior_n_per_mm=prior,
        live_speed_control=bool(getattr(config, "live_speed_control", True)),
        hold_duration_s=float(getattr(config, "holding_duration_s", 0.0)) if mode is ControlMode.LOAD_HOLD else 0.0,
    )


# ----------------------------------------------------------------------
# 추종 성능 평가 (시험 후 리포트·검증용)
# ----------------------------------------------------------------------
@dataclass
class TrackingSample:
    """제어 1주기 기록"""
    time_s: float
    setpoint_n: float
    load_n: float
    speed_mm_min: float = 0.0
    stiffness_n_per_mm: float = 0.0


def evaluate_tracking(samples: List[TrackingSample], target_rate_n_s: float = 0.0,
                      target_load_n: float = 0.0, settle_band: float = 0.02,
                      rate_settle_s: float = 0.5, rate_window_s: float = 0.2) -> Dict[str, float]:
    """
    추종 성능 계산.

    - rate_error_pct: 램프 구간 하중 속도의 표준편차 수준 상대 오차(%) (RMS)
    - follow_error_pct: 램프 구간 목표 대비 추종 오차 RMS(%)
    - overshoot_pct: 목표 하중 대비 최대 초과분(%)
    - settle_s: 목표 도달 후 ±settle_band 안에 머문 시점(초)
    - hold_error_pct: 유지 구간 평균 오차(%)
    """
    out = {"rate_error_pct": 0.0, "follow_error_pct": 0.0, "overshoot_pct": 0.0,
           "settle_s": 0.0, "hold_error_pct": 0.0, "peak_load_n": 0.0, "max_error_n": 0.0}
    if not samples:
        return out

    out["peak_load_n"] = max(s.load_n for s in samples)
    out["max_error_n"] = max(abs(s.load_n - s.setpoint_n) for s in samples)

    # 램프 구간: 설정 하중이 목표의 90%에 닿기 전까지
    ramp_samples = [s for s in samples if s.setpoint_n > 0]
    if target_load_n > 0:
        ramp_end_limit = target_load_n * 0.98
        ramp_samples = [s for s in ramp_samples if s.setpoint_n < ramp_end_limit]
    # 초기 과도 구간(가속)은 제외한다
    if ramp_samples:
        t0 = ramp_samples[0].time_s
        ramp_samples = [s for s in ramp_samples if s.time_s - t0 >= rate_settle_s]
    if len(ramp_samples) >= 3 and target_rate_n_s > 0:
        # 하중 속도는 짧은 구간 미분 대신 0.2초 창 기울기로 본다 (계측 잡음 영향 제거)
        rates, errs = [], []
        j = 0
        for i in range(len(ramp_samples)):
            while j < len(ramp_samples) and ramp_samples[j].time_s - ramp_samples[i].time_s < rate_window_s:
                j += 1
            if j >= len(ramp_samples):
                break
            dt = ramp_samples[j].time_s - ramp_samples[i].time_s
            if dt <= 0:
                continue
            # 일정 속도(정상 램프) 구간만 본다. 제동 감속 구간은 오버슈트 항목에서 평가한다.
            sp_rate = (ramp_samples[j].setpoint_n - ramp_samples[i].setpoint_n) / dt
            if sp_rate < target_rate_n_s * 0.9:
                continue
            rates.append((ramp_samples[j].load_n - ramp_samples[i].load_n) / dt - sp_rate)
        for s in ramp_samples:
            if s.setpoint_n > 0:
                errs.append((s.load_n - s.setpoint_n) / s.setpoint_n * 100.0)
        if rates:
            out["rate_error_pct"] = math.sqrt(sum(r * r for r in rates) / len(rates)) / target_rate_n_s * 100.0
        if errs:
            out["follow_error_pct"] = math.sqrt(sum(e * e for e in errs) / len(errs))

    if target_load_n > 0:
        out["overshoot_pct"] = max(0.0, (out["peak_load_n"] - target_load_n) / target_load_n * 100.0)
        # 유지 구간: 설정이 목표에 도달한 이후
        hold_samples = [s for s in samples if s.setpoint_n >= target_load_n * 0.999]
        if len(hold_samples) > 2:
            tail = hold_samples[max(0, int(len(hold_samples) * 0.5)):]
            out["hold_error_pct"] = sum(abs(s.load_n - target_load_n) / target_load_n * 100.0
                                        for s in tail) / len(tail)
            # 정착 시간: 목표 도달 이후 마지막으로 밴드를 벗어난 시점
            start_t = hold_samples[0].time_s
            last_outside = None
            for s in hold_samples:
                if abs(s.load_n - target_load_n) > target_load_n * settle_band:
                    last_outside = s
            out["settle_s"] = 0.0 if last_outside is None else last_outside.time_s - start_t
    return {k: round(v, 4) for k, v in out.items()}


def _f(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result or result in (float("inf"), float("-inf")):
        return default
    return result
