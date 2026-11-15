"""
Salt Sw ver.1 - Virtual UTM Hardware Simulator
실제 만능재료시험기 없이도 4대 시험(인장, 압축, 굽힘, 유지) 데이터를 실시간 생성하는 물리 시뮬레이터

신율계(Extensometer) 지원:
- mV 타입(아날로그 mV/V)과 펄스 타입(엔코더 카운트) 원시 신호를 실제 계측기처럼 생성하고,
  드라이버와 동일한 환산식(ExtensometerSettings)으로 변위를 복원해 시험에 적용한다.
- 크로스헤드 변위 = 표점부 변형 + 프레임/그립 탄성 변형(하중 x 기계 유연성)이므로,
  신율계 변위는 크로스헤드 변위보다 작게 나타난다 (교정된 신율계의 실제 특성).
"""

import math
import random
import threading
import time
from typing import Optional, Tuple

from .hardware_interface import HardwareInterface
from .models import (
    DataPoint, ExtensometerSettings, Specimen, TestConfig, TestMode, BendingType, HoldingType
)


class VirtualUTMSimulator(HardwareInterface):
    """
    물리 기반 가상 재료시험기 시뮬레이터.
    - 인장: 탄성, 소성 항복, 가공 경화, 네킹 및 파단
    - 압축: 탄성, 소성 항복, 배럴링 소착
    - 굽힘(3점/4점): 보의 휨 강성, 탄성 휨, 소성 힌지 및 파단
    - 유지(크리프/이완): 목표 하중 유지 시 크리프 변위 진행, 목표 변위 유지 시 응력 이완
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

        # 신율계 상태
        self.ext: ExtensometerSettings = ExtensometerSettings()
        self.current_ext_disp_mm: float = 0.0
        self.current_ext_raw: float = 0.0
        self.current_ext_valid: bool = False

    # ------------------------------------------------------------------
    def set_extensometer(self, settings: Optional[ExtensometerSettings]):
        """환경 설정의 신율계 구성 적용"""
        self.ext = settings.copy() if settings else ExtensometerSettings()
        self.current_ext_disp_mm = 0.0
        self.current_ext_raw = 0.0
        self.current_ext_valid = False

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

        self._thread = threading.Thread(target=self._run_simulation, daemon=True)
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

        # 재료 기본 특성 (강재 SS400 기준 표준 매개변수)
        e_modulus_mpa = 205000.0
        yield_stress_mpa = 260.0
        yield_strain = yield_stress_mpa / e_modulus_mpa
        uts_stress_mpa = 450.0
        uts_strain = 0.16
        fracture_strain = 0.24

        speed_mm_s = config.test_speed_mm_min / 60.0
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

        while not self._stop_event.is_set():
            loop_start = time.time()
            elapsed_time = loop_start - start_time

            gauge_deform += speed_mm_s * interval_s

            # --- 모드별 거동 연산 ---
            if config.mode == TestMode.HOLDING:
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
                self.on_data_received(point)

            if disp >= config.max_displacement_mm:
                completion_reason = "최대 변위 도달 (Safety Limit)"
                break

            elapsed_loop = time.time() - loop_start
            sleep_time = max(0.001, interval_s - elapsed_loop)
            time.sleep(sleep_time)

        self.is_running = False
        if self.on_test_completed:
            self.on_test_completed(completion_reason)

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
