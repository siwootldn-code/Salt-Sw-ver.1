"""
Salt Sw ver.1 - Virtual UTM Hardware Simulator
실제 만능재료시험기 없이도 4대 시험(인장, 압축, 굽힘, 유지) 및 다단계 시퀀스 데이터를 실시간 생성하는 물리 시뮬레이터

신율계(Extensometer) 지원:
- mV 타입(아날로그 mV/V)과 펄스 타입(엔코더 카운트) 원시 신호를 실제 계측기처럼 생성하고,
  드라이버와 동일한 환산식(ExtensometerSettings)으로 변위를 복원해 시험에 적용한다.
- 크로스헤드 변위 = 표점부 변형 + 프레임/그립 탄성 변형(하중 x 기계 유연성)이므로,
  신율계 변위는 크로스헤드 변위보다 작게 나타난다 (교정된 신율계의 실제 특성).

다단계 시퀀스(Sequence):
- SequenceController 가 단계 목표(하중/변위/시간) 도달을 판정하고, 시뮬레이터는 그 지시에 따라
  속도 · 유지(정지) · 복귀를 물리 모델에 반영한다. 실장비와 동일한 컨트롤러를 사용한다.

재질 프로필:
- 재질 문자열에서 규격(SS400, SM490, S45C, SUS304, AL6061 등)을 찾아 표준 물성으로 모사한다.
- 같은 재질의 시편끼리도 실제처럼 약간의 편차(탄성계수 ±1%, 항복 ±1.5%, 인장강도 ±1%,
  파단 변형률 ±2%)를 가진다. 배치 통계(평균/표준편차/변동계수)가 의미를 갖는 이유다.
"""

import math
import random
import threading
import time
from typing import Dict, List, Optional, Tuple

from .hardware_interface import HardwareInterface
from .models import (
    DataPoint, ExtensometerSettings, Specimen, TestConfig, TestMode, BendingType, HoldingType
)
from .pid_controller import (
    ControlMode, ControlPhase, PIDProfileManager, SoftPIDController, TrackingSample,
    build_controller
)
from .sequence import SequenceController, StepAction


# 규격별 표준 물성 (E MPa, 항복 MPa, 인장강도 MPa, 인장강도 변형률, 파단 변형률)
MATERIAL_PROFILES: Dict[str, Dict[str, float]] = {
    "SS400": {"e": 205000.0, "sy": 260.0, "su": 450.0, "eu": 0.16, "ef": 0.24},
    "SS275": {"e": 205000.0, "sy": 300.0, "su": 420.0, "eu": 0.17, "ef": 0.26},
    "SM490": {"e": 205000.0, "sy": 365.0, "su": 510.0, "eu": 0.14, "ef": 0.22},
    "S45C": {"e": 207000.0, "sy": 490.0, "su": 700.0, "eu": 0.09, "ef": 0.15},
    "SUS304": {"e": 193000.0, "sy": 260.0, "su": 620.0, "eu": 0.35, "ef": 0.50},
    "AL6061": {"e": 69000.0, "sy": 240.0, "su": 300.0, "eu": 0.08, "ef": 0.12},
    "SS330": {"e": 205000.0, "sy": 205.0, "su": 330.0, "eu": 0.20, "ef": 0.30},
    # 연질(엘라스토머) · 필름류 — 소프트 PID 시험 대상
    "NBR": {"e": 5.0, "sy": 4.0, "su": 13.0, "eu": 2.4, "ef": 3.6},
    "EPDM": {"e": 4.0, "sy": 3.4, "su": 11.0, "eu": 2.6, "ef": 3.9},
    "SILICONE": {"e": 3.0, "sy": 2.8, "su": 9.0, "eu": 2.8, "ef": 4.2},
    "PET": {"e": 3000.0, "sy": 60.0, "su": 120.0, "eu": 0.08, "ef": 0.12},
    "PE": {"e": 900.0, "sy": 18.0, "su": 30.0, "eu": 0.12, "ef": 0.35},
    "PI": {"e": 3500.0, "sy": 90.0, "su": 150.0, "eu": 0.06, "ef": 0.10},
}
DEFAULT_PROFILE_KEY = "SS400"


