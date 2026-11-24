"""
폴더별 저장 규칙 및 시험 후 저장 설정 테스트
"""

import json
import os
from datetime import datetime

from core.auto_export import build_report_paths, export_auto_reports, resolve_report_dir
from core.models import BendingType, DataPoint, Specimen, TestConfig, TestMode, TestResult
from core.preferences import PreferencesManager, SaveSettings


def _sample_data():
    spec = Specimen(specimen_id="SALT SP/01", material="SS400", width_mm=12.5, thickness_mm=3.2)
    cfg = TestConfig(mode=TestMode.TENSILE, test_speed_mm_min=5.0)
    pts = [
        DataPoint(time_s=0.0, displacement_mm=0.0, load_n=0.0, stress_mpa=0.0, strain_pct=0.0),
        DataPoint(time_s=1.0, displacement_mm=0.5, load_n=9000.0, stress_mpa=225.0, strain_pct=1.0),
        DataPoint(time_s=2.0, displacement_mm=1.0, load_n=18100.0, stress_mpa=452.5, strain_pct=2.0),
    ]
    res = TestResult(
        test_mode=cfg.mode,
        specimen_id=spec.specimen_id,
        material=spec.material,
        area_mm2=40.0,
        gauge_length_mm=50.0,
        peak_load_n=18100.0,
        peak_stress_mpa=452.5,
    )
    return spec, cfg, res, pts


def test_resolve_report_dir_all_rules(tmp_path):
    spec, cfg, _, _ = _sample_data()
    when = datetime(2026, 11, 24, 14, 30, 0)
    root = str(tmp_path)

    assert resolve_report_dir(root, cfg, spec, "flat", "KO", when) == root
    assert resolve_report_dir(root, cfg, spec, "date", "KO", when) == os.path.join(root, "2026-11-24")
    assert resolve_report_dir(root, cfg, spec, "mode", "KO", when) == os.path.join(root, "인장")
    assert resolve_report_dir(root, cfg, spec, "mode", "EN", when) == os.path.join(root, "Tensile")
    assert resolve_report_dir(root, cfg, spec, "specimen", "KO", when) == os.path.join(root, "SALT_SP01")
    assert resolve_report_dir(root, cfg, spec, "date_mode", "KO", when) == os.path.join(root, "2026-11-24", "인장")

    bend_cfg = TestConfig(mode=TestMode.BENDING, bending_type=BendingType.FOUR_POINT)
    assert resolve_report_dir(root, bend_cfg, spec, "mode", "KO", when) == os.path.join(root, "4점굽힘")


def test_export_auto_reports_selective_and_folder_rule(tmp_path):
    spec, cfg, res, pts = _sample_data()
    when = datetime(2026, 11, 24, 15, 0, 0)
    paths = export_auto_reports(
        spec, cfg, res, pts,
        lang="KO",
        out_dir=str(tmp_path),
        when=when,
        folder_rule="date_mode",
        export_excel=True,
        export_pdf=True,
    )
    assert os.path.isfile(paths["excel"])
    assert os.path.isfile(paths["pdf"])
    assert os.path.dirname(paths["excel"]) == os.path.join(str(tmp_path), "2026-11-24", "인장")

    only_excel = export_auto_reports(
        spec, cfg, res, pts,
        lang="EN",
        out_dir=str(tmp_path),
        when=when,
        folder_rule="specimen",
        export_excel=True,
        export_pdf=False,
    )
    assert "excel" in only_excel and "pdf" not in only_excel
    assert os.path.isfile(only_excel["excel"])


def test_preferences_save_settings_roundtrip_and_backward_compat(tmp_path):
    cfg_file = tmp_path / "preferences.json"
    # 구버전(v1) 포맷 호환 확인
    cfg_file.write_text(json.dumps({"version": 1, "extensometer": {"enabled": True}}), encoding="utf-8")
    mgr = PreferencesManager(str(cfg_file))
    assert mgr.data.ext.enabled is True
    assert mgr.data.save.folder_rule == "date"
    assert mgr.data.save.ask_after_test is True

    mgr.data.save = SaveSettings(
        base_dir=str(tmp_path / "exports"),
        folder_rule="date_mode",
        ask_after_test=False,
        last_dir=str(tmp_path / "last"),
    )
    assert mgr.save() is True

    mgr2 = PreferencesManager(str(cfg_file))
    assert mgr2.data.save.base_dir == str(tmp_path / "exports")
    assert mgr2.data.save.folder_rule == "date_mode"
    assert mgr2.data.save.ask_after_test is False
    assert mgr2.data.save.last_dir == str(tmp_path / "last")
