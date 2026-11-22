"""
Salt Sw ver.1 - 빠른 시험 어시스턴트 UI 검증 스크린샷 (PyQt6 offscreen 렌더링)

실행:
    QT_QPA_PLATFORM=offscreen python3 tools/capture_assistant.py

생성 위치: docs/screenshots/
- 19_assistant_step1_card_ko.png   : "인장시험으로 시험해줘" → 시편 세팅 확인 카드 (치수 미입력 강조)
- 20_assistant_step2_running_ko.png: 치수 입력 후 [시편 세팅 완료 · 시험 시작] → 실시간 시험 진행
- 21_assistant_step3_exported_ko.png: 시험 완료 + Excel/PDF 자동 저장 경로
- 22_assistant_step4_card_en.png   : 영문(EN) 카드

실제 앱과 같은 경로(명령 해석 → 카드 → _start_test → _on_test_completed → 자동 저장)로 진행한다.
시뮬레이터 시간 배속(time_scale)만 올려 촬영 시간을 줄인다.
"""

import os
import sys
import tempfile
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.history import TestHistoryStore
from core.i18n import TRANSLATIONS
from core.models import ExtensometerSettings
from ui.main_window import MainWindow

OUT_DIR = os.path.join(BASE_DIR, "docs", "screenshots")
AUTO_DIR = os.path.join(BASE_DIR, "output", "auto_reports")
TIME_SCALE = 30.0          # 5 mm/min 인장 시험을 촬영 시간 안에 끝내기 위한 배속
MID_TEST_SECONDS = 1.3     # 시험 중 화면을 잡는 시점 (실제 초)


def save(widget, name: str):
    for _ in range(6):
        QApplication.processEvents()
        widget.repaint()
    path = os.path.join(OUT_DIR, name)
    widget.grab().save(path)
    print(f"[saved] {path}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(AUTO_DIR, exist_ok=True)

    app = QApplication(sys.argv)
    app.setFont(QFont("Noto Sans CJK KR", 10))

    window = MainWindow()
    tmpdir = tempfile.TemporaryDirectory()
    # 실제 설정/이력 폴더를 건드리지 않는다. 자동 저장 폴더만 실제 경로를 써서 카드에 그대로 보인다.
    window.prefs.config_path = os.path.join(tmpdir.name, "preferences.json")
    window.prefs.data.ext = ExtensometerSettings()
    window.history = TestHistoryStore(os.path.join(tmpdir.name, "history"))
    window.auto_report_dir = AUTO_DIR
    window._sync_pref_widgets_from_model()
    window._apply_pref_group_state()
    window._refresh_pref_state()
    window._update_ext_tile_visibility()
    window._update_history_button()
    window.chk_auto_id.setChecked(False)   # 시편 번호가 촬영 중에 바뀌지 않도록

    window.resize(1360, 940)
    window.show()
    window.tabs.setCurrentIndex(0)
    app.processEvents()

    # 1) 명령 입력 → 시편 세팅 확인 카드 (치수 미입력 상태)
    window.asst_edit.setText(TRANSLATIONS["KO"]["asst_example_1"])
    window._open_assistant_card()
    app.processEvents()
    save(window, "19_assistant_step1_card_ko.png")

    # 2) 치수 입력 → [시편 세팅 완료 · 시험 시작] → 실시간 시험 진행
    panel = window.assistant_panel
    panel.spin_width.setValue(12.5)
    panel.spin_thickness.setValue(3.2)
    panel.spin_gauge_length.setValue(50.0)
    app.processEvents()

    window.simulator.time_scale = TIME_SCALE
    with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
         patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
        window._assistant_start()
        started = time.time()
        while time.time() - started < MID_TEST_SECONDS and panel.state == "running":
            app.processEvents()
            time.sleep(0.01)
        save(window, "20_assistant_step2_running_ko.png")

        # 3) 시험 완료 → 결과 계산 + 로우데이터/성적서 자동 저장
        deadline = time.time() + 120
        while panel.state != "done" and time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)
        for _ in range(6):
            app.processEvents()
            time.sleep(0.01)
    print(f"[auto] state={panel.state} paths={panel.paths}")
    save(window, "21_assistant_step3_exported_ko.png")

    # 4) 영문 카드
    window._toggle_language()
    window.asst_edit.setText(TRANSLATIONS["EN"]["asst_example_2"])
    window._open_assistant_card()
    app.processEvents()
    save(window, "22_assistant_step4_card_en.png")

    tmpdir.cleanup()
    print("done")


if __name__ == "__main__":
    main()
