"""
Salt Sw ver.1 - 환경 설정 탭 / 신율계 UI 동작 검증 (offscreen PyQt6)

실행: python3 -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from PyQt6.QtWidgets import QApplication, QMessageBox

from core.models import ExtensometerSettings
from ui.main_window import MainWindow


_app = QApplication.instance() or QApplication(sys.argv)


class TestPreferencesTabUI(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.win = MainWindow()
        self.win.prefs.config_path = os.path.join(self.tmpdir.name, "preferences.json")
        self.win.prefs.data.ext = ExtensometerSettings()
        self.win._sync_pref_widgets_from_model()
        self.win._apply_pref_group_state()
        self.win._refresh_pref_state()
        self.win._update_ext_tile_visibility()
        self.win.show()
        self.win.tabs.setCurrentIndex(2)
        _app.processEvents()

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        _app.processEvents()
        self.tmpdir.cleanup()

    def test_preferences_tab_exists(self):
        titles = [self.win.tabs.tabText(i) for i in range(self.win.tabs.count())]
        self.assertIn("환경 설정", titles)
        self.assertEqual(len(titles), 3)

    def test_default_state_is_off(self):
        self.assertTrue(self.win.rb_ext_off.isChecked())
        self.assertTrue(self.win.box_mv_params.isHidden())
        self.assertTrue(self.win.box_pulse_params.isHidden())
        self.assertTrue(self.win.tile_ext.isHidden())
        self.assertIn("크로스헤드", self.win.lbl_tile_strain.text())

    def test_enable_mv_saves_and_updates_dashboard(self):
        self.win.rb_ext_on.setChecked(True)
        self.win.combo_ext_type.setCurrentIndex(0)
        self.win.spin_rated.setValue(2.0)
        self.win.spin_ext_fs.setValue(25.0)
        self.win.spin_ext_exc.setValue(5.0)
        self.win.spin_ext_gl.setValue(50.0)
        self.assertTrue(self.win._save_preferences(silent=True))

        with open(self.win.prefs.config_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertTrue(saved["extensometer"]["enabled"])
        self.assertEqual(saved["extensometer"]["ext_type"], "MV")

        self.assertFalse(self.win.box_mv_params.isHidden())
        self.assertTrue(self.win.box_pulse_params.isHidden())
        self.assertFalse(self.win.tile_ext.isHidden())
        self.assertIn("신율계", self.win.lbl_tile_strain.text())
        self.assertIn("신율계", self.win.lbl_strain_source.text())

    def test_switch_to_pulse_shows_pulse_settings(self):
        self.win.rb_ext_on.setChecked(True)
        self.win.combo_ext_type.setCurrentIndex(1)
        _app.processEvents()
        self.assertTrue(self.win.box_mv_params.isHidden())
        self.assertFalse(self.win.box_pulse_params.isHidden())
        self.assertIn("mm/pulse", self.win.lbl_pref_hint.text())

    def test_dirty_indicator(self):
        self.win.rb_ext_on.setChecked(True)
        _app.processEvents()
        self.assertFalse(self.win.lbl_pref_dirty.isHidden())
        self.win._save_preferences(silent=True)
        _app.processEvents()
        self.assertTrue(self.win.lbl_pref_dirty.isHidden())

    def test_restore_defaults(self):
        self.win.rb_ext_on.setChecked(True)
        self.win._save_preferences(silent=True)
        self.assertTrue(self.win.prefs.ext.enabled)
        self.win._restore_pref_defaults(silent=True)
        self.assertFalse(self.win.prefs.ext.enabled)
        self.assertTrue(self.win.rb_ext_off.isChecked())
        self.assertTrue(self.win.tile_ext.isHidden())

    def test_language_switch(self):
        self.win.tabs.setCurrentIndex(2)
        self.win._toggle_language()
        _app.processEvents()
        self.assertEqual(self.win.tabs.tabText(2), "Preferences")
        self.assertEqual(self.win.pref_ext_group.title(), "Extensometer Setup")
        self.assertEqual(self.win.btn_pref_save.text(), "Save and Apply")
        self.assertNotIn("&", self.win.tabs.tabText(0))
        self.win._toggle_language()
        self.assertEqual(self.win.tabs.tabText(2), "환경 설정")

    def test_run_test_with_extensometer(self):
        self.win.rb_ext_on.setChecked(True)
        self.win.combo_ext_type.setCurrentIndex(0)
        self.assertTrue(self.win._save_preferences(silent=True))

        self.win.spin_speed.setValue(300.0)   # 시연용 고속 시험
        with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
             patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
            self.win._start_test()
            deadline = time.time() + 40
            while self.win.current_result is None and time.time() < deadline:
                _app.processEvents()
                time.sleep(0.02)

        self.assertIsNotNone(self.win.current_result, "시험이 완료되지 않았습니다")
        result = self.win.current_result
        self.assertTrue(result.ext_enabled)
        self.assertEqual(result.strain_source, "Extensometer (mV)")
        self.assertGreater(result.total_samples, 20)
        # 화면 표시 확인
        self.assertFalse(self.win.tile_ext.isHidden())
        self.assertNotEqual(self.win.lbl_ext_val.text(), "0.000")
        self.assertNotEqual(self.win.table_results.item(0, 0).text(), "-")
        self.assertIn("신율계", self.win.lbl_strain_source.text())
        self.win._reset_data()
        _app.processEvents()
        self.assertEqual(self.win.lbl_ext_val.text(), "0.000")


if __name__ == "__main__":
    unittest.main(verbosity=2)
