"""
Salt Sw ver.1 - Preferences Manager (환경 설정 영구 저장)
환경 설정 탭에서 지정한 신율계(Extensometer) 구성과 향후 확장 설정을
preferences.json 파일에 영구 저장하고 복원한다.

- 파일이 없거나 일부 항목이 빠져 있어도 기본값으로 안전하게 동작 (하위 호환)
- 모르는 항목이 들어 있어도 무시하고 읽기 실패로 이어지지 않음
"""

import json
import os
from dataclasses import dataclass, asdict, field
from typing import Any, Optional

from .auto_export import AUTO_REPORT_DIR, FOLDER_RULES
from .models import ExtensometerSettings, ExtensometerType


PREFERENCES_VERSION = 2


@dataclass
class SaveSettings:
    """시험 데이터 · 성적서 저장 폴더 설정"""
    base_dir: str = ""                 # 비어 있으면 기본 output/auto_reports 사용
    folder_rule: str = "date"          # flat | date | mode | specimen | date_mode
    ask_after_test: bool = True        # 시험 완료 후 저장 폴더 선택 창 표시
    last_dir: str = ""                 # 마지막으로 직접 선택한 폴더

    def effective_base_dir(self) -> str:
        return str(self.base_dir or "").strip() or AUTO_REPORT_DIR


@dataclass
class AppPreferences:
    """프로그램 환경 설정"""
    ext: ExtensometerSettings = field(default_factory=ExtensometerSettings)
    save: SaveSettings = field(default_factory=SaveSettings)

    def to_dict(self) -> dict:
        return {
            "version": PREFERENCES_VERSION,
            "extensometer": asdict(self.ext),
            "save": asdict(self.save),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "AppPreferences":
        prefs = cls()
        section = raw.get("extensometer")
        if isinstance(section, dict):
            prefs.ext = _build_extensometer(section)
        save_sec = raw.get("save")
        if isinstance(save_sec, dict):
            prefs.save = _build_save(save_sec)
        return prefs


def _as_float(value: Any, default: float) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf 방어
        return default
    return f


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "y", "on"):
            return True
        if text in ("false", "0", "no", "n", "off"):
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _build_save(raw: dict) -> SaveSettings:
    d = SaveSettings()
    rule = str(raw.get("folder_rule", d.folder_rule)).strip().lower()
    if rule not in FOLDER_RULES:
        rule = d.folder_rule
    return SaveSettings(
        base_dir=str(raw.get("base_dir", d.base_dir) or "").strip(),
        folder_rule=rule,
        ask_after_test=_as_bool(raw.get("ask_after_test"), d.ask_after_test),
        last_dir=str(raw.get("last_dir", d.last_dir) or "").strip(),
    )


def _build_extensometer(raw: dict) -> ExtensometerSettings:
    d = ExtensometerSettings()

    ext_type = str(raw.get("ext_type", d.ext_type)).strip().upper()
    if ext_type not in (ExtensometerType.MV.value, ExtensometerType.PULSE.value):
        ext_type = ExtensometerType.MV.value

    return ExtensometerSettings(
        enabled=_as_bool(raw.get("enabled"), d.enabled),
        ext_type=ext_type,
        gauge_length_mm=max(0.1, _as_float(raw.get("gauge_length_mm"), d.gauge_length_mm)),
        rated_output_mv_v=max(0.0001, _as_float(raw.get("rated_output_mv_v"), d.rated_output_mv_v)),
        full_scale_mm=max(0.0001, _as_float(raw.get("full_scale_mm"), d.full_scale_mm)),
        excitation_v=max(0.0001, _as_float(raw.get("excitation_v"), d.excitation_v)),
        calib_factor=_as_float(raw.get("calib_factor"), d.calib_factor),
        zero_offset_mv=_as_float(raw.get("zero_offset_mv"), d.zero_offset_mv),
        resolution_mm_per_pulse=max(0.000001, _as_float(raw.get("resolution_mm_per_pulse"), d.resolution_mm_per_pulse)),
        direction_invert=_as_bool(raw.get("direction_invert"), d.direction_invert),
        zero_offset_pulse=_as_float(raw.get("zero_offset_pulse"), d.zero_offset_pulse),
    )


class PreferencesManager:
    """환경 설정 로드/저장 관리자 (preferences.json)"""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, "preferences.json")
        self.config_path = config_path
        self.data = AppPreferences()
        self.load()

    def load(self) -> AppPreferences:
        """설정 파일 로드 (없거나 손상되면 기본값 유지)"""
        if not os.path.exists(self.config_path):
            return self.data
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self.data = AppPreferences.from_dict(raw)
        except Exception as e:
            print(f"[PreferencesManager] 환경 설정 로드 실패 (기본값 사용): {e}")
            self.data = AppPreferences()
        return self.data

    def save(self) -> bool:
        """현재 설정을 JSON으로 영구 저장"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data.to_dict(), f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[PreferencesManager] 환경 설정 저장 실패: {e}")
            return False

    def reset(self) -> bool:
        """기본값으로 복원 후 저장"""
        self.data = AppPreferences()
        return self.save()

    @property
    def ext(self) -> ExtensometerSettings:
        return self.data.ext
