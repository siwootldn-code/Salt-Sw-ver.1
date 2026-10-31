"""
Salt Sw ver.1 - Virtual UTM Hardware Simulator
실제 만능재료시험기 없이도 사실적인 인장/압축 시험 데이터를 실시간 생성하는 물리 시뮬레이터
"""

import math
import random
import threading
import time
from typing import Callable, Optional
from .hardware_interface import HardwareInterface
from .models import DataPoint, Specimen, TestConfig, TestMode


class VirtualUTMSimulator(HardwareInterface):
    """
    물리 기반 가상 재료시험기 시뮬레이터.
    선형 탄성, 소성 변형, 가공 경화, 네킹 및 급격한 파단 메커니즘을 시뮬레이션합니다.
    """

    def __init__(self):
        super().__init__()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.specimen: Optional[Specimen] = None
        self.config: Optional[TestConfig] = None
        self.current_displacement: float = 0.0
        self.current_load: float = 0.0

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

    def _run_simulation(self):
        """실시간 물리 연산 루프"""
        specimen = self.specimen
        config = self.config
        area = specimen.cross_sectional_area_mm2
        l0 = specimen.gauge_length_mm
        
        # 재료 기본 특성 (강재 SS400 기준 표준 매개변수)
        # E = 205 GPa = 205,000 MPa
        # Yield Strength ~ 260 MPa
        # Tensile Strength ~ 440 MPa
        e_modulus_mpa = 205000.0
        yield_stress_mpa = 260.0
        yield_strain = yield_stress_mpa / e_modulus_mpa  # ~ 0.00127 (0.127%)
        uts_stress_mpa = 450.0
        uts_strain = 0.16  # 16% 변형률에서 최대 인장강도 도달
        fracture_strain = 0.24  # 24% 변형률에서 파단
        
        speed_mm_s = config.test_speed_mm_min / 60.0
        interval_s = 1.0 / max(5, config.sampling_rate_hz)
        
        start_time = time.time()
        disp = 0.0
        peak_load = 0.0
        is_fractured = False
        completion_reason = "정상 종료"

        while not self._stop_event.is_set():
            loop_start = time.time()
            elapsed_time = loop_start - start_time
            
            # 변위 증가
            disp += speed_mm_s * interval_s
            strain = disp / l0
            
            # 모드별 응력 곡선 계산
            if config.mode == TestMode.TENSILE:
                stress = self._calc_tensile_stress(
                    strain, e_modulus_mpa, yield_stress_mpa, yield_strain,
                    uts_stress_mpa, uts_strain, fracture_strain
                )
            else:
                # 압축 시험
                stress = self._calc_compression_stress(
                    strain, e_modulus_mpa, yield_stress_mpa, yield_strain
                )

            # 노이즈 추가 (로드셀 미세 진동: ±0.3%)
            noise_factor = 1.0 + random.gauss(0, 0.003)
            load = max(0.0, stress * area * noise_factor)
            
            if load > peak_load:
                peak_load = load

            # 데이터 포인트 생성
            point = DataPoint(
                time_s=round(elapsed_time, 3),
                displacement_mm=round(disp, 4),
                load_n=round(load, 2)
            )
            point.compute_mechanics(area, l0)

            self.current_displacement = disp
            self.current_load = load

            # 콜백 호출
            if self.on_data_received:
                self.on_data_received(point)

            # 파단 감지 (인장 시험 시 피크 하중 도달 후 지정 비율 이하로 하중 급감 또는 파단 변형률 도달)
            if config.mode == TestMode.TENSILE:
                if strain >= uts_strain and peak_load > 100:
                    drop_ratio = (peak_load - load) / peak_load
                    if drop_ratio >= config.fracture_drop_ratio or strain >= fracture_strain:
                        is_fractured = True
                        completion_reason = "시편 파단 (Fracture Detected)"
                        break

            # 안전 한계 변위 도달 체크
            if disp >= config.max_displacement_mm:
                completion_reason = "최대 변위 도달 (Safety Limit)"
                break

            # 샘플링 주기 지연
            elapsed_loop = time.time() - loop_start
            sleep_time = max(0.001, interval_s - elapsed_loop)
            time.sleep(sleep_time)

        self.is_running = False
        if self.on_test_completed:
            self.on_test_completed(completion_reason)

    def _calc_tensile_stress(self, strain: float, E: float, sy: float, ey: float,
                             su: float, eu: float, ef: float) -> float:
        """인장 S-S 곡선 물리 함수 (탄성 -> 항복소성 -> 네킹 -> 파단)"""
        if strain <= 0:
            return 0.0
        
        # 1. 탄성 구간 (Linear Elastic)
        if strain < ey:
            return E * strain
        
        # 2. 소성 변형 및 가공 경화 (Hollomon 식 모델링: sigma = K * eps^n)
        elif strain < eu:
            # 항복 후 UTS까지 매끄러운 곡선
            ratio = (strain - ey) / max(0.0001, (eu - ey))
            # 응력 상승 (경화 지수 반영)
            return sy + (su - sy) * (ratio ** 0.45)
        
        # 3. 네킹 구간 (UTS 이후 파단까지 국부적 단면 수축으로 하중 감소)
        elif strain < ef:
            ratio = (strain - eu) / max(0.0001, (ef - eu))
            return su * (1.0 - 0.45 * (ratio ** 1.3))
        
        # 4. 완전 파단 (Fracture)
        else:
            return 0.0

    def _calc_compression_stress(self, strain: float, E: float, sy: float, ey: float) -> float:
        """압축 응력 곡선 (탄성 -> 소성 소착/가공경화)"""
        if strain <= 0:
            return 0.0
        if strain < ey:
            return E * strain
        else:
            # 압축 시 배럴링 및 지속적 가공경화로 응력이 지속 증가하는 특성
            plastic_strain = strain - ey
            return sy + 250.0 * (plastic_strain ** 0.5)
