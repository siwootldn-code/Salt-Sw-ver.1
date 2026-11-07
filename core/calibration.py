"""
Salt Sw ver.1 - Calibration Manager
로드셀(하중) 2점 교정(Zero/Span) 및 크로스헤드 속도/변위 정밀 교정 관리자
"""

import json
import os
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class CalibrationData:
    # 하중 교정 파라미터 (Bongshin Loadcell)
    load_zero_offset: float = 0.0        # 무부하 영점 오프셋 (raw)
    load_scale_factor: float = 1.0       # 스팬 보정 비례 계수 (기준하중 / 실측하중)
    last_load_calib_date: str = "-"      # 최근 하중 교정 일자

    # 속도 교정 파라미터 (Servo Crosshead Speed)
    speed_scale_factor: float = 1.0      # 속도 보정 계수 (목표속도 / 실측속도)
    last_speed_calib_date: str = "-"     # 최근 속도 교정 일자

    # 변위 교정 파라미터 (Displacement)
    disp_zero_offset: float = 0.0        # 변위 영점 오프셋
    disp_scale_factor: float = 1.0       # 변위 스케일 계수


class CalibrationManager:
    """교정 설정값 로드 및 영구 저장 관리자"""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, "calib_config.json")
        self.config_path = config_path
        self.data = CalibrationData()
        self.load()

    def load(self):
        """설정 파일에서 교정 파라미터 로드"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    self.data = CalibrationData(**raw)
            except Exception as e:
                print(f"[CalibrationManager] 설정 로드 실패 (기본값 사용): {e}")

    def save(self):
        """현재 교정 파라미터를 JSON으로 영구 저장"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(asdict(self.data), f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[CalibrationManager] 설정 저장 실패: {e}")
            return False

    def apply_load(self, raw_load: float) -> float:
        """원시 하중값에 영점 및 스팬 교정 계수 적용"""
        return (raw_load - self.data.load_zero_offset) * self.data.load_scale_factor

    def apply_disp(self, raw_disp: float) -> float:
        """원시 변위값에 영점 및 스케일 계수 적용"""
        return (raw_disp - self.data.disp_zero_offset) * self.data.disp_scale_factor

    def get_corrected_speed(self, target_speed_mm_min: float) -> float:
        """서보드라이버 지령 속도에 보정 계수 적용"""
        return target_speed_mm_min * self.data.speed_scale_factor
