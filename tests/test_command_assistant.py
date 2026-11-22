"""
Salt Sw ver.1 - 빠른 시험 어시스턴트 검증

1) 명령 해석 (core/command_assistant.py) - 한국어/영문, 누락 치수 감지, 제어 방식·PID·자동 저장
2) 자동 출력 (core/auto_export.py) - 파일 이름 규칙과 실제 Excel/PDF 생성
3) 화면 연동 (ui/main_window.py) - 카드 표시 → 치수 확인 → 시험 시작 → 자동 저장 → 완료 카드

실행: python3 -m unittest tests.test_command_assistant -v
"""

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from core.auto_export import build_report_paths, export_auto_reports, safe_token
from core.command_assistant import (
    CommandAssistant, material_label, parse_command, recommended_speed,
)
from core.history import TestHistoryStore
from core.i18n import TRANSLATIONS
from core.models import (
    BendingType, DataPoint, ExtensometerSettings, HoldingType, Specimen, SpecimenType,
    TestConfig, TestMode, TestResult,
)
from core.pid_controller import ControlMode


def fake_result() -> TestResult:
    return TestResult(
        test_mode=TestMode.TENSILE, specimen_id="SALT-SP-900", material="SS400",
        area_mm2=40.0, gauge_length_mm=50.0, peak_load_n=18000.0,
        peak_stress_mpa=450.0, yield_stress_mpa=288.0, elastic_modulus_gpa=205.0,
        elongation_pct=24.0, break_load_n=12000.0, break_displacement_mm=12.0,
        energy_joule=90.0, total_time_s=144.0, total_samples=40, is_fractured=True,
    )


def fake_points(count: int = 40):
    return [
        DataPoint(time_s=i * 0.5, displacement_mm=i * 0.3, load_n=450.0 * i,
                  stress_mpa=11.25 * i, strain_pct=i * 0.6)
        for i in range(count)
    ]


