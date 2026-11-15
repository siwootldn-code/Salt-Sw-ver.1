"""
Salt Sw ver.1 - Data Models
시편 규격, 시험 조건, 실시간 계측 데이터 및 분석 결과 모델
"""

from dataclasses import dataclass, field, replace
from enum import Enum
import math
from typing import List, Optional


class ExtensometerType(Enum):
    """신율계(변위계) 신호 방식"""
    MV = "MV"        # 아날로그 mV/V (스트레인게이지 방식)
    PULSE = "PULSE"  # 엔코더 펄스 (디지털 카운트 방식)


@dataclass
class ExtensometerSettings:
    """
    신율계(Extensometer) 설정
    - mV 타입: 정격 출력(mV/V) x 여자전압(V) = 정격 신호량, 이를 정격 변위(mm)로 환산
    - 펄스 타입: 펄스 1개당 이동량(mm/pulse)으로 환산
    - 표점거리(GL)는 변형률 환산 기준 길이
    """
    enabled: bool = False                       # 신율계 사용 여부
    ext_type: str = ExtensometerType.MV.value   # "MV" | "PULSE"
    gauge_length_mm: float = 50.0               # 표점거리 GL (mm)

    # mV 타입 파라미터
    rated_output_mv_v: float = 2.0              # 정격 출력 (mV/V)
    full_scale_mm: float = 25.0                 # 정격 변위 (mm)
    excitation_v: float = 5.0                   # 여자 전압 (V)
    calib_factor: float = 1.0                   # 교정 계수 (실측 보정)
    zero_offset_mv: float = 0.0                 # 영점 오프셋 (mV)

    # 펄스 타입 파라미터
    resolution_mm_per_pulse: float = 0.001      # 분해능 (mm/pulse)
    direction_invert: bool = False              # 방향 반전
    zero_offset_pulse: float = 0.0              # 영점 오프셋 (pulse count)

    # ------------------------------------------------------------------
    @property
    def is_mv(self) -> bool:
        return self.ext_type == ExtensometerType.MV.value

    @property
    def is_pulse(self) -> bool:
        return self.ext_type == ExtensometerType.PULSE.value

    @property
    def full_scale_signal_mv(self) -> float:
        """정격 신호량 (mV) = 정격 출력(mV/V) x 여자전압(V)"""
        return max(0.0001, self.rated_output_mv_v * self.excitation_v)

    # ------------------------------------------------------------------
    # mV 타입 환산
    def mv_to_mm(self, mv: float) -> float:
        """아날로그 mV 신호 -> 변위(mm)"""
        ratio = (mv - self.zero_offset_mv) / self.full_scale_signal_mv
        return ratio * self.full_scale_mm * self.calib_factor

    def mm_to_mv(self, mm: float) -> float:
        """변위(mm) -> 아날로그 mV 신호 (시뮬레이터 및 역산용)"""
        ratio = mm / max(0.0001, self.full_scale_mm * self.calib_factor)
        return ratio * self.full_scale_signal_mv + self.zero_offset_mv

    # ------------------------------------------------------------------
    # 펄스 타입 환산
    def pulses_to_mm(self, pulses: float) -> float:
        """엔코더 펄스 카운트 -> 변위(mm)"""
        delta = pulses - self.zero_offset_pulse
        mm = delta * self.resolution_mm_per_pulse
        return -mm if self.direction_invert else mm

    def mm_to_pulses(self, mm: float) -> float:
        """변위(mm) -> 엔코더 펄스 카운트 (시뮬레이터 및 역산용)"""
        signed = -mm if self.direction_invert else mm
        return signed / max(0.000001, self.resolution_mm_per_pulse) + self.zero_offset_pulse

    # ------------------------------------------------------------------
    def to_displacement(self, raw_value: float) -> float:
        """현재 타입에 맞춰 원시 신호를 변위(mm)로 환산"""
        return self.mv_to_mm(raw_value) if self.is_mv else self.pulses_to_mm(raw_value)

    def to_raw(self, mm: float) -> float:
        """변위(mm)를 현재 타입의 원시 신호로 환산"""
        return self.mm_to_mv(mm) if self.is_mv else self.mm_to_pulses(mm)

    def to_strain_pct(self, mm: float) -> float:
        """변위(mm) -> 변형률(%)"""
        return (mm / max(0.0001, self.gauge_length_mm)) * 100.0

    def copy(self) -> "ExtensometerSettings":
        return replace(self)


class SpecimenType(Enum):
    """시편 형태"""
    FLAT = "판재 (Flat)"
    ROUND = "봉재 (Round)"
    TUBE = "관형 (Tube)"


class TestMode(Enum):
    """시험 종류"""
    TENSILE = "인장 시험 (Tensile)"
    COMPRESSION = "압축 시험 (Compression)"
    BENDING = "굽힘 시험 (Bending)"
    HOLDING = "유지 시험 (Holding)"


class BendingType(Enum):
    """굽힘 시험 방식"""
    THREE_POINT = "3점 굽힘 (3-Point Bending)"
    FOUR_POINT = "4점 굽힘 (4-Point Bending)"


class HoldingType(Enum):
    """유지 시험 방식"""
    LOAD_HOLD = "하중 유지 (Load Hold / Creep)"
    DISP_HOLD = "변위 유지 (Disp Hold / Relaxation)"


