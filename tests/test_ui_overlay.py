"""
Salt Sw ver.1 - UI 연동 검증 (오버레이 세션 · 배치 통계 · 시험 이력 · 시퀀스 모드)

실행: python3 -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from core.history import TestHistoryStore
from core.models import ExtensometerSettings, TestMode
from core.session import SpecimenSession
from core.sequence import SequenceProgram, SequenceStep, StepAction
from core.models import DataPoint, Specimen, SpecimenType, TestConfig, TestResult
from ui.main_window import MainWindow


_app = QApplication.instance() or QApplication(sys.argv)


def fake_result(peak_load=18000.0, peak_stress=450.0) -> TestResult:
    return TestResult(
        test_mode=TestMode.TENSILE, specimen_id="SP", material="SS400",
        area_mm2=40.0, gauge_length_mm=50.0, peak_load_n=peak_load,
        peak_stress_mpa=peak_stress, yield_stress_mpa=288.0,
        elastic_modulus_gpa=205.0, elongation_pct=24.0,
    )


def fake_points(count: int = 12):
    return [
        DataPoint(time_s=i * 0.05, displacement_mm=i * 0.05, load_n=200.0 * i,
                  stress_mpa=5.0 * i, strain_pct=i * 0.5)
        for i in range(count)
    ]


def fake_specimen(specimen_id="SALT-SP-100") -> Specimen:
    return Specimen(specimen_id=specimen_id, material="SS400",
                    specimen_type=SpecimenType.FLAT, width_mm=12.5,
                    thickness_mm=3.2, gauge_length_mm=50.0)


class TestOverlayUI(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.win = MainWindow()
        self.win.prefs.config_path = os.path.join(self.tmpdir.name, "preferences.json")
        self.win.prefs.data.ext = ExtensometerSettings()
        self.win.history = TestHistoryStore(os.path.join(self.tmpdir.name, "history"))
        self.win._sync_pref_widgets_from_model()
        self.win._apply_pref_group_state()
        self.win._refresh_pref_state()
        self.win._update_ext_tile_visibility()
        self.win._refresh_session_table()
        self.win._update_history_button()
        self.win.show()
        self.win.tabs.setCurrentIndex(0)
        _app.processEvents()

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        _app.processEvents()
        self.tmpdir.cleanup()

    # ------------------------------------------------------------------
    def _run_window_test(self, specimen_id="SALT-SP-100", speed=300.0, timeout=60.0):
        before = len(self.win.session)
        self.win.edit_specimen_id.setText(specimen_id)
        self.win.spin_thick.setValue(3.2)
        self.win.spin_speed.setValue(speed)
        with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
             patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
            self.win._start_test()
            deadline = time.time() + timeout
            while len(self.win.session) <= before and time.time() < deadline:
                _app.processEvents()
                time.sleep(0.02)
            for _ in range(5):
                _app.processEvents()
        self.assertTrue(len(self.win.session) > before, "시험이 완료되지 않았습니다")

    def test_completed_test_enters_session_batch_and_history(self):
        self._run_window_test()
        self.assertEqual(len(self.win.session), 1)
        record = self.win.session.records[0]
        self.assertEqual(record.session_label, "SP-001")
        self.assertTrue(record.history_id)
        self.assertTrue(record.integrity_digest)
        self.assertEqual(record.visible, True)

        # 세션 표에 한 행이 표시된다
        self.assertEqual(self.win.table_session.rowCount(), 1)
        self.assertEqual(self.win.table_session.item(0, 1).text(), "SP-001")
        self.assertEqual(self.win.table_session.item(0, 0).checkState(), Qt.CheckState.Checked)

        # 배치 통계: 시편 1개 -> 표준편차 0
        header = self.win.table_batch.item(0, 0).text()
        self.assertIn("최대 하중", header)
        self.assertNotEqual(self.win.table_batch.item(0, 1).text(), "-")
        self.assertEqual(self.win.table_batch.item(0, 2).text(), "0.0")
        self.assertIn("시편 1개", self.win.batch_group.title())

        # 이력 저장 + 버튼 표시
        summaries = self.win.history.list()
        self.assertEqual(len(summaries), 1)
        self.assertTrue(self.win.history.verify(summaries[0].record_id).ok)
        self.assertIn("1", self.win.btn_history.text())

        # 시편 번호 자동 증가
        self.assertEqual(self.win.edit_specimen_id.text(), "SALT-SP-101")

    def test_visibility_checkbox_changes_statistics(self):
        for i, load in enumerate((18000.0, 17000.0, 19000.0)):
            self.win.session.add(fake_specimen(f"ID-{i}"), TestConfig(), fake_result(load), fake_points())
        self.win._refresh_session_table()
        self.win._replot_graph()
        self.assertEqual(self.win.session.statistics_for("peak_load_n").n, 3)
        self.assertEqual(len(self.win._overlay_items), 3)

        item = self.win.table_session.item(1, 0)
        item.setCheckState(Qt.CheckState.Unchecked)
        _app.processEvents()

        self.assertEqual(self.win.session.statistics_for("peak_load_n").n, 2)
        self.assertEqual(len(self.win._overlay_items), 2)
        self.assertIn("시편 2개", self.win.batch_group.title())

        self.win._set_all_session_visible(False)
        self.assertEqual(self.win.session.statistics_for("peak_load_n").n, 0)
        self.assertEqual(self.win.table_batch.item(0, 1).text(), "-")
        self.assertEqual(self.win.table_batch.item(0, 0).text(), "최대 하중 (N)")
        self.assertEqual(self.win.table_batch.item(0, 1).text(), "-")

    def test_clear_session_keeps_history_records(self):
        self._run_window_test()
        self.assertEqual(len(self.win.session), 1)
        self.assertEqual(self.win.history.count(), 1)
        self.win._clear_session()
        self.assertEqual(len(self.win.session), 0)
        self.assertEqual(self.win.history.count(), 1)
        self.assertEqual(self.win.table_session.rowCount(), 0)

    def test_load_history_record_into_overlay(self):
        self._run_window_test(specimen_id="SALT-SP-200")
        record_id = self.win.history.list()[0].record_id

        self.win._clear_session()
        ok, message = self.win._load_history_record(record_id)
        self.assertTrue(ok)
        self.assertIn(record_id, message)
        self.assertEqual(len(self.win.session), 1)
        self.assertEqual(self.win.session.records[0].history_id, record_id)
        self.assertGreater(len(self.win.session.records[0].points), 10)

        # 같은 이력을 다시 넣으면 중복으로 거부된다
        ok2, message2 = self.win._load_history_record(record_id)
        self.assertFalse(ok2)
        self.assertIn("이미", message2)

        # 이력에 없는 ID
        ok3, _ = self.win._load_history_record("no-such-record")
        self.assertFalse(ok3)

    def test_batch_export_writes_files(self):
        for i, load in enumerate((18000.0, 17100.0)):
            self.win.session.add(fake_specimen(f"ID-{i}"), TestConfig(), fake_result(load), fake_points())
        self.win._refresh_session_table()

        for kind, suffix in (("xlsx", ".xlsx"), ("pdf", ".pdf")):
            path = os.path.join(self.tmpdir.name, f"batch{suffix}")
            with patch.object(QFileDialog, "getSaveFileName", return_value=(path, "")), \
                 patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok):
                self.win._export_batch(kind)
            self.assertTrue(os.path.exists(path), f"{kind} 내보내기 실패")
            self.assertGreater(os.path.getsize(path), 2000)

    def test_overlay_survives_new_test_start(self):
        self.win.session.add(fake_specimen("ID-1"), TestConfig(), fake_result(), fake_points())
        self.win._refresh_session_table()
        self.win._replot_graph()
        self.assertEqual(len(self.win._overlay_items), 1)
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
            self.win._start_test()
            for _ in range(5):
                _app.processEvents()
                time.sleep(0.02)
            self.assertEqual(len(self.win._overlay_items), 1)   # 새 시험 시작 후에도 유지

    def test_reset_data_keeps_overlay(self):
        self.win.session.add(fake_specimen("ID-1"), TestConfig(), fake_result(), fake_points())
        self.win._refresh_session_table()
        self.win._replot_graph()
        self.win._reset_data()
        self.assertEqual(len(self.win.session), 1)
        self.assertEqual(len(self.win._overlay_items), 1)


class TestSequenceUI(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.win = MainWindow()
        self.win.prefs.config_path = os.path.join(self.tmpdir.name, "preferences.json")
        self.win.history = TestHistoryStore(os.path.join(self.tmpdir.name, "history"))
        self.win.show()
        self.win.tabs.setCurrentIndex(0)
        _app.processEvents()

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        _app.processEvents()
        self.tmpdir.cleanup()

    def test_sequence_mode_shows_panel_and_config(self):
        self.assertTrue(self.win.sequence_group.isHidden())
        self.win.rb_sequence.setChecked(True)
        _app.processEvents()
        self.assertFalse(self.win.sequence_group.isHidden())

        config = self.win._get_current_config()
        self.assertEqual(config.mode, TestMode.SEQUENCE)
        self.assertTrue(config.sequence.is_valid())
        self.assertEqual(len(config.sequence.steps), 4)
        # 프로그램은 복사본으로 전달된다 (UI 상태와 분리)
        config.sequence.steps[0].target = 1234.0
        self.assertNotEqual(self.win.sequence_program.steps[0].target, 1234.0)

    def test_sequence_list_reflects_program(self):
        program = SequenceProgram(name="테스트", steps=[
            SequenceStep(StepAction.RAMP_LOAD, target=500.0, speed_mm_min=5.0),
            SequenceStep(StepAction.HOLD, hold_s=10.0),
        ])
        self.win.sequence_program = program
        self.win._refresh_sequence_view()
        self.assertEqual(self.win.list_sequence.count(), 2)
        self.assertIn("목표 하중 가압", self.win.list_sequence.item(0).text())
        self.assertIn("테스트", self.win.lbl_seq_count.text())
        self.assertIn("2", self.win.lbl_seq_count.text())

    def test_invalid_sequence_blocks_test_start(self):
        self.win.rb_sequence.setChecked(True)
        self.win.sequence_program = SequenceProgram(name="빈 시퀀스", steps=[])
        self.win._refresh_sequence_view()
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok) as warn:
            self.win._start_test()
        self.assertTrue(warn.called)
        self.assertEqual(len(self.win.session), 0)

    def test_sequence_run_creates_record_with_steps(self):
        program = SequenceProgram(name="짧은 시퀀스", steps=[
            SequenceStep(StepAction.RAMP_LOAD, target=600.0, speed_mm_min=5.0),
            SequenceStep(StepAction.HOLD, hold_s=0.5),
            SequenceStep(StepAction.RAMP_TO_BREAK, speed_mm_min=300.0),
        ])
        self.win.sequence_program = program
        self.win.rb_sequence.setChecked(True)
        self.win.spin_speed.setValue(200.0)
        self.win.edit_specimen_id.setText("SEQ-UI-1")

        before = len(self.win.session)
        with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
             patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
            self.win._start_test()
            deadline = time.time() + 90
            while len(self.win.session) <= before and time.time() < deadline:
                _app.processEvents()
                time.sleep(0.02)
            for _ in range(5):
                _app.processEvents()

        self.assertEqual(len(self.win.session), 1)
        record = self.win.session.records[0]
        self.assertEqual(len(record.step_events), 3)
        self.assertEqual(record.result.test_mode, TestMode.SEQUENCE)
        self.assertEqual(record.result.sequence_name, "짧은 시퀀스")
        # 그래프에 단계 구분선이 그려진다
        self.assertGreaterEqual(len(self.win._step_markers), 3)

        # 이력에도 단계 기록이 저장된다
        summary = self.win.history.list()[0]
        self.assertEqual(summary.sequence_steps, 3)

    def test_language_switch_updates_new_panels(self):
        self.win.session.add(fake_specimen("ID-1"), TestConfig(), fake_result(), fake_points())
        self.win._refresh_session_table()
        self.win._toggle_language()
        _app.processEvents()

        self.assertEqual(self.win.batch_group.title().split(" · ")[0], "Batch Statistics (selected)")
        self.assertEqual(self.win.table_batch.horizontalHeaderItem(1).text(), "Mean")
        self.assertEqual(self.win.table_session.horizontalHeaderItem(1).text(), "Session")
        self.assertEqual(self.win.rb_sequence.text(), "Multi-step Sequence")
        self.assertEqual(self.win.table_batch.item(0, 0).text(), "Peak Load (N)")
        self.assertIn("History", self.win.btn_history.text())
        self.assertEqual(self.win.combo_type.itemText(0), "Flat (Rectangular)")

        self.win._toggle_language()
        _app.processEvents()
        self.assertEqual(self.win.table_batch.item(0, 0).text(), "최대 하중 (N)")
        self.assertEqual(self.win.combo_type.itemText(0), "판재 (납작한 시편)")

    def test_auto_increment_toggle(self):
        self.win.edit_specimen_id.setText("SALT-SP-009")
        self.win._next_specimen_id()
        self.assertEqual(self.win.edit_specimen_id.text(), "SALT-SP-010")
        self.win.edit_specimen_id.setText("SPECIMEN")
        self.win._next_specimen_id()
        self.assertEqual(self.win.edit_specimen_id.text(), "SPECIMEN-2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