# ======================================================================
# 1) 명령 해석
# ======================================================================
class TestCommandParsing(unittest.TestCase):
    def test_sparse_command_keeps_dimensions_open(self):
        plan = parse_command("인장시험으로 시험해줘")
        self.assertIs(plan.mode, TestMode.TENSILE)
        self.assertEqual(plan.material_code, "SS400")
        self.assertGreater(plan.test_speed_mm_min, 0)
        self.assertFalse(plan.is_complete)
        for field in ("width", "thickness", "gauge_length"):
            self.assertIn(field, plan.missing_fields)
        self.assertIsNone(plan.width_mm)
        # 기본값을 임의로 채우지 않는다 (작업자가 확인해야 한다)
        self.assertIn("asst_note_mat_default", [note["key"] for note in plan.notes])

    def test_detailed_korean_command_fills_all_dimensions(self):
        plan = parse_command("SUS304 판재 12.5x3.2 표점 50 인장 5mm/min")
        self.assertIs(plan.mode, TestMode.TENSILE)
        self.assertEqual(plan.material_code, "SUS304")
        self.assertIs(plan.specimen_type, SpecimenType.FLAT)
        self.assertAlmostEqual(plan.width_mm, 12.5)
        self.assertAlmostEqual(plan.thickness_mm, 3.2)
        self.assertAlmostEqual(plan.gauge_length_mm, 50.0)
        self.assertAlmostEqual(plan.test_speed_mm_min, 5.0)
        self.assertEqual(plan.control_mode, ControlMode.DISP.value)
        self.assertEqual(plan.missing_fields, [])
        self.assertTrue(plan.is_complete)

    def test_english_command(self):
        plan = parse_command("SUS304 flat 12.5x3.2 gauge 50 tensile 5mm/min", "EN")
        self.assertIs(plan.mode, TestMode.TENSILE)
        self.assertAlmostEqual(plan.width_mm, 12.5)
        self.assertAlmostEqual(plan.thickness_mm, 3.2)
        self.assertAlmostEqual(plan.gauge_length_mm, 50.0)
        self.assertEqual(plan.missing_fields, [])

    def test_round_specimen_diameter(self):
        plan = parse_command("NBR 봉재 직경 10 압축 50mm/min")
        self.assertIs(plan.mode, TestMode.COMPRESSION)
        self.assertIs(plan.specimen_type, SpecimenType.ROUND)
        self.assertAlmostEqual(plan.diameter_mm, 10.0)
        self.assertIn("gauge_length", plan.missing_fields)
        self.assertNotIn("width", plan.missing_fields)

    def test_bending_type_and_span(self):
        plan = parse_command("AL6061 판재 12.5x3.2 표점 50 4점 굽힘 지간 100 2mm/min")
        self.assertIs(plan.mode, TestMode.BENDING)
        self.assertIs(plan.bending_type, BendingType.FOUR_POINT)
        self.assertAlmostEqual(plan.span_length_mm, 100.0)
        self.assertNotIn("span_length", plan.missing_fields)

        sparse = parse_command("3점 굽힘으로 해줘")
        self.assertIs(sparse.mode, TestMode.BENDING)
        self.assertIs(sparse.bending_type, BendingType.THREE_POINT)
        self.assertIn("span_length", sparse.missing_fields)

    def test_load_rate_control(self):
        plan = parse_command("SUS304 판재 12.5x3.2 표점 50 인장 하중 속도 6000 N/min")
        self.assertEqual(plan.control_mode, ControlMode.LOAD_RATE.value)
        self.assertAlmostEqual(plan.target_rate, 6000.0)

    def test_stress_rate_control(self):
        plan = parse_command("SUS304 판재 12.5x3.2 표점 50 인장 응력 속도 10 MPa/s")
        self.assertEqual(plan.control_mode, ControlMode.STRESS_RATE.value)
        self.assertAlmostEqual(plan.target_rate, 10.0)

    def test_load_hold_target_and_duration(self):
        plan = parse_command("SUS304 판재 12.5x3.2 표점 50 하중 유지 1000N 60초")
        self.assertIs(plan.mode, TestMode.HOLDING)
        self.assertIs(plan.holding_type, HoldingType.LOAD_HOLD)
        self.assertEqual(plan.control_mode, ControlMode.LOAD_HOLD.value)
        self.assertAlmostEqual(plan.target_holding_val, 1000.0)
        self.assertAlmostEqual(plan.holding_duration_s, 60.0)

    def test_disp_hold_keeps_displacement_control(self):
        plan = parse_command("SS400 판재 12.5x3.2 표점 50 변위 유지 120초")
        self.assertIs(plan.mode, TestMode.HOLDING)
        self.assertIs(plan.holding_type, HoldingType.DISP_HOLD)
        self.assertEqual(plan.control_mode, ControlMode.DISP.value)
        self.assertAlmostEqual(plan.holding_duration_s, 120.0)

    def test_auto_export_switch(self):
        self.assertTrue(parse_command("SUS304 판재 12.5x3.2 표점 50 인장").auto_export)
        self.assertFalse(parse_command("SUS304 판재 12.5x3.2 표점 50 인장 저장하지 마").auto_export)

    def test_pid_profile_follows_material(self):
        self.assertEqual(parse_command("로봇팔 인장 하중 속도 6000 N/min SS400").pid_profile_id, "metal")
        self.assertEqual(parse_command("ABS 판재 12.5x3.2 표점 50 인장").pid_profile_id, "film")
        self.assertEqual(parse_command("NBR 판재 10x2 표점 20 인장").pid_profile_id, "elastomer")
        explicit = parse_command("SUS304 판재 12.5x3.2 표점 50 인장 5mm/min PID 1")
        self.assertEqual(explicit.pid_profile_id, "elastomer")

    def test_unknown_mode_defaults_to_tensile_with_note(self):
        plan = parse_command("SUS304 판재 12.5x3.2 표점 50 5mm/min")
        self.assertIs(plan.mode, TestMode.TENSILE)
        self.assertIn("asst_note_mode_default", [note["key"] for note in plan.notes])

    def test_tube_input_is_reported_as_unsupported(self):
        plan = parse_command("인장 관형 20x2")
        self.assertIs(plan.specimen_type, SpecimenType.FLAT)
        self.assertIn("asst_note_shape_tube", [note["key"] for note in plan.notes])

    def test_recommended_speed_by_material_family(self):
        self.assertLess(recommended_speed(TestMode.TENSILE, "SS400"),
                        recommended_speed(TestMode.TENSILE, "ABS"))
        self.assertLess(recommended_speed(TestMode.TENSILE, "ABS"),
                        recommended_speed(TestMode.TENSILE, "NBR"))

    def test_notes_are_localized(self):
        plan = CommandAssistant.parse("인장시험으로 시험해줘", "KO")
        self.assertTrue(plan.note_texts("KO"))
        self.assertTrue(plan.note_texts("EN"))
        self.assertNotEqual(plan.note_texts("KO")[0], plan.note_texts("EN")[0])
        self.assertEqual(material_label("SUS304", "EN"), "SUS304 Stainless Steel")


