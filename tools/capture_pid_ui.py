"""
Salt Sw ver.1 - 소프트 PID 제어 화면 캡처 (PyQt6 offscreen)

실행:
    QT_QPA_PLATFORM=offscreen python3 tools/capture_pid_ui.py

생성 위치: docs/screenshots/
- 17_pid_control_ko.png     : 하중 유지(PID 3 금속) 시험 완료 화면
- 17b_pid_control_en.png    : 같은 화면의 영문 UI
- 18_pid_group_ko.png       : 제어 방식 및 PID 설정 영역 확대
"""

import os
import sys
import tempfile
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QFont

from core.history import TestHistoryStore
from core.preferences import PreferencesManager
from ui.main_window import MainWindow

OUT_DIR = os.path.join(BASE_DIR, "docs", "screenshots")


def save(widget, name: str):
    for _ in range(6):
        QApplication.processEvents()
        widget.repaint()
    path = os.path.join(OUT_DIR, name)
    widget.grab().save(path)
    print(f"[saved] {path}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    app = QApplication(sys.argv)
    app.setFont(QFont("Noto Sans CJK KR", 10))

    window = MainWindow()
    tmpdir = tempfile.TemporaryDirectory()
    window.prefs = PreferencesManager(os.path.join(tmpdir.name, "preferences.json"))
    window.pid_manager.config_path = os.path.join(tmpdir.name, "pid_profiles.json")
    window.pid_manager.reset_defaults()
    window.simulator.pid_manager = window.pid_manager
    window.serial_driver.pid_manager = window.pid_manager
    window.history = TestHistoryStore(os.path.join(tmpdir.name, "history"))
    window._update_history_button()

    # 제어 설정 영역까지 한 화면에 담기도록 세로로 길게 캡처한다
    window.resize(1360, 1080)
    window.show()
    app.processEvents()

    # 시편 · 제어 조건 설정 (SS400 12.5 x 3.2, 2,000 N 까지 96 kN/min)
    window.edit_specimen_id.setText("SALT-SP-1122")
    window.edit_material.setText("SS400 (일반구조용강)")
    window.spin_width.setValue(12.5)
    window.spin_thick.setValue(3.2)
    window.spin_l0.setValue(50.0)
    window.spin_drop.setValue(50.0)
    window.chk_auto_id.setChecked(True)

    window.rb_holding.setChecked(True)
    window.combo_hold_type.setCurrentIndex(0)
    window.spin_hold_val.setValue(2000.0)
    window.spin_hold_dur.setValue(4.0)

    window.combo_control_mode.setCurrentIndex(3)          # 하중 유지
    window.spin_target_rate.setValue(96000.0)             # 1,600 N/s
    window.combo_pid_mode.setCurrentIndex(window.combo_pid_mode.findData("metal"))
    window.spin_ctl_delay.setValue(40.0)
    window.spin_ctl_hz.setValue(25.0)
    window.chk_live_speed.setChecked(True)

    # 실제 경로(시뮬레이터 -> 결과 -> 이력 -> 세션)로 시험 1회 수행
    window.simulator.time_scale = 6.0
    before = len(window.session)
    with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
         patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
        window._start_test()
        deadline = time.time() + 40
        while len(window.session) <= before and time.time() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)
        for _ in range(8):
            QApplication.processEvents()
            time.sleep(0.01)

    ok = len(window.session) > before
    print(f"[test] 하중 유지 시험 {'완료' if ok else '실패'} · 결과 "
          f"{window.current_result.peak_load_n:,.0f} N" if window.current_result else "결과 없음")

    window.tabs.setCurrentIndex(0)
    for _ in range(4):
        app.processEvents()
    for _ in range(4):
        app.processEvents()
    save(window, "17_pid_control_ko.png")
    save(window.ctl_group, "18_pid_group_ko.png")

    window._toggle_language()
    window._replot_graph()
    for _ in range(4):
        app.processEvents()
    save(window, "17b_pid_control_en.png")
    window._toggle_language()

    # 추종 성능 요약 (보고용)
    print(f"[summary] {window._last_tracking or '-'}")
    print(f"[status] {window.lbl_ctl_status.text()}")
    tmpdir.cleanup()
    print("done")


if __name__ == "__main__":
    main()
