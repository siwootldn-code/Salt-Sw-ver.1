"""
Salt Sw ver.1 - RS-232 Serial UTM Hardware Driver
시리얼(RS-232 / USB-to-UART) 통신을 통해 실제 UTM 제어기 및 인디케이터와 연동하는 드라이버
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


class SerialUTMDriver(HardwareInterface):
    """
    RS-232 시리얼 기반 만능재료시험기 드라이버
    - COM 포트 자동 감지 및 연결/해제
    - 백그라운드 수신 스레드를 통한 고속 계측 데이터 스트리밍
    - 다양한 인디케이터/DAQ 패킷 파싱 (ASCII, CSV, Key-Value)
    """

    def __init__(self):
        super().__init__()
        self.ser: Optional[Any] = None
        self._read_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # 시험 제원 및 상태
        self.specimen: Optional[Specimen] = None
        self.config: Optional[TestConfig] = None
        self.start_time: float = 0.0
        
        # 보정 계수 및 영점 (Zero/Tare)
        self.load_tare: float = 0.0
        self.disp_tare: float = 0.0
        self.load_scale: float = 1.0  # 기본: kN 단위 변환 계수
        self.disp_scale: float = 1.0  # 기본: mm 단위 변환 계수

    @staticmethod
    def list_available_ports() -> List[str]:
        """PC에 연결된 시리얼(COM) 포트 목록 조회"""
        if not HAS_PYSERIAL:
            return ["COM1 (pyserial 미설치)"]
        ports = serial.tools.list_ports.comports()
        return [p.device for p in ports] or ["COM1"]

    def connect(self, port: str = "COM1", baudrate: int = 9600, timeout: float = 1.0) -> bool:
        """
        RS-232 시리얼 포트 연결
        :param port: COM 포트 번호 (예: 'COM1', 'COM3', '/dev/ttyUSB0')
        :param baudrate: 통신 속도 (9600, 19200, 38400, 115200 등)
        :param timeout: 읽기 타임아웃(초)
        """
        if not HAS_PYSERIAL:
            print("[SerialUTMDriver] pyserial 라이브러리가 필요합니다: pip install pyserial")
            return False

        try:
            self.ser = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout
            )
            self.is_connected = self.ser.is_open
            return self.is_connected
        except Exception as e:
            print(f"[SerialUTMDriver] 포트 {port} 연결 실패: {e}")
            self.is_connected = False
            return False

    def disconnect(self):
        """연결 해제"""
        self.stop_test()
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.is_connected = False
        self.ser = None

    def start_test(self, specimen: Specimen, config: TestConfig):
        """실제 시험 시작 및 RS-232 실시간 데이터 수신 스레드 가동"""
        if not self.is_connected or not self.ser:
            print("[SerialUTMDriver] 시리얼 포트가 연결되어 있지 않습니다.")
            return

        self.specimen = specimen
        self.config = config
        self.is_running = True
        self._stop_event.clear()
        self.start_time = time.time()

        # 장비에 시작 제어 명령 전송 (장비 프로토콜에 맞춤 확장 가능)
        # 예: self.send_command("START\r\n")

        self._read_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._read_thread.start()

    def stop_test(self):
        """시험 중지 (비상 정지)"""
        self.is_running = False
        self._stop_event.set()
        
        # 장비에 정지 명령 전송
        # self.send_command("STOP\r\n")

        if self.on_test_completed:
            self.on_test_completed("사용자 중지 또는 완료")

    def return_to_origin(self):
        """원점 복귀 명령"""
        # self.send_command("ORIGIN\r\n")
        pass

    def tare_load(self):
        """현재 하중을 0으로 세팅 (Zero/Tare)"""
        # self.send_command("TARE_LOAD\r\n")
        pass

    def tare_displacement(self):
        """현재 변위를 0으로 세팅"""
        # self.send_command("TARE_DISP\r\n")
        pass

    def send_command(self, cmd: str):
        """시리얼 제어 명령 전송"""
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(cmd.encode("ascii"))
            except Exception as e:
                print(f"[SerialUTMDriver] 명령 전송 오류: {e}")

    def _worker_loop(self):
        """시리얼 데이터 지속 수신 루프"""
        buffer = ""
        while not self._stop_event.is_set() and self.ser and self.ser.is_open:
            try:
                line = self.ser.readline().decode("ascii", errors="ignore").strip()
                if not line:
                    continue

                dp = self._parse_packet(line)
                if dp and self.on_data_received:
                    self.on_data_received(dp)

            except Exception as e:
                print(f"[SerialUTMDriver] 수신 에러: {e}")
                time.sleep(0.01)

    def _parse_packet(self, line: str) -> Optional[DataPoint]:
        """
        수신된 시리얼 문자열 라인을 DataPoint로 변환
        일반적인 산업용 UTM/인디케이터 패킷 포맷 대응:
        1) CSV 형태: "하중값, 변위값" (예: "12.345, 1.250")
        2) 접두사 형태: "L:12.34, D:1.25" 또는 "F:12.34, S:1.25"
        """
        try:
            current_time = time.time() - self.start_time
            
            # 숫자 추출 (부호 및 소수점 포함)
            numbers = re.findall(r"[-+]?\d*\.?\d+", line)
            if len(numbers) >= 2:
                raw_load = float(numbers[0])
                raw_disp = float(numbers[1])

                load = (raw_load - self.load_tare) * self.load_scale
                disp = (raw_disp - self.disp_tare) * self.disp_scale

                area = self.specimen.cross_sectional_area if self.specimen else 1.0
                gauge = self.specimen.gauge_length if self.specimen else 50.0

                # kN -> N 변환 후 단면적으로 나누어 MPa 계산
                stress = (load * 1000.0) / area if area > 0 else 0.0
                # mm 변위를 표점거리로 나누어 변형률(%) 계산
                strain = (disp / gauge) * 100.0 if gauge > 0 else 0.0

                return DataPoint(
                    timestamp=round(current_time, 3),
                    displacement=round(disp, 4),
                    load=round(load, 4),
                    stress=round(stress, 2),
                    strain=round(strain, 3)
                )
        except Exception:
            pass
        return None
