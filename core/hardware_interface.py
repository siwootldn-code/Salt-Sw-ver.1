"""
Salt Sw ver.1 - Hardware Interface Base Class
실제 계측기(RS-232, Modbus RTU, USB DAQ 등)와의 연동을 위한 추상 인터페이스
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional
from .models import DataPoint, TestConfig, Specimen


class HardwareInterface(ABC):
    """UTM 하드웨어 제어 및 데이터 수집 추상 기본 클래스"""

    def __init__(self):
        self.is_connected: bool = False
        self.is_running: bool = False
        self.on_data_received: Optional[Callable[[DataPoint], None]] = None
        self.on_test_completed: Optional[Callable[[str], None]] = None

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