def resolve_material_profile(material_text: str) -> Dict[str, float]:
    """재질 문자열에서 규격 프로필을 찾는다 (없으면 SS400)"""
    text = (material_text or "").upper().replace(" ", "")
    # 긴 표기를 먼저 본다 (예: 'PET' 를 'PE' 로 잘못 읽지 않도록)
    for key in sorted(MATERIAL_PROFILES, key=len, reverse=True):
        if key in text:
            return dict(MATERIAL_PROFILES[key])
    return dict(MATERIAL_PROFILES[DEFAULT_PROFILE_KEY])


class VirtualUTMSimulator(HardwareInterface):
    """
    물리 기반 가상 재료시험기 시뮬레이터.
    - 인장: 탄성, 소성 항복, 가공 경화, 네킹 및 파단
    - 압축: 탄성, 소성 항복, 배럴링 소착
    - 굽힘(3점/4점): 보의 휨 강성, 탄성 휨, 소성 힌지 및 파단
    - 유지(크리프/이완): 목표 하중 유지 시 크리프 변위 진행, 목표 변위 유지 시 응력 이완
    - 시퀀스: 단계별 가압/유지/파단/복귀 지휘
    - 신율계: mV / 펄스 원시 신호 생성 및 변위 복원
    """

    # 프레임 + 그립 탄성 변형 (하중 1 N당 크로스헤드 추가 이동량)
    MACHINE_COMPLIANCE_MM_PER_N = 0.000005

    def __init__(self):
        super().__init__()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.specimen: Optional[Specimen] = None
        self.config: Optional[TestConfig] = None
        self.current_displacement: float = 0.0
        self.current_load: float = 0.0

        # 시험 중 실시간 속도 변경 지원 (가상 장비는 항상 지원)
        self.supports_live_speed_control = True
        self._live_speed_mm_min: float = 0.0

        # 소프트 PID 제어 상태 (하중·응력 속도 제어 시 사용)
        self.pid_manager = PIDProfileManager()
        self.controller: Optional[SoftPIDController] = None
        self.control_trace: List[TrackingSample] = []

        # 검증·화면 캡처용 시간 배속 (1.0 = 실시간). 물리 계산은 그대로 두고 시간만 빨리 흘린다.
        self.time_scale: float = 1.0

        # 신율계 상태
        self.ext: ExtensometerSettings = ExtensometerSettings()
        self.current_ext_disp_mm: float = 0.0
        self.current_ext_raw: float = 0.0
        self.current_ext_valid: bool = False

        # 재질 프로필 및 시편 편차
        self.profile: Dict[str, float] = dict(MATERIAL_PROFILES[DEFAULT_PROFILE_KEY])
        self.scatter: Dict[str, float] = {}

    # ------------------------------------------------------------------
    def set_extensometer(self, settings: Optional[ExtensometerSettings]):
        """환경 설정의 신율계 구성 적용"""
        self.ext = settings.copy() if settings else ExtensometerSettings()
        self.current_ext_disp_mm = 0.0
        self.current_ext_raw = 0.0
        self.current_ext_valid = False

    # ------------------------------------------------------------------
    def set_speed(self, speed_mm_min: float):
        """시험 중 속도 변경 - 다음 스텝부터 바로 반영 (변위 속도 제어)"""
        self._live_speed_mm_min = max(0.0, float(speed_mm_min))

    def _effective_speed_mm_s(self) -> float:
        if self._live_speed_mm_min > 0:
            return self._live_speed_mm_min / 60.0
        return (self.config.test_speed_mm_min if self.config else 0.0) / 60.0

    def current_control_status(self, lang: str = "KO") -> str:
        """소프트 PID 제어 상태 (변위 속도 제어 시에는 빈 문자열)"""
        if self.controller is None:
            return ""
        return self.controller.status_text(lang)

    def tare_extensometer(self):
        """현재 신율계 원시값을 영점으로 설정"""
        if self.ext.is_mv:
            self.ext.zero_offset_mv = round(self.current_ext_raw, 5)
        else:
            self.ext.zero_offset_pulse = round(self.current_ext_raw)
        self.current_ext_disp_mm = 0.0

    # ------------------------------------------------------------------
    def connect(self, port: str = "VIRTUAL", baudrate: int = 115200) -> bool:
        self.is_connected = True
        return True

    def disconnect(self):
        self.stop_test()
        self.is_connected = False

    def start_test(self, specimen: Specimen, config: TestConfig):
        """시험 시작: 백그라운드 스레드에서 실시간 데이터 생성"""
        if not self.is_connected:
            self.connect()

        self.specimen = specimen
        self.config = config
        self.set_extensometer(config.ext)
        self._stop_event.clear()
        self.is_running = True
        self.current_displacement = 0.0
        self.current_load = 0.0
        self.step_events = []
        self.sequence_name = ""

        # 재질 프로필 + 시편 간 편차 (배치 시험의 현실적 산포)
        self.profile = resolve_material_profile(specimen.material)
        self.scatter = {
            "e": 1.0 + random.uniform(-0.010, 0.010),
            "sy": 1.0 + random.uniform(-0.015, 0.015),
            "su": 1.0 + random.uniform(-0.010, 0.010),
            "ef": 1.0 + random.uniform(-0.020, 0.020),
        }
        if config.mode == TestMode.SEQUENCE:
            self.sequence_name = config.sequence.name

        # 하중·응력 속도 제어 여부 (굽힘·시퀀스는 변위 속도 제어만 지원)
        self._live_speed_mm_min = 0.0
        use_control = (config.uses_pid_control and
                       config.mode in (TestMode.TENSILE, TestMode.COMPRESSION, TestMode.HOLDING))
        self.controller = build_controller(config, specimen, self.pid_manager) if use_control else None
        self.control_trace = []
        if use_control and self.controller is None:
            use_control = False

        target = self._run_controlled if use_control else self._run_simulation
        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()

    def stop_test(self):
        """시험 정지"""
        if self.is_running:
            self._stop_event.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.0)
            self.is_running = False

    def return_to_origin(self):
        """원점 복귀 (변위 및 하중 0으로 초기화)"""
        self.current_displacement = 0.0
        self.current_load = 0.0
        self.current_ext_disp_mm = 0.0
        self.current_ext_raw = 0.0
        self.current_ext_valid = False

    # ------------------------------------------------------------------
    def _encode_ext(self, gauge_mm: float) -> Tuple[float, float]:
        """
        표점부 변형량(mm) -> 실제 계측기처럼 원시 신호 생성 후, 드라이버 환산식으로 복원.
        반환: (원시 신호, 복원된 변위 mm)
        """
        if not self.ext.enabled:
            return 0.0, 0.0

        if self.ext.is_mv:
            raw = self.ext.mm_to_mv(gauge_mm) + random.gauss(0.0, 0.0004)
            raw = round(raw, 4)
            return raw, self.ext.mv_to_mm(raw)
        else:
            raw = self.ext.mm_to_pulses(gauge_mm) + random.gauss(0.0, 0.30)
            raw = round(raw)
            return float(raw), self.ext.pulses_to_mm(raw)

    # ------------------------------------------------------------------
    def _run_simulation(self):
        """실시간 물리 연산 루프"""
        specimen = self.specimen
        config = self.config
        area = specimen.cross_sectional_area_mm2
        l0 = specimen.gauge_length_mm

        ext_on = bool(self.ext.enabled)
        ext_gl = self.ext.gauge_length_mm if ext_on else l0

        # 재질 프로필 (시편 편차 반영)
        profile = self.profile
        scatter = self.scatter
        e_modulus_mpa = profile["e"] * scatter.get("e", 1.0)
        yield_stress_mpa = profile["sy"] * scatter.get("sy", 1.0)
        yield_strain = yield_stress_mpa / e_modulus_mpa
        uts_stress_mpa = profile["su"] * scatter.get("su", 1.0)
        uts_strain = profile["eu"]
        fracture_strain = profile["ef"] * scatter.get("ef", 1.0)

        interval_s = 1.0 / max(5, config.sampling_rate_hz)

        b = specimen.width_mm
        d = specimen.thickness_mm
        span = config.span_length_mm

        # 신율계 사용 시에만 프레임/그립 탄성 변형을 반영 (미사용 시 강성 프레임으로 단순화)
        compliance = self.MACHINE_COMPLIANCE_MM_PER_N if (ext_on and config.mode != TestMode.BENDING) else 0.0

        def evaluate(gauge_deform: float) -> Tuple[float, float, float]:
            """표점부 변형량 -> (하중 N, 응력 MPa, 공칭 변형률)"""
            if config.mode == TestMode.COMPRESSION:
                strain = gauge_deform / l0
                stress = self._calc_compression_stress(strain, e_modulus_mpa, yield_stress_mpa, yield_strain)
                return max(0.0, stress * area), stress, strain

            if config.mode == TestMode.BENDING:
                strain = (6.0 * d * gauge_deform) / (span ** 2)
                stress = self._calc_tensile_stress(
                    strain, e_modulus_mpa, yield_stress_mpa, yield_strain,
                    uts_stress_mpa, uts_strain, fracture_strain
                )
                # 역산 하중: P = (2 * b * d^2 * stress) / (3 * L)
                return max(0.0, (2.0 * b * (d ** 2) * stress) / (3.0 * span)), stress, strain

            strain = gauge_deform / l0
            stress = self._calc_tensile_stress(
                strain, e_modulus_mpa, yield_stress_mpa, yield_strain,
                uts_stress_mpa, uts_strain, fracture_strain
            )
            return max(0.0, stress * area), stress, strain

        # --- 다단계 시퀀스 상태 ---
        seq_ctl: Optional[SequenceController] = SequenceController(config.sequence) \
            if config.mode == TestMode.SEQUENCE else None
        seq_last_index = -1
        seq_hold_load = 0.0
        seq_hold_deform = 0.0
        seq_prev_action: Optional[StepAction] = None
        seq_return_deform = 0.0
        seq_return_load = 0.0
        fractured = False
        if seq_ctl is not None:
            seq_ctl.start(0.0, 0.0, 0.0)

        start_time = time.time()
        gauge_deform = 0.0     # 표점부 변형량 (시편 실제 변형)
        disp = 0.0             # 크로스헤드 변위
        peak_load = 0.0
        completion_reason = "정상 종료"
        load = 0.0
        stress = 0.0
        strain = 0.0

        # 유지 시험 전용 상태 변수
        holding_phase = "RAMP"  # "RAMP" -> "HOLDING"
        hold_start_time = 0.0
        base_hold_load = 0.0
        base_hold_disp = 0.0

        elapsed_virtual = 0.0
        while not self._stop_event.is_set():
            loop_start = time.time()
            # 가상 시간은 물리 스텝과 정확히 일치시킨다 (시간 배속은 대기 시간만 줄인다)
            elapsed_virtual += interval_s
            elapsed_time = elapsed_virtual
            speed_mm_s = self._effective_speed_mm_s()

            # --- 시퀀스: 단계가 바뀐 시점의 기준값 저장 ---
            if seq_ctl is not None and seq_ctl.current_index != seq_last_index:
                seq_last_index = seq_ctl.current_index
                step = seq_ctl.current_step
                if step is not None:
                    if step.action == StepAction.HOLD:
                        seq_hold_load = load
                        seq_hold_deform = gauge_deform
                    elif step.action == StepAction.RETURN:
                        seq_return_deform = max(1e-6, gauge_deform)
                        seq_return_load = load

            # --- 속도/방향 결정 ---
            if seq_ctl is not None:
                step = seq_ctl.current_step
                if step is None or seq_ctl.is_finished:
                    seq_speed = 0.0
                    direction = 0
                else:
                    seq_speed = step.speed_mm_min / 60.0
                    direction = seq_ctl.direction
            else:
                seq_speed = speed_mm_s
                direction = 1

            # --- 모드별 거동 연산 ---
            if config.mode == TestMode.SEQUENCE and seq_ctl is not None:
                step = seq_ctl.current_step
                action = step.action if step is not None and not seq_ctl.is_finished else None

                if action == StepAction.HOLD:
                    # 유지: 크로스헤드는 정지, 미세 크리프만 진행하고 하중은 완만히 이완
                    gauge_deform += 0.0004 * interval_s
                    event = seq_ctl.events[-1] if seq_ctl.events else None
                    hold_total = max(0.1, step.hold_s if step else 0.1)
                    hold_elapsed = (elapsed_time - event.started_at) if event else 0.0
                    progress = min(1.0, max(0.0, hold_elapsed / hold_total))
                    relax = 0.02 if seq_prev_action == StepAction.RAMP_LOAD else 0.08
                    load = seq_hold_load * (1.0 - relax * progress)
                    load = max(0.0, load * (1.0 + random.gauss(0, 0.0008)))
                    stress = load / area
                    strain = gauge_deform / l0
                elif action == StepAction.RETURN:
                    # 복귀: 선형 탄성 제거로 단순화 (시편이 이미 파단된 경우 하중 0)
                    gauge_deform = max(0.0, gauge_deform - seq_speed * interval_s)
                    if fractured:
                        load = 0.0
                    else:
                        ratio = gauge_deform / max(1e-6, seq_return_deform)
                        load = max(0.0, seq_return_load * ratio)
                    load = max(0.0, load * (1.0 + random.gauss(0, 0.0008)))
                    stress = load / area
                    strain = gauge_deform / l0
                elif seq_ctl.is_finished:
                    load = 0.0
                    stress = 0.0
                    strain = gauge_deform / l0
                else:
                    gauge_deform += seq_speed * interval_s
                    load, stress, strain = evaluate(gauge_deform)
                    load = max(0.0, load * (1.0 + random.gauss(0, 0.003)))
                    if not fractured and strain >= uts_strain and peak_load > 50:
                        drop_ratio = (peak_load - load) / peak_load
                        if drop_ratio >= config.fracture_drop_ratio or strain >= fracture_strain:
                            fractured = True

                if load > peak_load:
                    peak_load = load
                disp = gauge_deform + compliance * load

                # 단계 전환 판정
                for transition in seq_ctl.update(elapsed_time, load, disp, fractured=fractured):
                    if transition.event is not None:
                        seq_prev_action = StepAction(transition.event.action)
                        if seq_prev_action == StepAction.HOLD:
                            seq_hold_load = transition.event.end_load_n
                if seq_ctl.is_finished:
                    completion_reason = "시퀀스 완료 · 파단 감지" if fractured else "시퀀스 완료 · 정상 종료"
                    if seq_ctl.events:
                        seq_ctl.events[-1].outcome = seq_ctl.events[-1].outcome or completion_reason
                    break

            elif config.mode == TestMode.HOLDING:
                gauge_deform += speed_mm_s * interval_s
                target_val = config.target_holding_val
                if config.holding_type == HoldingType.LOAD_HOLD:
                    # 하중 유지 (Creep)
                    if holding_phase == "RAMP":
                        load = min(target_val, gauge_deform * 1500.0)
                        if load >= target_val * 0.99:
                            holding_phase = "HOLDING"
                            hold_start_time = elapsed_time
                            base_hold_disp = gauge_deform
                            base_hold_load = target_val
                    else:
                        h_time = elapsed_time - hold_start_time
                        creep_rate = 0.008  # mm / sec
                        gauge_deform = base_hold_disp + creep_rate * (h_time ** 0.6)
                        noise = random.gauss(0, 0.002)
                        load = base_hold_load * (1.0 + noise)
                        if h_time >= config.holding_duration_s:
                            completion_reason = f"목표 유지 시간({config.holding_duration_s:.0f}초) 완료"
                            break
                else:
                    # 변위 유지 (Relaxation)
                    if holding_phase == "RAMP":
                        load = gauge_deform * 1800.0
                        if gauge_deform >= target_val:
                            gauge_deform = target_val
                            holding_phase = "HOLDING"
                            hold_start_time = elapsed_time
                            base_hold_load = load
                            base_hold_disp = gauge_deform
                    else:
                        h_time = elapsed_time - hold_start_time
                        gauge_deform = base_hold_disp
                        relax_ratio = 0.20 * (1.0 - math.exp(-h_time / 15.0))
                        noise = random.gauss(0, 0.002)
                        load = base_hold_load * (1.0 - relax_ratio) * (1.0 + noise)
                        if h_time >= config.holding_duration_s:
                            completion_reason = f"목표 유지 시간({config.holding_duration_s:.0f}초) 완료"
                            break

                load = max(0.0, load * (1.0 + random.gauss(0, 0.0008)))
                stress = load / area
                strain = gauge_deform / ext_gl

            else:
                # 인장 / 압축 / 굽힘
                gauge_deform += speed_mm_s * interval_s
                load, stress, strain = evaluate(gauge_deform)
                load = max(0.0, load * (1.0 + random.gauss(0, 0.003)))

                if config.mode != TestMode.COMPRESSION and strain >= uts_strain and peak_load > 50:
                    drop_ratio = (peak_load - load) / peak_load
                    if drop_ratio >= config.fracture_drop_ratio or strain >= fracture_strain:
                        completion_reason = (
                            "굽힘 시편 파단 (Flexural Fracture)"
                            if config.mode == TestMode.BENDING
                            else "시편 파단 (Fracture Detected)"
                        )
                        break

            if load > peak_load:
                peak_load = load

            # 크로스헤드 변위 = 표점부 변형 + 기계 탄성 변형
            disp = gauge_deform + compliance * load

            # --- 신율계 원시 신호 생성 및 복원 ---
            ext_disp = 0.0
            ext_strain = 0.0
            ext_raw = 0.0
            ext_valid = False
            if ext_on:
                ext_raw, ext_disp = self._encode_ext(gauge_deform)
                ext_strain = self.ext.to_strain_pct(ext_disp)
                ext_valid = True

            point = DataPoint(
                time_s=round(elapsed_time, 3),
                displacement_mm=round(disp, 4),
                load_n=round(load, 2),
                stress_mpa=round(stress, 2),
                strain_pct=round(ext_strain if ext_valid else strain * 100.0, 3),
                ext_disp_mm=round(ext_disp, 4),
                ext_strain_pct=round(ext_strain, 3),
                ext_raw=ext_raw,
                ext_valid=ext_valid,
            )

            self.current_displacement = disp
            self.current_load = load
            self.current_ext_disp_mm = ext_disp
            self.current_ext_raw = ext_raw
            self.current_ext_valid = ext_valid

            if self.on_data_received:
                try:
                    self.on_data_received(point)
                except Exception:
                    # 창이 닫힌 뒤(시험 중 UI 종료) 신호 전달이 실패해도 시뮬레이션은 계속한다
                    pass

            if disp >= config.max_displacement_mm:
                completion_reason = "최대 변위 도달 (Safety Limit)"
                if seq_ctl is not None and not seq_ctl.is_finished:
                    seq_ctl.abort(elapsed_time, load, disp, "안전 한계 도달")
                break

            elapsed_loop = time.time() - loop_start
            sleep_time = max(0.001, (interval_s - elapsed_loop) / max(0.001, self.time_scale))
            time.sleep(sleep_time)

        # 시퀀스 기록 마무리 (중지/안전 한계로 끝난 경우 진행 중 단계를 닫는다)
        if seq_ctl is not None:
            if not seq_ctl.is_finished:
                seq_ctl.abort(time.time() - start_time, load, disp, "시험 중단")
            self.step_events = seq_ctl.events_as_dicts()

        self.is_running = False
        if self.on_test_completed:
            try:
                self.on_test_completed(completion_reason)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 소프트 PID 제어 시뮬레이션 (하중 속도 · 응력 속도 · 하중 유지)
    # ------------------------------------------------------------------
    SERVO_TIME_CONSTANT_S = 0.06     # 서보·볼스크류 응답 지연 (1차 지연)
    HOLD_CREEP_STRAIN_RATE = 1.0e-6  # 하중 유지 중 시편 크리프 (변형률/s)
    HOLD_OVERLOAD_RATIO = 1.20       # 목표 하중 20% 초과 시 안전 정지

    def _run_controlled(self):
        """
        하중·응력 속도 제어 시험.
        실제 장비와 같은 순서(지연된 계측 -> 제어 주기 계산 -> 서보 응답 -> 시편 변형)로 계산한다.
        """
        specimen = self.specimen
        config = self.config
        controller = self.controller
        area = specimen.cross_sectional_area_mm2
        l0 = specimen.gauge_length_mm
        mode = ControlMode.parse(config.control_mode)
        hold_mode = mode is ControlMode.LOAD_HOLD

        ext_on = bool(self.ext.enabled)
        ext_gl = self.ext.gauge_length_mm if ext_on else l0

        profile = self.profile
        scatter = self.scatter
        e_modulus = profile["e"] * scatter.get("e", 1.0)
        yield_stress = profile["sy"] * scatter.get("sy", 1.0)
        yield_strain = yield_stress / e_modulus
        uts_stress = profile["su"] * scatter.get("su", 1.0)
        uts_strain = profile["eu"]
        fracture_strain = profile["ef"] * scatter.get("ef", 1.0)

        interval = 1.0 / max(5, config.sampling_rate_hz)
        ctrl_period = 1.0 / max(1.0, config.control_rate_hz)
        delay_s = max(0.0, min(0.5, config.comm_delay_ms / 1000.0))

        def evaluate(gauge_deform: float) -> Tuple[float, float, float]:
            """표점부 변형량 -> (하중 N, 응력 MPa, 변형률)"""
            strain = gauge_deform / l0
            if config.mode == TestMode.COMPRESSION:
                stress = self._calc_compression_stress(strain, e_modulus, yield_stress, yield_strain)
            else:
                stress = self._calc_tensile_stress(
                    strain, e_modulus, yield_stress, yield_strain,
                    uts_stress, uts_strain, fracture_strain
                )
            return max(0.0, stress * area), stress, strain

        start_time = time.time()
        elapsed = 0.0
        gauge_deform = 0.0
        load = 0.0
        stress = 0.0
        strain = 0.0
        peak_load = 0.0
        speed_act_mm_s = 0.0        # 실제 크로스헤드 속도 (서보 지연 반영)
        speed_cmd_mm_s = 0.0
        next_ctrl = 0.0
        last_ctrl_t = 0.0
        fixed_speed_set = False
        stopping = False     # 실시간 속도 변경 미지원 시 1회 설정 여부
        history: List[Tuple[float, float, float]] = []
        hist_idx = 0
        completion_reason = "정상 종료"

        while not self._stop_event.is_set():
            loop_start = time.time()
            # 가상 시간은 물리 스텝과 정확히 일치시킨다 (시간 배속은 대기 시간만 줄인다)
            elapsed += interval

            # 1) 계측 이력 적재 및 통신 지연 반영 (지연된 계측값만 보인다)
            history.append((elapsed, load, gauge_deform))
            target_t = elapsed - delay_s
            while hist_idx + 1 < len(history) and history[hist_idx + 1][0] <= target_t:
                hist_idx += 1
            _, meas_load, meas_disp = history[hist_idx]

            # 2) 제어 주기마다 속도 명령 갱신
            if elapsed + 1e-9 >= next_ctrl:
                dt_ctrl = interval if next_ctrl == 0 else elapsed - last_ctrl_t
                if not stopping:
                    ctrl_speed = controller.update(dt_ctrl, meas_load, meas_disp)
                    last_ctrl_t = elapsed
                    if controller.live_speed_control:
                        speed_cmd_mm_s = ctrl_speed / 60.0
                    else:
                        # 고정 속도 폴백: 초기 강성으로 환산한 속도를 한 번만 넣는다
                        if not fixed_speed_set:
                            ff = controller.feedforward_speed_mm_min
                            if ff > 0:
                                speed_cmd_mm_s = ff / 60.0
                                fixed_speed_set = True
                else:
                    speed_cmd_mm_s = 0.0

                self.control_trace.append(TrackingSample(
                    time_s=round(elapsed, 3),
                    setpoint_n=round(controller.setpoint_load_n, 2),
                    load_n=round(load, 2),
                    speed_mm_min=round(speed_cmd_mm_s * 60.0, 3),
                    stiffness_n_per_mm=round(controller.stiffness_n_per_mm, 1),
                ))
                next_ctrl += ctrl_period

            # 3) 서보 응답 지연 후 이동, 하중 유지 중에는 크리프만큼 시편이 더 늘어난다
            speed_act_mm_s += (speed_cmd_mm_s - speed_act_mm_s) * min(
                1.0, interval / max(1e-3, self.SERVO_TIME_CONSTANT_S))
            creep = 0.0
            if hold_mode and controller.phase == ControlPhase.HOLD and load > 0:
                creep = l0 * self.HOLD_CREEP_STRAIN_RATE * interval
            gauge_deform = max(0.0, gauge_deform + speed_act_mm_s * interval + creep)

            # 4) 시편 응답
            raw_load, stress, strain = evaluate(gauge_deform)
            load = max(0.0, raw_load * (1.0 + random.gauss(0, 0.003)))
            if load > peak_load:
                peak_load = load

            # 5) 신율계 원시 신호 생성 및 복원
            ext_disp = 0.0
            ext_strain = 0.0
            ext_raw = 0.0
            ext_valid = False
            if ext_on:
                ext_raw, ext_disp = self._encode_ext(gauge_deform)
                ext_strain = self.ext.to_strain_pct(ext_disp)
                ext_valid = True

            point = DataPoint(
                time_s=round(elapsed, 3),
                displacement_mm=round(gauge_deform, 4),
                load_n=round(load, 2),
                stress_mpa=round(stress, 2),
                strain_pct=round(ext_strain if ext_valid else strain * 100.0, 3),
                ext_disp_mm=round(ext_disp, 4),
                ext_strain_pct=round(ext_strain, 3),
                ext_raw=ext_raw,
                ext_valid=ext_valid,
            )

            self.current_displacement = gauge_deform
            self.current_load = load
            self.current_ext_disp_mm = ext_disp
            self.current_ext_raw = ext_raw
            self.current_ext_valid = ext_valid

            if self.on_data_received:
                try:
                    self.on_data_received(point)
                except Exception:
                    pass

            # 6) 종료 판정
            if stopping and abs(speed_act_mm_s) < 2e-6:
                break
            if controller.is_rate_unreachable:
                completion_reason = "목표 하중 속도 미달 (현재 강성 · 최대 속도 초과)"
                break
            if controller.is_finished:
                completion_reason = "목표 하중 유지 완료"
                break
            if hold_mode and controller.target_load_n > 0:
                if load > controller.target_load_n * self.HOLD_OVERLOAD_RATIO:
                    completion_reason = "과하중 안전 정지 (목표 20% 초과)"
                    break
                if not controller.live_speed_control and meas_load >= controller.target_load_n:
                    # 실시간 보정이 없으면 지연된 계측으로 정지 지령만 줄 수 있다
                    completion_reason = "목표 하중 도달 (고정 속도 · 실시간 보정 없음)"
                    stopping = True
            if config.mode != TestMode.COMPRESSION and strain >= uts_strain and peak_load > 50:
                drop_ratio = (peak_load - load) / peak_load
                if drop_ratio >= config.fracture_drop_ratio or strain >= fracture_strain:
                    completion_reason = "시편 파단 (Fracture Detected)"
                    break
            if gauge_deform >= config.max_displacement_mm:
                completion_reason = "최대 변위 도달 (Safety Limit)"
                break

            elapsed_loop = time.time() - loop_start
            time.sleep(max(0.001, (interval - elapsed_loop) / max(0.001, self.time_scale)))

        self.is_running = False
        if self.on_test_completed:
            try:
                self.on_test_completed(completion_reason)
            except Exception:
                pass

    def _calc_tensile_stress(self, strain: float, E: float, sy: float, ey: float,
                             su: float, eu: float, ef: float) -> float:
        """인장/휨 S-S 곡선 물리 함수 (탄성 -> 항복소성 -> 네킹 -> 파단)"""
        if strain <= 0:
            return 0.0
        if strain < ey:
            return E * strain
        elif strain < eu:
            ratio = (strain - ey) / max(0.0001, (eu - ey))
            return sy + (su - sy) * (ratio ** 0.45)
        elif strain < ef:
            ratio = (strain - eu) / max(0.0001, (ef - eu))
            return su * (1.0 - 0.45 * (ratio ** 1.3))
        else:
            return 0.0

    def _calc_compression_stress(self, strain: float, E: float, sy: float, ey: float) -> float:
        """압축 응력 곡선 (탄성 -> 소성 배럴링 가공경화)"""
        if strain <= 0:
            return 0.0
        if strain < ey:
            return E * strain
        else:
            plastic_strain = strain - ey
            return sy + 250.0 * (plastic_strain ** 0.5)
