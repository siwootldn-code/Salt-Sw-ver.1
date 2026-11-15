"""
Salt Sw ver.1 - UI 검증 스크린샷 생성 (PyQt6 offscreen 렌더링)

실행:
    QT_QPA_PLATFORM=offscreen python3 tools/capture_ui.py

생성 위치: docs/screenshots/
- 환경 설정 탭(신율계 사용 안 함 / mV / 펄스), 한글·영문
- 신율계를 사용한 실시간 시험 화면과 시험 완료 화면
- 다중 시편 오버레이 + 배치 통계 (한/영)
- 다단계 시퀀스 편집 창과 시퀀스 시험 완료 화면 (단계 표시)
- 시험 이력 다이얼로그 (무결성 검증)
- 최소 창 크기 레이아웃 확인
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

from core.models import ExtensometerSettings, Specimen, SpecimenType, TestConfig, TestMode
from core.simulator import VirtualUTMSimulator
from core.calculator import MaterialCalculator
from core.history import TestHistoryStore
from core.sequence import SequenceProgram, SequenceStep, StepAction
from ui.main_window import MainWindow
from ui.dialogs import SequenceDialog, HistoryDialog

OUT_DIR = os.path.join(BASE_DIR, "docs", "screenshots")


def run_simulation(ext: ExtensometerSettings, speed_mm_min: float = 300.0, sampling_hz: int = 300):
    specimen = Specimen(
        specimen_id="SALT-SP-0118",
        material="SS400 (일반구조용강)",
        specimen_type=SpecimenType.FLAT,
        width_mm=12.5,
        thickness_mm=3.2,
        gauge_length_mm=50.0,
    )
    config = TestConfig(
        mode=TestMode.TENSILE,
        test_speed_mm_min=speed_mm_min,
        fracture_drop_ratio=0.5,
        max_displacement_mm=40.0,
        sampling_rate_hz=sampling_hz,
        ext=ext,
    )
    sim = VirtualUTMSimulator()
    sim.connect()
    points = []
    state = {}
    sim.on_data_received = points.append
    sim.on_test_completed = lambda reason: state.setdefault("reason", reason)
    sim.start_test(specimen, config)
    deadline = time.time() + 90
    while "reason" not in state and time.time() < deadline:
        time.sleep(0.02)
    sim.stop_test()
    return specimen, config, points, state.get("reason", "")


def save(widget, name: str):
    # 레이아웃(스크롤 영역 내용 높이) 이 안정된 뒤 캡처
    for _ in range(5):
        QApplication.processEvents()
        widget.repaint()
    path = os.path.join(OUT_DIR, name)
    widget.grab().save(path)
    print(f"[saved] {path}")


def set_pref_ui(window, enabled: bool, ext_type: str = "mV"):
    """환경 설정 화면 상태 변경 (저장까지 실제 경로로 수행)"""
    window.rb_ext_on.setChecked(enabled)
    window.rb_ext_off.setChecked(not enabled)
    window.combo_ext_type.setCurrentIndex(0 if ext_type == "MV" else 1)
    if ext_type == "MV":
        window.spin_rated.setValue(2.0)
        window.spin_ext_fs.setValue(25.0)
        window.spin_ext_exc.setValue(5.0)
        window.spin_ext_cal.setValue(1.0)
        window.spin_ext_zero.setValue(0.0)
    else:
        window.spin_ext_res.setValue(0.001)
        window.chk_ext_invert.setChecked(False)
    window.spin_ext_gl.setValue(50.0)
    window._apply_pref_group_state()
    window._update_pref_hint()
    window._save_preferences(silent=True)


def show_test_data(window, points):
    """시험 데이터를 화면에 반영"""
    window.data_points = list(points[:-1])
    window._on_data_received(points[-1])
    window._replot_graph()


def show_live(window, points, source_key: str):
    """시험 진행 중 화면 상태로 표시 (결과표는 비우고 시작/정지 버튼을 진행 상태로)"""
    window.current_result = None
    window._live_record_seq = None
    window._clear_results_table()
    window.btn_start.setEnabled(False)
    window.btn_stop.setEnabled(True)
    window._apply_strain_source_label(source_key)
    show_test_data(window, points)


def run_window_test(window, specimen_id: str, thickness: float, speed: float = 300.0,
                    timeout: float = 60.0) -> bool:
    """메인 윈도우의 실제 경로(시뮬레이터 -> 결과 -> 이력 -> 세션)로 시험 1회 수행"""
    before = len(window.session)
    window.edit_specimen_id.setText(specimen_id)
    window.spin_thick.setValue(thickness)
    window.spin_speed.setValue(speed)
    with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
         patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
        window._start_test()
        deadline = time.time() + timeout
        while len(window.session) <= before and time.time() < deadline:
            QApplication.processEvents()
            time.sleep(0.02)
        # 완료 처리(결과표/세션/이력)까지 이벤트 루프 비우기
        for _ in range(6):
            QApplication.processEvents()
            time.sleep(0.01)
    return len(window.session) > before


def run_window_sequence(window, timeout: float = 90.0) -> bool:
    before = len(window.session)
    with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
         patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
        window._start_test()
        deadline = time.time() + timeout
        while len(window.session) <= before and time.time() < deadline:
            QApplication.processEvents()
            time.sleep(0.02)
        for _ in range(6):
            QApplication.processEvents()
            time.sleep(0.01)
    return len(window.session) > before


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    app = QApplication(sys.argv)
    app.setFont(QFont("Noto Sans CJK KR", 10))

    window = MainWindow()
    # 실제 프로그램의 환경 설정 / 이력 폴더를 건드리지 않도록 임시 경로 사용
    tmpdir = tempfile.TemporaryDirectory()
    window.prefs.config_path = os.path.join(tmpdir.name, "preferences.json")
    window.prefs.data.ext = ExtensometerSettings()  # 기본 상태에서 시작
    window.history = TestHistoryStore(os.path.join(tmpdir.name, "history"))
    window._update_history_button()
    window._sync_pref_widgets_from_model()
    window._apply_pref_group_state()
    window._refresh_pref_state()
    window._update_ext_tile_visibility()

    window.resize(1360, 940)
    window.show()
    app.processEvents()

    # 1) 신율계 미사용 - 대시보드
    window.tabs.setCurrentIndex(0)
    save(window, "01_dashboard_ext_off_ko.png")

    # 2) 환경 설정 탭 - 사용 안 함
    window.tabs.setCurrentIndex(2)
    save(window, "02_preferences_ext_off_ko.png")

    # 2-1) 기존 장비 탭 스타일 회귀 확인
    window.tabs.setCurrentIndex(1)
    save(window, "10_hardware_ko.png")
    window.tabs.setCurrentIndex(2)

    # 3) 환경 설정 탭 - mV 타입 사용
    set_pref_ui(window, True, "MV")
    window._refresh_pref_state()
    save(window, "03_preferences_ext_mv_ko.png")

    # 4) mV 신율계로 시험 중 화면 (중간 시점)
    #    화면의 시편 제원을 시뮬레이션 시편과 일치시켜 완료 결과가 어긋나지 않게 한다
    window.edit_specimen_id.setText("SALT-SP-0118")
    window.spin_width.setValue(12.5)
    window.spin_thick.setValue(3.2)
    window.spin_l0.setValue(50.0)
    window.spin_speed.setValue(300.0)
    window.chk_auto_id.setChecked(False)
    specimen, config, points, reason = run_simulation(window.prefs.ext)
    mid = max(10, int(len(points) * 0.45))
    window.tabs.setCurrentIndex(0)
    show_live(window, points[:mid], "src_mv")
    save(window, "04_dashboard_ext_mv_live_ko.png")

    # 5) 시험 완료 화면 (결과표 + 측정 소스) — 실제 완료 경로(이력 저장 · 세션 추가) 사용
    window.data_points = list(points[:-1])
    window._on_data_received(points[-1])
    with patch.object(QMessageBox, "information", return_value=QMessageBox.StandardButton.Ok), \
         patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok):
        window._on_test_completed(reason)
    for _ in range(4):
        app.processEvents()
    window._replot_graph()
    window.btn_excel.setEnabled(True)
    window.btn_pdf.setEnabled(True)
    save(window, "05_dashboard_ext_mv_result_ko.png")
    window.chk_auto_id.setChecked(True)

    # 6) 환경 설정 탭 - 펄스 타입, 영문 UI
    set_pref_ui(window, True, "PULSE")
    window._refresh_pref_state()
    window.tabs.setCurrentIndex(2)
    window._toggle_language()
    window._refresh_pref_state()
    save(window, "06_preferences_ext_pulse_en.png")

    # 7) 영문 환경 설정 - 사용 안 함
    window.rb_ext_off.setChecked(True)
    window._apply_pref_group_state()
    window._refresh_pref_state()
    save(window, "07_preferences_ext_off_en.png")

    # 8) 최소 창 크기에서 레이아웃 확인 (펄스 설정, 한글)
    window._toggle_language()
    window.rb_ext_on.setChecked(True)
    window.combo_ext_type.setCurrentIndex(1)
    window._apply_pref_group_state()
    window._refresh_pref_state()
    window.resize(1120, 740)
    app.processEvents()
    save(window, "08_preferences_pulse_min_size_ko.png")

    # 9) 펄스 신율계 실시간 화면
    specimen, config, points, reason = run_simulation(window.prefs.ext)
    mid = max(10, int(len(points) * 0.45))
    window.resize(1360, 940)
    window.tabs.setCurrentIndex(0)
    show_live(window, points[:mid], "src_pulse")
    save(window, "09_dashboard_ext_pulse_live_ko.png")

    # ==================================================================
    # 다중 시편 오버레이 + 배치 통계
    # ==================================================================
    window._reset_data()
    window.session.clear()
    window._refresh_session_table()
    set_pref_ui(window, False)
    window.rb_tensile.setChecked(True)
    window.chk_auto_id.setChecked(True)
    window.tabs.setCurrentIndex(0)

    batch = [("SALT-SP-001", 3.2), ("SALT-SP-002", 3.0), ("SALT-SP-003", 3.4)]
    for specimen_id, thickness in batch:
        ok = run_window_test(window, specimen_id, thickness, speed=300.0)
        print(f"[test] {specimen_id} thickness={thickness} -> {'ok' if ok else 'FAILED'}")

    window.edit_specimen_id.setText("SALT-SP-004")
    window._refresh_session_table()
    window._replot_graph()
    app.processEvents()
    save(window, "11_overlay_batch_stats_ko.png")

    # 11-1) 하중-변위 곡선 오버레이도 확인
    window.rb_graph_ld.setChecked(True)
    window._replot_graph()
    save(window, "11b_overlay_load_disp_ko.png")
    window.rb_graph_ss.setChecked(True)
    window._replot_graph()

    # 12) 영문 화면 - 오버레이 + 배치 통계
    window._toggle_language()
    window.tabs.setCurrentIndex(0)
    window._replot_graph()
    save(window, "12_overlay_batch_stats_en.png")
    window._toggle_language()
    window._replot_graph()

    # ==================================================================
    # 다단계 시퀀스
    # ==================================================================
    demo_program = SequenceProgram(name="인장 4단계 시퀀스", steps=[
        SequenceStep(StepAction.RAMP_LOAD, target=800.0, speed_mm_min=5.0),
        SequenceStep(StepAction.HOLD, hold_s=3.0),
        SequenceStep(StepAction.RAMP_TO_BREAK, speed_mm_min=240.0),
        SequenceStep(StepAction.RETURN, speed_mm_min=240.0),
    ])
    window.sequence_program = demo_program
    window._refresh_sequence_view()

    # 13) 시퀀스 편집 창 (한글)
    dialog = SequenceDialog(demo_program, "KO", window)
    dialog.show()
    for _ in range(4):
        app.processEvents()
    save(dialog, "13_sequence_dialog_ko.png")
    dialog.close()

    # 14) 시퀀스 시험 실행 (단계 표시가 그래프에 남는 완료 화면)
    window.rb_sequence.setChecked(True)
    window._on_test_mode_toggled(4, True)
    window.edit_specimen_id.setText("SALT-SP-004")
    window.spin_thick.setValue(3.2)
    ok = run_window_sequence(window)
    print(f"[test] sequence -> {'ok' if ok else 'FAILED'}")
    app.processEvents()
    save(window, "14_sequence_result_ko.png")

    # 14-1) 영문 시퀀스 화면
    window._toggle_language()
    window._replot_graph()
    save(window, "14b_sequence_result_en.png")
    window._toggle_language()
    window.rb_tensile.setChecked(True)

    # ==================================================================
    # 시험 이력 (자동 저장 + 무결성 검증)
    # ==================================================================
    history_dialog = HistoryDialog(window.history, "KO", load_callback=window._load_history_record, parent=window)
    history_dialog.show()
    for _ in range(4):
        app.processEvents()
    history_dialog._verify_chain()
    app.processEvents()
    save(history_dialog, "15_history_dialog_ko.png")
    history_dialog.close()

    history_en = HistoryDialog(window.history, "EN", load_callback=window._load_history_record, parent=window)
    history_en.show()
    for _ in range(4):
        app.processEvents()
    save(history_en, "15b_history_dialog_en.png")
    history_en.close()

    # ==================================================================
    # 최소 창 크기 레이아웃 확인 (오버레이 + 세션 + 통계가 겹치지 않는지)
    # ==================================================================
    window.edit_specimen_id.setText("SALT-SP-005")
    window.resize(1120, 740)
    app.processEvents()
    window._replot_graph()
    save(window, "16_overlay_min_size_ko.png")

    # 이력이 저장된 개수와 무결성 요약 출력
    summaries = window.history.list()
    chain = window.history.verify_chain()
    print(f"[history] {len(summaries)}건 저장 · 체인 검증 {chain.ok} ({chain.ok_count}/{chain.total})")

    tmpdir.cleanup()
    print("done")


if __name__ == "__main__":
    main()
