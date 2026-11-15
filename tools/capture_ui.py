"""
Salt Sw ver.1 - UI 검증 스크린샷 생성 (PyQt6 offscreen 렌더링)

실행:
    QT_QPA_PLATFORM=offscreen python3 tools/capture_ui.py

생성 위치: docs/screenshots/
- 환경 설정 탭(신율계 사용 안 함 / mV / 펄스), 한글·영문
- 신율계를 사용한 실시간 시험 화면과 시험 완료 화면
"""

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

from core.models import ExtensometerSettings, Specimen, SpecimenType, TestConfig, TestMode
from core.simulator import VirtualUTMSimulator
from core.calculator import MaterialCalculator
from ui.main_window import MainWindow

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


def save(window, name: str):
    # 레이아웃(스크롤 영역 내용 높이) 이 안정된 뒤 캡처
    for _ in range(4):
        QApplication.processEvents()
        window.repaint()
    path = os.path.join(OUT_DIR, name)
    window.grab().save(path)
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
    window._clear_results_table()
    window.btn_start.setEnabled(False)
    window.btn_stop.setEnabled(True)
    window._apply_strain_source_label(source_key)
    show_test_data(window, points)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    app = QApplication(sys.argv)
    app.setFont(QFont("Noto Sans CJK KR", 10))

    window = MainWindow()
    # 실제 프로그램의 환경 설정 파일을 건드리지 않도록 임시 경로 사용
    tmpdir = tempfile.TemporaryDirectory()
    window.prefs.config_path = os.path.join(tmpdir.name, "preferences.json")
    window.prefs.data.ext = ExtensometerSettings()  # 기본 상태에서 시작
    window._sync_pref_widgets_from_model()
    window._apply_pref_group_state()
    window._refresh_pref_state()
    window._update_ext_tile_visibility()

    window.resize(1360, 900)
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
    specimen, config, points, reason = run_simulation(window.prefs.ext)
    mid = max(10, int(len(points) * 0.45))
    window.tabs.setCurrentIndex(0)
    show_live(window, points[:mid], "src_mv")
    save(window, "04_dashboard_ext_mv_live_ko.png")

    # 5) 시험 완료 화면 (결과표 + 측정 소스)
    window.data_points = list(points[:-1])
    window._on_data_received(points[-1])
    window.current_result = MaterialCalculator.calculate(specimen, config, points, reason)
    window._update_results_table(window.current_result, reason)
    window._replot_graph()
    window._apply_strain_source_label("src_mv")
    window.btn_excel.setEnabled(True)
    window.btn_pdf.setEnabled(True)
    save(window, "05_dashboard_ext_mv_result_ko.png")

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
    window.resize(1360, 900)
    window.tabs.setCurrentIndex(0)
    show_live(window, points[:mid], "src_pulse")
    save(window, "09_dashboard_ext_pulse_live_ko.png")

    tmpdir.cleanup()
    print("done")


if __name__ == "__main__":
    main()
