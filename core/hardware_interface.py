"""
Salt Sw ver.1 - Hardware Interface Base Class
실제 계측기(RS-232, Modbus RTU, USB DAQ 등)와의 연동을 위한 추상 인터페이스
"""

from abc import ABC, abstractmethod
from typing import Callable, List, Optional
from .models import DataPoint, ExtensometerSettings, TestConfig, Specimen
from .sequence import SequenceProgram


class HardwareInterface(ABC):
    """UTM 하드웨어 제어 및 데이터 수집 추상 기본 클래스"""

    # 시험 중 실시간 속도 변경(SPD 명령) 지원 여부
    # 봉신 P2020 / P2014 는 아직 확인되지 않았으므로 기본값은 미지원이다.
    supports_live_speed_control: bool = False

    def __init__(self):
        self.is_connected: bool = False
        self.is_running: bool = False
        self.on_data_received: Optional[Callable[[DataPoint], None]] = None
        self.on_test_completed: Optional[Callable[[str], None]] = None
        # 다단계 시퀀스 실행 기록 (시험 종료 후 결과/그래프에 표시)
        self.step_events: List[dict] = []
        self.sequence_name: str = ""

    @abstractmethod
    def connect(self, port: str = "COM1", baudrate: int = 115200) -> bool:
        """장비 연결"""
        pass

    @abstractmethod
    def disconnect(self):
        """장비 연결 해제"""
        pass

    @abstractmethod
    def start_test(self, specimen: Specimen, config: TestConfig):
        """시험 시작"""
        pass

    @abstractmethod
    def stop_test(self):
        """시험 중지 (비상 정지)"""
        pass

    @abstractmethod
    def return_to_origin(self):
        """크로스헤드 원점 복귀"""
        pass

    def tare_load(self):
        """하중 영점 맞춤 (Tare)"""
        pass

    def tare_displacement(self):
        """변위 영점 맞춤 (Tare)"""
        pass

    def tare_extensometer(self):
        """신율계 영점 맞춤 (mV 오프셋 / 펄스 카운트 기준점 설정)"""
        pass

    def set_extensometer(self, settings: Optional[ExtensometerSettings]):
        """신율계 설정 적용 (환경 설정 값) - 지원하지 않는 드라이버는 무시"""
        pass

    def set_speed(self, speed_mm_min: float):
        """시험 중 크로스헤드 속도 변경 - 실시간 변경을 지원하지 않으면 무시"""
        pass

    def current_control_status(self) -> str:
        """소프트 PID 제어 상태 표시 문자열 (변위 제어·미지원이면 빈 문자열)"""
        return ""

    def current_sequence_status(self) -> str:
        """진행 중인 시퀀스 단계 표시 문자열 (미지원 드라이버는 빈 문자열)"""
        return ""