@dataclass
class Specimen:
    """시편 제원 정보"""
    specimen_id: str = "SPECIMEN-001"
    material: str = "SS400 (일반구조용 강재)"
    specimen_type: SpecimenType = SpecimenType.FLAT
    width_mm: float = 12.5       # 판재 폭
    thickness_mm: float = 3.0    # 판재 두께
    diameter_mm: float = 10.0    # 봉재 직경
    gauge_length_mm: float = 50.0  # 표점거리 (L0)

    @property
    def cross_sectional_area_mm2(self) -> float:
        """초기 단면적 (A0, mm²) 계산"""
        if self.specimen_type == SpecimenType.FLAT:
            return max(0.001, self.width_mm * self.thickness_mm)
        elif self.specimen_type == SpecimenType.ROUND:
            return max(0.001, math.pi * ((self.diameter_mm / 2.0) ** 2))
        else:
            return max(0.001, self.width_mm * self.thickness_mm)


@dataclass
class TestConfig:
    """시험 제어 파라미터"""
    mode: TestMode = TestMode.TENSILE
    test_speed_mm_min: float = 5.0          # 시험 속도 (mm/min)
    fracture_drop_ratio: float = 0.5        # 피크 하중 대비 파단 감지 하중 드롭 비율 (50%)
    max_displacement_mm: float = 50.0       # 최대 안전 변위 한계 (mm)
    sampling_rate_hz: int = 20              # 데이터 샘플링 주기 (Hz)

    # 굽힘 시험 전용 파라미터 (KS B 0804 / ASTM D790)
    bending_type: BendingType = BendingType.THREE_POINT
    span_length_mm: float = 100.0           # 지간 거리 (L, mm)

    # 유지 시험 전용 파라미터 (ASTM E139 / ASTM E328)
    holding_type: HoldingType = HoldingType.LOAD_HOLD
    target_holding_val: float = 1000.0      # 목표 유지값 (N 또는 mm)
    holding_duration_s: float = 60.0        # 목표 유지 시간 (초)

    # 신율계(Extensometer) 설정 (환경 설정 탭에서 저장/적용)
    ext: ExtensometerSettings = field(default_factory=ExtensometerSettings)

    @property
    def use_extensometer(self) -> bool:
        return bool(self.ext and self.ext.enabled)


@dataclass
class DataPoint:
    """단일 계측 시점의 데이터"""
    time_s: float
    displacement_mm: float          # 크로스헤드 변위 (mm)
    load_n: float
    stress_mpa: float = 0.0
    strain_pct: float = 0.0         # 분석에 사용하는 변형률 (신율계 사용 시 신율계 기준)

    # 신율계 채널 (사용하지 않을 때는 0 / ext_valid=False)
    ext_disp_mm: float = 0.0        # 신율계 변위 (mm)
    ext_strain_pct: float = 0.0     # 신율계 변형률 (%)
    ext_raw: float = 0.0            # 신율계 원시 신호 (mV 또는 pulse count)
    ext_valid: bool = False         # 해당 시점 신율계 신호 수신 여부

    def compute_mechanics(self, area_mm2: float, gauge_length_mm: float, use_ext: bool = False):
        """하중/변위로부터 공칭 응력(MPa) 및 공칭 변형률(%) 계산"""
        self.stress_mpa = self.load_n / area_mm2
        measurement = self.ext_disp_mm if (use_ext and self.ext_valid) else self.displacement_mm
        self.strain_pct = (measurement / gauge_length_mm) * 100.0


@dataclass
class TestResult:
    """시험 완료 후 최종 분석 결과"""
    test_mode: TestMode
    specimen_id: str
    material: str
    area_mm2: float
    gauge_length_mm: float
    
    peak_load_n: float = 0.0            # 최대 하중 (N)
    peak_stress_mpa: float = 0.0        # 인장강도 / 압축강도 (MPa)
    yield_load_n: float = 0.0           # 항복 하중 (N)
    yield_stress_mpa: float = 0.0       # 항복 강도 (0.2% Offset) (MPa)
    elastic_modulus_gpa: float = 0.0     # 탄성 계수 (Young's Modulus, GPa)
    break_load_n: float = 0.0           # 파단 하중 (N)
    break_displacement_mm: float = 0.0  # 파단 변위 (mm)
    elongation_pct: float = 0.0         # 파단 연신율 / 변형률 (%)
    energy_joule: float = 0.0           # 흡수에너지 (J)
    total_time_s: float = 0.0           # 총 시험 소요 시간 (초)
    total_samples: int = 0              # 수집된 샘플 수
    is_fractured: bool = False          # 파단 발생 여부

    # 굽힘 시험 특화 결과치
    flexural_modulus_gpa: float = 0.0   # 휨 탄성계수 (GPa)
    
    # 유지 시험 특화 결과치
    initial_holding_val: float = 0.0    # 유지 시작 시점 계측값
    final_holding_val: float = 0.0      # 유지 종료 시점 계측값
    creep_deflection_mm: float = 0.0    # 크리프 추가 변위량 (mm)
    load_relaxation_pct: float = 0.0    # 응력/하중 감쇄율 (%)

    # 신율계(Extensometer) 적용 결과
    ext_enabled: bool = False           # 신율계 사용 여부
    ext_type: str = ""                  # "MV" | "PULSE"
    ext_gauge_length_mm: float = 0.0    # 신율계 표점거리 (mm)
    ext_max_disp_mm: float = 0.0        # 신율계 최대 변위 (mm)
    ext_break_disp_mm: float = 0.0      # 파단 시점 신율계 변위 (mm)
    strain_source: str = "Crosshead"    # 변형률 측정 소스 (Crosshead / Extensometer (mV) / Extensometer (Pulse))