# ======================================================================
# 2) 자동 출력
# ======================================================================
class TestAutoExport(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _specimen(self):
        return Specimen(specimen_id="SALT-SP-001", material="SUS400",
                        specimen_type=SpecimenType.FLAT, width_mm=12.5,
                        thickness_mm=3.2, gauge_length_mm=50.0)

    def test_file_name_pattern_ko(self):
        specimen = self._specimen()
        config = TestConfig(mode=TestMode.TENSILE)
        excel, pdf = build_report_paths(specimen, config, "KO", self.tmpdir.name,
                                        when=datetime(2026, 11, 22, 14, 30, 5))
        self.assertTrue(excel.endswith("20261122_143005_인장_SALT-SP-001.xlsx"))
        self.assertTrue(pdf.endswith("20261122_143005_인장_SALT-SP-001.pdf"))

    def test_file_name_bending_and_english(self):
        specimen = self._specimen()
        config = TestConfig(mode=TestMode.BENDING, bending_type=BendingType.FOUR_POINT)
        excel, _ = build_report_paths(specimen, config, "KO", self.tmpdir.name,
                                      when=datetime(2026, 11, 22, 14, 30, 5))
        self.assertIn("_4점굽힘_", excel)
        excel_en, _ = build_report_paths(specimen, config, "EN", self.tmpdir.name,
                                         when=datetime(2026, 11, 22, 14, 30, 5))
        self.assertIn("_Bending-4P_", excel_en)

    def test_specimen_id_is_sanitized(self):
        self.assertEqual(safe_token("SP/001: A"), "SP001_A")
        self.assertEqual(safe_token("  "), "SPECIMEN")

    def test_export_creates_both_files(self):
        specimen = self._specimen()
        config = TestConfig(mode=TestMode.TENSILE, test_speed_mm_min=5.0)
        paths = export_auto_reports(specimen, config, fake_result(), fake_points(),
                                    lang="KO", out_dir=self.tmpdir.name,
                                    when=datetime(2026, 11, 22, 14, 30, 5))
        self.assertTrue(os.path.exists(paths["excel"]))
        self.assertTrue(os.path.exists(paths["pdf"]))
        self.assertGreater(os.path.getsize(paths["excel"]), 1000)
        self.assertGreater(os.path.getsize(paths["pdf"]), 1000)
        with open(paths["pdf"], "rb") as handle:
            self.assertEqual(handle.read(4), b"%PDF")

        import openpyxl
        workbook = openpyxl.load_workbook(paths["excel"])
        self.assertIn("시험 성적 요약", workbook.sheetnames)


# ======================================================================
# 3) 화면 연동 (시편 세팅 카드 → 시험 → 자동 저장)
# ======================================================================
try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from ui.main_window import MainWindow
    HAS_QT = True
except Exception:  # pragma: no cover - Qt 가 없는 환경
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PyQt6 가 없어 화면 테스트를 건너뜁니다")
class TestAssistantUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.win = MainWindow()
        self.win.prefs.config_path = os.path.join(self.tmpdir.name, "preferences.json")
        self.win.prefs.data.ext = ExtensometerSettings()
        self.win.history = TestHistoryStore(os.path.join(self.tmpdir.name, "history"))
        self.win.auto_report_dir = os.path.join(self.tmpdir.name, "auto_reports")
        self.win._sync_pref_widgets_from_model()
        self.win._apply_pref_group_state()
        self.win._refresh_pref_state()
        self.win._update_ext_tile_visibility()
        self.win.chk_auto_id.setChecked(False)
        self.win.show()
        self.win.tabs.setCurrentIndex(0)
        self.app.processEvents()

    def tearDown(self):
        # 정지 시 완료 신호가 큐에 남을 수 있으므로 대화상자를 막아 두고 이벤트를 비운다
        with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
             patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
            self.win.active_driver.stop_test()
            deadline = time.time() + 5.0
            while time.time() < deadline and self.win.active_driver.is_running:
                self.app.processEvents()
                time.sleep(0.01)
            for _ in range(6):
                self.app.processEvents()
                time.sleep(0.01)
            self.win.close()
            self.win.deleteLater()
            self.app.processEvents()
        self.tmpdir.cleanup()

    # ------------------------------------------------------------------
    def _open_card(self, text: str):
        self.win.asst_edit.setText(text)
        self.win._open_assistant_card()
        self.app.processEvents()

    def _wait_done(self, timeout: float = 60.0) -> bool:
        deadline = time.time() + timeout
        while self.win.assistant_panel.state != "done" and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        for _ in range(4):
            self.app.processEvents()
            time.sleep(0.01)
        return self.win.assistant_panel.state == "done"

    def test_sparse_command_opens_card_with_missing_dimensions(self):
        self._open_card("인장시험으로 시험해줘")
        panel = self.win.assistant_panel
        self.assertTrue(panel.isVisible())
        self.assertEqual(panel.state, "plan")
        self.assertEqual(set(panel.missing), {"width", "thickness", "gauge_length"})
        # 좌측 폼은 아직 바뀌지 않는다 (시작 버튼을 눌러야 반영)
        self.assertEqual(self.win.spin_thick.value(), 3.0)

    def test_start_is_blocked_until_dimensions_are_entered(self):
        self._open_card("인장시험으로 시험해줘")
        panel = self.win.assistant_panel
        panel.btn_start.click()
        self.app.processEvents()
        self.assertEqual(panel.state, "plan")
        self.assertFalse(self.win.active_driver.is_running)
        self.assertEqual(len(self.win.session), 0)
        self.assertTrue(panel.lbl_missing.isVisible())

    def test_full_flow_applies_plan_and_saves_reports(self):
        self._open_card("SS400 판재 12.5x3.2 표점 50 인장 20mm/min")
        panel = self.win.assistant_panel
        self.assertEqual(panel.missing, set())
        self.win.simulator.time_scale = 60.0

        with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
             patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
            panel.btn_start.click()
            self.app.processEvents()
            # 좌측 폼에 계획이 그대로 반영된다
            self.assertAlmostEqual(self.win.spin_width.value(), 12.5)
            self.assertAlmostEqual(self.win.spin_thick.value(), 3.2)
            self.assertAlmostEqual(self.win.spin_l0.value(), 50.0)
            self.assertAlmostEqual(self.win.spin_speed.value(), 20.0)
            self.assertTrue(self.win.active_driver.is_running)
            self.assertTrue(self._wait_done())

        self.assertEqual(panel.state, "done")
        self.assertIn("excel", panel.paths)
        self.assertIn("pdf", panel.paths)
        self.assertTrue(os.path.exists(panel.paths["excel"]))
        self.assertTrue(os.path.exists(panel.paths["pdf"]))
        self.assertIn("_인장_SALT-SP-001", panel.paths["excel"])
        self.assertGreater(os.path.getsize(panel.paths["pdf"]), 1000)
        # 결과와 세션, 이력도 정상 경로로 남는다
        self.assertEqual(len(self.win.session), 1)
        self.assertIsNotNone(self.win.current_result)
        self.assertGreater(self.win.current_result.peak_load_n, 1000.0)
        self.assertEqual(self.win.history.count(), 1)

    def test_manual_start_closes_card(self):
        self._open_card("SS400 판재 12.5x3.2 표점 50 인장 20mm/min")
        panel = self.win.assistant_panel
        self.win.simulator.time_scale = 200.0
        with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
             patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
            self.win._start_test()
            self.app.processEvents()
            self.assertEqual(panel.state, "idle")
            self.assertFalse(panel.isVisible())
            self.assertFalse(self.win._assistant_auto_export)
            self.win._stop_test()
            deadline = time.time() + 5.0
            while time.time() < deadline and self.win.active_driver.is_running:
                self.app.processEvents()
                time.sleep(0.01)
            for _ in range(6):
                self.app.processEvents()
                time.sleep(0.01)

    def test_language_switch_updates_card(self):
        self._open_card("SUS304 판재 12.5x3.2 표점 50 인장 5mm/min")
        panel = self.win.assistant_panel
        self.win._toggle_language()
        self.app.processEvents()
        self.assertEqual(panel.state, "plan")
        self.assertEqual(panel.lbl_title.text(), TRANSLATIONS["EN"]["asst_card_title"])
        self.assertEqual(panel.btn_start.text(), TRANSLATIONS["EN"]["asst_start"])
        self.assertEqual(panel._summary_values["material"].text(), "SUS304 Stainless Steel")
        self.assertTrue(self.win.asst_edit.placeholderText().startswith("e.g."))


if __name__ == "__main__":
    unittest.main(verbosity=2)
