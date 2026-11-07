"""
Salt Sw ver.1 - RS-232 Serial UTM Hardware Driver
봉신(Bongshin) 로드셀 및 P2020, P2014 디지털 인디케이터 전용 시리얼 통신 드라이버
Baudrate: 115,200 bps (기본값)
"""

import time
import re
import threading
from typing import Callable, Optional, List, Dict, Any

try:
    import serial
    import serial.tools.list_ports
    HAS_PYSERIAL = True
except ImportError:
    serial = None
    HAS_PYSERIAL = False

from .hardware_interface import HardwareInterface
from .models import DataPoint, TestConfig, Specimen
from .calibration import CalibrationManager


class SerialUTMDriver(HardwareInterface):
    """
    RS-232 시리얼 기반 만능재료시험기 드라이버
    - 봉신(Bongshin) 로드셀 및 P2020, P2014 인디케이터 115,200 bps 지원
    - 백그라운드 고속 데이터 수신 스레드
    - 하중(Load, N/kN/kgf) 및 변위(Displacement, mm) 실시간 파싱
    - 영점(Tare/Zero) 보정 및 스케일 변환
    - 원시 패킷(Raw Packet) 실시간 모니터링 지원
    """

    def __init__(self):
        super().__init__()
        self.ser: Optional[Any] = None
        self._read_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # 콜백 함수
        self.on_raw_data_received: Optional[Callable[[str], None]] = None
        
        # 시험 제원 및 상태
        self.specimen: Optional[Specimen] = None
        self.config: Optional[TestConfig] = None
        self.start_time: float = 0.0
        
        # 보정 계수 및 영점 (Zero/Tare)
        self.calib_mgr = CalibrationManager()
        self.load_tare: float = 0.0
        self.disp_tare: float = 0.0
        self.last_raw_load: float = 0.0
        self.last_raw_disp: float = 0.0
        
        # 단위 스케일 팩터 (기본: N 단위로 변환)
        # N: 1.0, kN: 1000.0, kgf: 9.80665
        self.load_unit_multiplier: float = 1.0  
        self.disp_unit_multiplier: float = 1.0  # 기본: mm

    @staticmethod
    def list_available_ports() -> List[str]:
        """PC에 연결된 시리얼(COM) 포트 목록 조회"""
        if not HAS_PYSERIAL:
            return ["COM1", "COM2", "COM3", "COM4"]
        try:
            ports = serial.tools.list_ports.comports()
            port_list = [p.device for p in ports]
            return port_list if port_list else ["COM1", "COM2", "COM3"]
        except Exception:
            return ["COM1", "COM2", "COM3"]

    def connect(self, port: str = "COM1", baudrate: int = 115200, timeout: float = 0.5) -> bool:
        """
        RS-232 시리얼 포트 연결 (기본 115,200 bps, 8-N-1)
        """
        if not HAS_PYSERIAL:
            print("[SerialUTMDriver] pyserial 라이브러리가 필요합니다: pip install pyserial")
            return False

        try:
            if self.ser and self.ser.is_open:
                self.ser.close()

            self.ser = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout
            )
            self.is_connected = self.ser.is_open
            print(f"[SerialUTMDriver] {port} 포트 연결 성공 (Baudrate: {baudrate})")
            
            # 연결 즉시 원시 데이터 모니터링을 위해 수신 루프 가동
            self._stop_event.clear()
            self._read_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._read_thread.start()
            
            return self.is_connected
        except Exception as e:
            print(f"[SerialUTMDriver] 포트 {port} 연결 실패: {e}")
            self.is_connected = False
            return False

    def disconnect(self):
        """연결 해제"""
        self.is_running = False
        self._stop_event.set()
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.is_connected = False
        self.ser = None
        print("[SerialUTMDriver] 시리얼 포트 연결 해제됨")

    def start_test(self, specimen: Specimen, config: TestConfig):
        """실제 시험 시작 및 계측 데이터 수집 활성화"""
        self.specimen = specimen
        self.config = config
        self.is_running = True
        self.start_time = time.time()
        
        # 시작 시 현재 값을 영점으로 자동 보정
        self.tare_load()
        self.tare_displacement()

    def stop_test(self):
        """시험 중지 (비상 정지)"""
        self.is_running = False
        if self.on_test_completed:
            self.on_test_completed("사용자 중지 또는 시험 완료")

    def return_to_origin(self):
        """원점 복귀 (하드웨어 제어 지원 시 명령 송신)"""
        self.send_command("ORIGIN\r\n")

    def tare_load(self):
        """현재 하중을 0으로 세팅 (Zero/Tare)"""
        self.calib_mgr.data.load_zero_offset = self.last_raw_load
        self.calib_mgr.save()
        self.load_tare = 0.0
        print(f"[SerialUTMDriver] 하중 영점 세팅 완료: Zero Offset = {self.calib_mgr.data.load_zero_offset}")

    def tare_displacement(self):
        """현재 변위를 0으로 세팅"""
        self.calib_mgr.data.disp_zero_offset = self.last_raw_disp
        self.calib_mgr.save()
        self.disp_tare = 0.0
        print(f"[SerialUTMDriver] 변위 영점 세팅 완료: Zero Offset = {self.calib_mgr.data.disp_zero_offset}")

    def calibrate_load_span(self, ref_load_val: float, unit: str = "kgf") -> float:
        """
        기준 하중(분동/기준기) 인가 상태에서 스팬 교정 계수(Span Factor) 산출 및 영구 저장
        """
        if unit == "kgf":
            ref_n = ref_load_val * 9.80665
        elif unit == "kN":
            ref_n = ref_load_val * 1000.0
        else:
            ref_n = ref_load_val

        # 현재 수신 중인 순수 센서 하중 (오프셋 뺀 값)
        current_raw_delta = (self.last_raw_load - self.calib_mgr.data.load_zero_offset) * self.load_unit_multiplier
        if abs(current_raw_delta) > 0.001:
            factor = ref_n / current_raw_delta
            self.calib_mgr.data.load_scale_factor = round(factor, 6)
            from datetime import datetime
            self.calib_mgr.data.last_load_calib_date = datetime.now().strftime("%Y-%m-%d %H:%M")
            self.calib_mgr.save()
            return self.calib_mgr.data.load_scale_factor
        return 1.0

    def calibrate_speed(self, target_speed_mm_min: float, measured_dist_mm: float, duration_sec: float = 60.0) -> float:
        """
        목표 속도로 duration_sec 동안 구동 후 실측 이동 거리 기반 속도 보정 계수 산출 및 영구 저장
        """
        actual_speed = (measured_dist_mm / duration_sec) * 60.0
        if actual_speed > 0.001:
            factor = target_speed_mm_min / actual_speed
            self.calib_mgr.data.speed_scale_factor = round(factor, 6)
            from datetime import datetime
            self.calib_mgr.data.last_speed_calib_date = datetime.now().strftime("%Y-%m-%d %H:%M")
            self.calib_mgr.save()
            return self.calib_mgr.data.speed_scale_factor
        return 1.0

    def send_command(self, cmd: str):
        """시리얼 명령 전송"""
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(cmd.encode("ascii"))
            except Exception as e:
                print(f"[SerialUTMDriver] 명령 전송 오류: {e}")

    def _worker_loop(self):
        """시리얼 데이터 지속 수신 루프 (고속 스트리밍 대응)"""
        while not self._stop_event.is_set() and self.ser and self.ser.is_open:
            try:
                line = self.ser.readline().decode("ascii", errors="ignore").strip()
                if not line:
                    continue

                # 원시 패킷 수신 콜백 전달 (UI 모니터링용)
                if self.on_raw_data_received:
                    self.on_raw_data_received(line)

                # 패킷 파싱
                dp = self._parse_packet(line)
                if dp and self.is_running and self.on_data_received:
                    self.on_data_received(dp)

            except Exception as e:
                time.sleep(0.005)

    def _parse_packet(self, line: str) -> Optional[DataPoint]:
        """
        봉신 및 P2020, P2014 인디케이터 데이터 파싱
        지원 형식:
        1. CSV 형식: "+0012.35, +0001.20" (하중, 변위)
        2. 공백 구분자: "+0012.35  +0001.20"
        3. 봉신 인디케이터 표준 헤더 포맷: "ST,GS,+0012.35kg, +0001.20mm"
        4. 단일 하중 스트림: "ST,GS,+0012.35kg"
        """
        try:
            current_time = time.time() - self.start_time if self.start_time > 0 else 0.0
            
            # STX(0x02), ETX(0x03) 제거
            cleaned = line.replace("\x02", "").replace("\x03", "")
            
            # 부호 포함 부동소수점 숫자 추출
            numbers = re.findall(r"[-+]?\d*\.?\d+", cleaned)
            if not numbers:
                return None

            raw_load = float(numbers[0])
            raw_disp = float(numbers[1]) if len(numbers) >= 2 else (current_time * (self.config.speed_mm_min / 60.0) if self.config else 0.0)

            self.last_raw_load = raw_load
            self.last_raw_disp = raw_disp

            # 영점(Tare) 및 캘리브레이션 보정 적용 (최종 단위: N 및 mm)
            corrected_raw_load = self.calib_mgr.apply_load(raw_load)
            load_n = (corrected_raw_load - self.load_tare) * self.load_unit_multiplier

            corrected_raw_disp = self.calib_mgr.apply_disp(raw_disp)
            disp_mm = (corrected_raw_disp - self.disp_tare) * self.disp_unit_multiplier

            # 하중이 kN 단위로 들어오는 경우 자동 판정
            # 봉신 인디케이터 기본 설정에 맞춤
            area = self.specimen.cross_sectional_area_mm2 if self.specimen else 1.0
            gauge = self.specimen.gauge_length_mm if self.specimen else 50.0

            # 응력: MPa = N / mm^2
            stress_mpa = load_n / area if area > 0 else 0.0
            # 변형률: % = (변위 / 표점거리) * 100
            strain_pct = (disp_mm / gauge) * 100.0 if gauge > 0 else 0.0

            return DataPoint(
                time_s=round(current_time, 3),
                displacement_mm=round(disp_mm, 4),
                load_n=round(load_n, 2),
                stress_mpa=round(stress_mpa, 2),
                strain_pct=round(strain_pct, 3)
            )
        except Exception:
            pass
        return None
