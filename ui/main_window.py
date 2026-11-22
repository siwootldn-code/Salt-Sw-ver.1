"""
Salt Sw ver.1 - Main Dashboard Window
만능재료시험기(UTM) 제어, 실시간 하중/변위/응력/변형률 모니터링 및 엑셀·PDF 출력 메인 윈도우
- 현장 작업자 최적화 직관적인 쉬운 한국어 기본 탑재 (불필요한 외래어 배제)
- 글로벌 수출 및 해외 바이어용 원클릭 영문(ASTM 표준) 전환 탑재
- Windows 11 High-DPI 무충돌 아키텍처
"""

import os
import re
from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QRect
from PyQt6.QtGui import QColor, QBrush, QFont
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QComboBox, QDoubleSpinBox,
    QPushButton, QRadioButton, QButtonGroup, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QFrame, QHeaderView,
    QTabWidget, QCheckBox, QScrollArea, QTextEdit, QSizePolicy,
    QListWidget, QListWidgetItem, QDialog
)

try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True

    class NumberAxis(pg.AxisItem):
        """천 단위 구분 기호가 있는 계측기용 축 표기 (15,000 / 0.15)"""

        def tickStrings(self, values, scale, spacing):
            labels = []
            for value in values:
                try:
                    if spacing >= 1 or abs(value) >= 1000:
                        labels.append(f"{value:,.0f}")
                    elif spacing >= 0.1:
                        labels.append(f"{value:,.1f}")
                    else:
                        labels.append(f"{value:,.2f}")
                except (TypeError, ValueError):
                    labels.append(str(value))
            return labels

except ImportError:
    HAS_PYQTGRAPH = False
    NumberAxis = None

from core.models import (
    Specimen, SpecimenType, TestConfig, TestMode, BendingType, HoldingType,
    DataPoint, TestResult, ExtensometerSettings, ExtensometerType
)
from core.simulator import VirtualUTMSimulator
from core.serial_driver import SerialUTMDriver
from core.hardware_interface import HardwareInterface
from core.calculator import MaterialCalculator
from core.preferences import PreferencesManager
from core.pid_controller import (
    ControlMode, PIDProfileManager, evaluate_tracking
)
from core.i18n import TRANSLATIONS, tr, step_action_label, metric_label
from core.session import BATCH_METRICS, SpecimenSession
from core.history import TestHistoryStore
from core.sequence import SequenceProgram, StepAction
from core.command_assistant import CommandAssistant, TestCommandPlan, material_label
from core.auto_export import AUTO_REPORT_DIR, display_path, export_auto_reports
from exporters.excel_exporter import ExcelExporter
from exporters.pdf_exporter import PDFExporter
from ui.styles import HYUNDAI_THEME_QSS
from ui.dialogs import SequenceDialog, HistoryDialog, mode_display
from ui.assistant_panel import TestAssistantPanel


class CommunicateBridge(QObject):
    """스레드 안전한 실시간 데이터 전송 브리지"""
    data_received = pyqtSignal(DataPoint)
    test_completed = pyqtSignal(str)
    raw_data_received = pyqtSignal(str)


class MainWindow(QMainWindow):
    """Salt Sw ver.1 메인 애플리케이션 윈도우"""

    RESULT_COLUMNS = [
        ("최대 하중 (Pmax, N)", "최대하중"),
        ("인장/압축강도 (Rm, MPa)", "강도"),
        ("항복강도 (Rp0.2, MPa)", "항복강도"),
        ("탄성계수 (E, GPa)", "탄성계수"),
        ("파단 연신율 (A, %)", "연신율"),
        ("파단 변위 (dL, mm)", "파단변위"),
        ("흡수에너지 (U, J)", "흡수에너지"),
        ("시험 상태", "상태")
    ]

    def __init__(self):
        super().__init__()
        self.current_lang = "KO"  # 기본값: 현장 친화 쉬운 한국어
        self.setWindowTitle("SALT SW VER.1 — 만능재료시험기 제어 시스템")
        self.resize(1360, 940)
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(HYUNDAI_THEME_QSS)

        # 데이터 저장소 및 하드웨어
        self.data_points: List[DataPoint] = []
        self.current_result: Optional[TestResult] = None
        self.prefs = PreferencesManager()
        self.pid_manager = PIDProfileManager()
        self.session = SpecimenSession()
        self.history = TestHistoryStore()
        self.sequence_program: SequenceProgram = SequenceProgram.standard()
        self._overlay_items: List[object] = []
        self._step_markers: List[object] = []
        self._live_record_seq: Optional[int] = None
        self._last_completion_reason: str = ""
        self._last_tracking: str = ""
        self.simulator = VirtualUTMSimulator()
        self.serial_driver = SerialUTMDriver()
        # 빠른 시험 어시스턴트가 자동 저장하는 폴더 (시험 완료 시 Excel + PDF)
        self.auto_report_dir = AUTO_REPORT_DIR
        self._assistant_auto_export = False
        self._active_specimen: Optional[Specimen] = None
        # PID 게인은 한 곳에서 관리한다 (화면에서 저장하면 가상·실장비 모두 반영)
        self.simulator.pid_manager = self.pid_manager
        self.serial_driver.pid_manager = self.pid_manager
        self.serial_driver.set_extensometer(self.prefs.ext)
        self.simulator.set_extensometer(self.prefs.ext)
        self.active_driver: HardwareInterface = self.simulator

        # 통신 브리지 바인딩
        self.bridge = CommunicateBridge()
        self.bridge.data_received.connect(self._on_data_received)
        self.bridge.test_completed.connect(self._on_test_completed)
        self.bridge.raw_data_received.connect(self._on_raw_packet_received)

        self.simulator.on_data_received = lambda p: self.bridge.data_received.emit(p)
        self.simulator.on_test_completed = lambda reason: self.bridge.test_completed.emit(reason)
        self.serial_driver.on_data_received = lambda p: self.bridge.data_received.emit(p)
        self.serial_driver.on_test_completed = lambda reason: self.bridge.test_completed.emit(reason)
        self.serial_driver.on_raw_data_received = lambda raw: self.bridge.raw_data_received.emit(raw)

        # 제어 상태 표시 갱신 타이머 (시험 중 0.25초 간격)
        self.ctl_timer = QTimer(self)
        self.ctl_timer.setInterval(250)
        self.ctl_timer.timeout.connect(self._refresh_control_status)

        self._init_ui()
        self._apply_language(self.current_lang)

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        root_layout = QVBoxLayout(main_widget)
        root_layout.setContentsMargins(12, 10, 12, 10)
        root_layout.setSpacing(8)

        # 1. 상단 글로벌 네비게이션 헤더 (원클릭 한/영 언어 전환 바)
        top_bar = QWidget()
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(4, 2, 4, 4)

        lbl_logo = QLabel("SALT SW VER.1")
        lbl_logo.setStyleSheet("font-size: 14pt; font-weight: 800; color: #1D4ED8; letter-spacing: 0.5px;")
        self.lbl_app_sub = QLabel("만능재료시험기 통합 제어 프로그램")
        self.lbl_app_sub.setStyleSheet("font-size: 9pt; color: #64748B; margin-left: 8px;")

        top_layout.addWidget(lbl_logo)
        top_layout.addWidget(self.lbl_app_sub)
        top_layout.addStretch()

        # 시험 이력 버튼 (자동 저장된 이력 열람 · 무결성 검증)
        self.btn_history = QPushButton("시험 이력 (0)")
        self.btn_history.setFixedWidth(150)
        self.btn_history.setStyleSheet(
            "background-color: #FFFFFF; border: 1px solid #CBD5E1; font-weight: 700; "
            "padding: 4px 10px; border-radius: 4px;"
        )
        self.btn_history.clicked.connect(self._open_history)
        top_layout.addWidget(self.btn_history)

        # 언어 전환 토글 버튼
        self.btn_lang = QPushButton("🌐 English")
        self.btn_lang.setFixedWidth(110)
        self.btn_lang.setStyleSheet("background-color: #FFFFFF; border: 1px solid #CBD5E1; font-weight: 700; padding: 4px 10px; border-radius: 4px;")
        self.btn_lang.clicked.connect(self._toggle_language)
        top_layout.addWidget(self.btn_lang)

        root_layout.addWidget(top_bar)

        # 2. 상단 탭 위젯 생성
        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)

        # 탭 1: 메인 시험 진행 및 모니터링 대시보드
        tab_dashboard = self._create_dashboard_tab()
        self.tabs.addTab(tab_dashboard, "시험 및 실시간 모니터링")

        # 탭 2: 계측 장비 연동 및 통신 설정
        tab_hardware = self._create_hardware_tab()
        self.tabs.addTab(tab_hardware, "장비 연결 및 정밀 교정")

        # 탭 3: 환경 설정 (신율계 등 계측 옵션)
        tab_prefs = self._create_preferences_tab()
        self.tabs.addTab(tab_prefs, "환경 설정")

        # 상태 바
        self.statusBar().showMessage("장비 상태: 대기 중 | 가상 시뮬레이터 동작 중")

    def _toggle_language(self):
        """원클릭 한/영 다국어 전환"""
        self.current_lang = "EN" if self.current_lang == "KO" else "KO"
        self._apply_language(self.current_lang)

    def _apply_language(self, lang: str):
        """UI 전체 위젯 텍스트 다국어 갱신"""
        t = TRANSLATIONS[lang]
        self.setWindowTitle(t["app_title"])
        self.lbl_app_sub.setText(t["brand_sub"])
        self.btn_lang.setText("🌐 한국어" if lang == "EN" else "🌐 English")

        # Tabs
        self.tabs.setTabText(0, t["tab_dashboard"])
        self.tabs.setTabText(1, t["tab_hardware"])
        self.tabs.setTabText(2, t["tab_preferences"])

        # Mode
        self.group_mode.setTitle(t["mode_title"])
        self.rb_tensile.setText(t["mode_tensile"])
        self.rb_compression.setText(t["mode_compression"])
        self.rb_bending.setText(t["mode_bending"])
        self.rb_holding.setText(t["mode_holding"])
        self.rb_sequence.setText(t["mode_sequence"])

        # Sequence panel
        self.sequence_group.setTitle(t["seq_group"])
        self.btn_seq_edit.setText(t["seq_edit"])
        self._refresh_sequence_view()

        # Specimen
        self.group_spec.setTitle(t["spec_title"])
        self.lbl_spec_id.setText(t["spec_id"])
        self.lbl_mat.setText(t["spec_mat"])
        self.lbl_spec_type.setText(t["spec_type"])
        self.combo_type.setItemText(0, t["spec_type_flat"])
        self.combo_type.setItemText(1, t["spec_type_round"])
        is_flat = (self.combo_type.currentIndex() == 0)
        self.lbl_width.setText(t["spec_width"] if is_flat else t["spec_dia"])
        self.lbl_thick.setText(t["spec_thick"])
        self.lbl_l0.setText(t["spec_l0"])
        self.chk_auto_id.setText(t["spec_auto_id"])

        # Conditions
        self.cond_group.setTitle(t["cond_title"])
        self.lbl_speed.setText(t["cond_speed"])
        self.lbl_drop.setText(t["cond_drop"])
        self.lbl_bend_type.setText(t["cond_bend_type"])
        self.lbl_span.setText(t["cond_span"])
        self.lbl_hold_type.setText(t["cond_hold_type"])
        self.lbl_hold_val.setText(t["cond_hold_val"])
        self.lbl_hold_dur.setText(t["cond_hold_dur"])
        self.combo_bend_type.setItemText(0, t["cond_bend_3p"])
        self.combo_bend_type.setItemText(1, t["cond_bend_4p"])
        self.combo_hold_type.setItemText(0, t["cond_hold_load"])
        self.combo_hold_type.setItemText(1, t["cond_hold_disp"])

        # Controls
        self.ctrl_group.setTitle(t["ctrl_title"])
        self.btn_start.setText(t["btn_start"])
        self.btn_stop.setText(t["btn_stop"])
        self.btn_origin.setText(t["btn_origin"])
        self.btn_reset.setText(t["btn_reset"])

        # Export
        self.export_group.setTitle(t["export_title"])
        self.btn_excel.setText(t["btn_excel"])
        self.btn_pdf.setText(t["btn_pdf"])

        # Readout Tiles
        self.lbl_tile_load.setText(t["tile_load"])
        self.lbl_tile_disp.setText(t["tile_disp"])
        self.lbl_tile_stress.setText(t["tile_stress"])
        self.lbl_tile_ext.setText(t["tile_ext"])
        self._apply_strain_tile_label()
        self._apply_strain_source_label()

        # Graph
        self.graph_box.setTitle(t["graph_title"])
        self.rb_graph_ss.setText(t["graph_ss"])
        self.rb_graph_ld.setText(t["graph_ld"])

        # Results Table
        self.results_group.setTitle(t["results_title"])
        headers = [
            t["col_pmax"], t["col_rm"], t["col_rp02"], t["col_e"],
            t["col_a"], t["col_dl"], t["col_u"], t["col_status"]
        ]
        for col, h in enumerate(headers):
            self.table_results.setHorizontalHeaderItem(col, QTableWidgetItem(h))

        # Specimen session / overlay
        self.session_group.setTitle(t["session_group"])
        for col, key in enumerate(("session_col_show", "session_col_session",
                                   "session_col_specimen", "session_col_pmax")):
            self.table_session.setHorizontalHeaderItem(col, QTableWidgetItem(t[key]))
        self.btn_session_show_all.setText(t["session_show_all"])
        self.btn_session_hide_all.setText(t["session_hide_all"])
        self.btn_session_remove.setText(t["session_remove"])
        self.btn_session_clear.setText(t["session_clear"])
        self._refresh_session_table()

        # Batch statistics
        self.batch_group.setTitle(t["batch_group"])
        for col, key in enumerate(("batch_col_metric", "batch_col_mean", "batch_col_std",
                                   "batch_col_cv", "batch_col_min", "batch_col_max")):
            self.table_batch.setHorizontalHeaderItem(col, QTableWidgetItem(t[key]))
        self.btn_batch_excel.setText(t["btn_batch_excel"])
        self.btn_batch_pdf.setText(t["btn_batch_pdf"])
        self._refresh_batch_table()
        self._update_history_button()

        # 현재 결과표도 선택 언어로 다시 그린다
        if self.current_result is not None:
            self._update_results_table(self.current_result, self._last_completion_reason)

        # Hardware Tab
        self.settings_group.setTitle(t["hw_conn_title"])
        self.lbl_hw_mode.setText(t["hw_mode"])
        self.combo_hw_mode.setItemText(0, t["hw_mode_sim"])
        self.combo_hw_mode.setItemText(1, t["hw_mode_real"])
        self.lbl_hw_port.setText(t["hw_port"])
        self.btn_refresh_ports.setText(t["btn_refresh"])
        self.lbl_hw_baud.setText(t["hw_baud"])
        self.lbl_hw_format.setText(t["hw_format"])
        self.btn_connect_hw.setText(t["btn_disconnect"] if self.active_driver.is_connected and self.active_driver == self.serial_driver else t["btn_connect"])
        self.tare_group.setTitle(t["tare_title"])
        self.btn_tare_load.setText(t["btn_tare_load"])
        self.btn_tare_disp.setText(t["btn_tare_disp"])
        self.calib_group.setTitle(t["calib_title"])
        self.box_load_calib.setTitle(t["calib_load_title"])
        self.btn_calib_zero.setText(t["btn_calib_zero"])
        self.lbl_ref_load.setText(t["calib_ref_label"])
        self.btn_calib_span.setText(t["btn_calib_span"])
        self.box_speed_calib.setTitle(t["calib_speed_title"])
        self.lbl_target_speed.setText(t["calib_target_speed"])
        self.lbl_measured_dist.setText(t["calib_measured_dist"])
        self.btn_calib_speed.setText(t["btn_calib_speed"])
        self.mon_group.setTitle(t["packet_title"])
        self.btn_clear_log.setText(t["btn_clear_log"])

        # Control method / soft PID
        self._apply_control_language(t)

        # Hardware - 시험 중 실시간 속도 변경 지원
        self.chk_live_speed.setText(t["ctl_live_speed"])
        self.chk_live_speed.setToolTip(t["ctl_live_help"])

        # 빠른 시험 어시스턴트
        self.asst_group.setTitle(t["asst_group"])
        self.asst_edit.setPlaceholderText(t["asst_placeholder"])
        self.btn_asst_open.setText(t["asst_open"])
        for index, button in enumerate(self.asst_example_buttons, start=1):
            button.setText(t[f"asst_example_{index}_label"])
            button.setToolTip(t[f"asst_example_{index}"])
        self.assistant_panel.retranslate(lang)

        # Preferences Tab
        self._apply_preferences_language(t)

        # 언어를 바꾸면 그래프 축 라벨도 바로 갱신한다
        if hasattr(self, "plot_widget"):
            self._replot_graph()

    def _create_dashboard_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # A. 빠른 시험 어시스턴트 (명령 입력 + 세팅 카드)
        outer.addWidget(self._create_assistant_bar())
        self.assistant_panel = TestAssistantPanel(self.current_lang)
        self.assistant_panel.start_requested.connect(self._assistant_start)
        self.assistant_panel.cancel_requested.connect(self._assistant_cancel)
        outer.addWidget(self.assistant_panel)

        body = QWidget()
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(380)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        left_content = self._create_left_panel()
        left_scroll.setWidget(left_content)
        self.left_scroll = left_scroll
        layout.addWidget(left_scroll, stretch=0)

        # 오른쪽(계측 타일·그래프·세션·배치 통계·결과표)은 창 높이가 작을 때
        # 위젯이 겹치치 않도록 스크롤 영역에 담는다 (일반 크기에서는 스크롤바 없음)
        right_panel = self._create_right_panel()
        self.dash_scroll = QScrollArea()
        self.dash_scroll.setWidgetResizable(True)
        self.dash_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.dash_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.dash_scroll.setWidget(right_panel)
        layout.addWidget(self.dash_scroll, stretch=1)

        outer.addWidget(body, stretch=1)
        return tab

    # ------------------------------------------------------------------
    # 빠른 시험 어시스턴트 (명령 입력 · 시편 세팅 카드 · 자동 시험/자동 출력)
    # ------------------------------------------------------------------
    def _create_assistant_bar(self) -> QGroupBox:
        """대시보드 상단 명령 입력 바"""
        self.asst_group = QGroupBox("빠른 시험 어시스턴트")
        bar = QHBoxLayout(self.asst_group)
        bar.setContentsMargins(10, 12, 10, 8)
        bar.setSpacing(8)

        self.asst_edit = QLineEdit()
        self.asst_edit.setMinimumHeight(32)
        self.asst_edit.returnPressed.connect(self._open_assistant_card)
        bar.addWidget(self.asst_edit, stretch=1)

        self.btn_asst_open = QPushButton("세팅 카드 열기")
        self.btn_asst_open.setObjectName("btn_asst_open")
        self.btn_asst_open.setMinimumWidth(136)
        self.btn_asst_open.setMinimumHeight(32)
        self.btn_asst_open.clicked.connect(self._open_assistant_card)
        bar.addWidget(self.btn_asst_open)

        # 빠른 예시 (북마크된 명령 문장을 그대로 넣는다)
        self.asst_example_buttons: List[QPushButton] = []
        for index in (1, 2, 3):
            button = QPushButton()
            button.setProperty("class", "asst-example")
            button.setMinimumHeight(32)
            button.clicked.connect(lambda _=False, i=index: self._use_assistant_example(i))
            bar.addWidget(button)
            self.asst_example_buttons.append(button)
        return self.asst_group

    def _use_assistant_example(self, index: int):
        t = TRANSLATIONS[self.current_lang]
        self.asst_edit.setText(t.get(f"asst_example_{index}", ""))
        self._open_assistant_card()

    def _open_assistant_card(self, *_):
        """입력한 명령을 해석해 시편 세팅 카드를 펼친다 (시험은 아직 시작하지 않는다)"""
        text = self.asst_edit.text().strip()
        t = TRANSLATIONS[self.current_lang]
        if not text:
            self.asst_edit.setFocus()
            self.statusBar().showMessage(t["asst_placeholder"])
            return
        if getattr(self.active_driver, "is_running", False):
            self.statusBar().showMessage(t["asst_busy"])
            return
        self._assistant_auto_export = False
        plan = CommandAssistant.parse(text, self.current_lang)
        self.assistant_panel.set_plan(
            plan, self.edit_specimen_id.text().strip(), display_path(self.auto_report_dir))
        self.asst_edit.setText(text)

    def _assistant_cancel(self):
        self.assistant_panel.reset()
        self._assistant_auto_export = False

    def _assistant_start(self):
        """작업자가 [시편 세팅 완료 · 시험 시작]을 누른 순간에만 시험을 시작한다"""
        panel = self.assistant_panel
        plan = panel.plan
        if plan is None:
            return
        if getattr(self.active_driver, "is_running", False):
            self.statusBar().showMessage(TRANSLATIONS[self.current_lang]["asst_busy"])
            return
        errors = panel.validation_errors()
        if errors:
            panel.flag_missing(errors)
            self.statusBar().showMessage(TRANSLATIONS[self.current_lang]["asst_enter_hint"])
            return

        self._apply_assistant_plan(plan, panel.values())
        self._assistant_auto_export = panel.auto_export_enabled()
        panel.set_specimen_id(self.edit_specimen_id.text().strip())
        panel.mark_running()
        self._start_test()

    def _apply_assistant_plan(self, plan: TestCommandPlan, values: dict):
        """해석한 계획을 좌측 시험 설정 폼에 그대로 채운다"""
        radios = {
            TestMode.TENSILE: self.rb_tensile,
            TestMode.COMPRESSION: self.rb_compression,
            TestMode.BENDING: self.rb_bending,
            TestMode.HOLDING: self.rb_holding,
            TestMode.SEQUENCE: self.rb_sequence,
        }
        radios.get(plan.mode, self.rb_tensile).setChecked(True)

        self.edit_material.setText(material_label(plan.material_code, self.current_lang))

        is_round = values["specimen_type"] is SpecimenType.ROUND
        self.combo_type.setCurrentIndex(1 if is_round else 0)
        self._on_specimen_type_changed(1 if is_round else 0)
        self.spin_width.setValue(values["diameter"] if is_round else values["width"])
        if not is_round:
            self.spin_thick.setValue(values["thickness"])
        self.spin_l0.setValue(values["gauge_length"])

        if plan.mode is TestMode.BENDING:
            self.combo_bend_type.setCurrentIndex(
                0 if plan.bending_type == BendingType.THREE_POINT else 1)
            self.spin_span.setValue(values["span_length"])

        if plan.mode is TestMode.HOLDING:
            self.combo_hold_type.setCurrentIndex(
                0 if plan.holding_type == HoldingType.LOAD_HOLD else 1)
            self.spin_hold_val.setValue(plan.target_holding_val)
            self.spin_hold_dur.setValue(plan.holding_duration_s)

        self.spin_speed.setValue(plan.test_speed_mm_min)
        control_index = {
            ControlMode.DISP.value: 0,
            ControlMode.LOAD_RATE.value: 1,
            ControlMode.STRESS_RATE.value: 2,
            ControlMode.LOAD_HOLD.value: 3,
        }.get(str(plan.control_mode).upper(), 0)
        self.combo_control_mode.setCurrentIndex(control_index)
        if plan.uses_pid and plan.target_rate > 0:
            self.spin_target_rate.setValue(plan.target_rate)
        pid_index = self.combo_pid_mode.findData(plan.pid_profile_id)
        if pid_index >= 0:
            self.combo_pid_mode.setCurrentIndex(pid_index)
        # 하중 유지 선택이 시험 종류 라디오를 바꿔 놓았을 수 있으므로 다시 맞춘다
        radios.get(plan.mode, self.rb_tensile).setChecked(True)

    def _finish_assistant_export(self, specimen: Specimen, config: TestConfig) -> tuple:
        """시험 완료 후 로우데이터(Excel) · 성적서(PDF) 자동 저장"""
        paths: dict = {}
        error = ""
        try:
            paths = export_auto_reports(
                specimen, config, self.current_result, self.data_points,
                lang=self.current_lang, out_dir=self.auto_report_dir)
        except Exception as exc:  # 저장 실패가 시험 결과 표시를 막지 않는다
            error = str(exc)
            print(f"[MainWindow] 자동 저장 실패: {exc}")

        panel = self.assistant_panel
        if paths:
            panel.mark_completed(paths, self.current_result.peak_load_n,
                                 self.current_result.peak_stress_mpa, specimen.specimen_id)
        elif error:
            panel.mark_export_failed(error)
        else:
            panel.mark_completed({}, self.current_result.peak_load_n,
                                 self.current_result.peak_stress_mpa, specimen.specimen_id)
        return paths, error

    def _create_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 10, 6)
        layout.setSpacing(10)

        # A. 시험 모드 선택 (4대 시험 모드 + 다단계 시퀀스)
        self.group_mode = QGroupBox("시험 종류 선택")
        mode_layout = QGridLayout(self.group_mode)
        mode_layout.setSpacing(6)
        self.rb_tensile = QRadioButton("인장 시험")
        self.rb_compression = QRadioButton("압축 시험")
        self.rb_bending = QRadioButton("굽힘 시험")
        self.rb_holding = QRadioButton("유지 시험")
        self.rb_sequence = QRadioButton("다단계 시퀀스 시험")
        self.rb_tensile.setChecked(True)

        self.mode_btn_group = QButtonGroup()
        self.mode_btn_group.addButton(self.rb_tensile, 0)
        self.mode_btn_group.addButton(self.rb_compression, 1)
        self.mode_btn_group.addButton(self.rb_bending, 2)
        self.mode_btn_group.addButton(self.rb_holding, 3)
        self.mode_btn_group.addButton(self.rb_sequence, 4)
        self.mode_btn_group.idToggled.connect(self._on_test_mode_toggled)

        mode_layout.addWidget(self.rb_tensile, 0, 0)
        mode_layout.addWidget(self.rb_compression, 0, 1)
        mode_layout.addWidget(self.rb_bending, 1, 0)
        mode_layout.addWidget(self.rb_holding, 1, 1)
        mode_layout.addWidget(self.rb_sequence, 2, 0, 1, 2)
        layout.addWidget(self.group_mode)

        # B. 시편 제원 설정
        self.group_spec = QGroupBox("시편 정보 입력")
        spec_layout = QGridLayout(self.group_spec)
        spec_layout.setSpacing(8)

        self.lbl_spec_id = QLabel("시편 번호:")
        spec_layout.addWidget(self.lbl_spec_id, 0, 0)
        self.edit_specimen_id = QLineEdit("SALT-SP-001")
        spec_layout.addWidget(self.edit_specimen_id, 0, 1)

        self.lbl_mat = QLabel("재질:")
        spec_layout.addWidget(self.lbl_mat, 1, 0)
        self.edit_material = QLineEdit("SS400 (일반구조용강)")
        spec_layout.addWidget(self.edit_material, 1, 1)

        self.lbl_spec_type = QLabel("시편 형태:")
        spec_layout.addWidget(self.lbl_spec_type, 2, 0)
        self.combo_type = QComboBox()
        self.combo_type.addItems(["판재 (납작한 시편)", "봉재 (둥근 환봉)"])
        self.combo_type.currentIndexChanged.connect(self._on_specimen_type_changed)
        spec_layout.addWidget(self.combo_type, 2, 1)

        self.lbl_width = QLabel("폭 (mm):")
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(0.1, 500.0)
        self.spin_width.setValue(12.5)
        spec_layout.addWidget(self.lbl_width, 3, 0)
        spec_layout.addWidget(self.spin_width, 3, 1)

        self.lbl_thick = QLabel("두께 (mm):")
        self.spin_thick = QDoubleSpinBox()
        self.spin_thick.setRange(0.01, 200.0)
        self.spin_thick.setValue(3.0)
        spec_layout.addWidget(self.lbl_thick, 4, 0)
        spec_layout.addWidget(self.spin_thick, 4, 1)

        self.lbl_l0 = QLabel("표점거리 (mm):")
        self.spin_l0 = QDoubleSpinBox()
        self.spin_l0.setRange(1.0, 1000.0)
        self.spin_l0.setValue(50.0)
        spec_layout.addWidget(self.lbl_l0, 5, 0)
        spec_layout.addWidget(self.spin_l0, 5, 1)

        self.chk_auto_id = QCheckBox("시험 후 시편 번호 자동 증가")
        self.chk_auto_id.setChecked(True)
        spec_layout.addWidget(self.chk_auto_id, 6, 0, 1, 2)

        layout.addWidget(self.group_spec)

        # B-2. 다단계 시험 시퀀스 (시퀀스 모드에서만 표시)
        self.sequence_group = QGroupBox("다단계 시험 시퀀스")
        seq_layout = QVBoxLayout(self.sequence_group)
        seq_layout.setContentsMargins(10, 12, 10, 10)
        seq_layout.setSpacing(6)

        self.lbl_seq_count = QLabel("총 4단계 · 표준 인장 4단계")
        self.lbl_seq_count.setStyleSheet("color: #1D4ED8; font-size: 8.5pt; font-weight: 700; background: transparent;")
        seq_layout.addWidget(self.lbl_seq_count)

        self.list_sequence = QListWidget()
        self.list_sequence.setFixedHeight(110)
        self.list_sequence.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list_sequence.setStyleSheet(
            "QListWidget { background-color: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 3px; "
            "font-size: 8.5pt; padding: 2px; }"
            "QListWidget::item { padding: 3px 4px; border-bottom: 1px solid #F1F5F9; }"
        )
        seq_layout.addWidget(self.list_sequence)

        self.btn_seq_edit = QPushButton("시퀀스 편집")
        self.btn_seq_edit.setMinimumHeight(28)
        self.btn_seq_edit.clicked.connect(self._edit_sequence)
        seq_layout.addWidget(self.btn_seq_edit)
        self.sequence_group.setVisible(False)
        layout.addWidget(self.sequence_group)

        # C. 시험 조건 설정 (동적 모드 연동)
        self.cond_group = QGroupBox("시험 조건 설정")
        cond_layout = QGridLayout(self.cond_group)
        cond_layout.setSpacing(8)

        self.lbl_speed = QLabel("시험 속도 (mm/min):")
        cond_layout.addWidget(self.lbl_speed, 0, 0)
        self.spin_speed = QDoubleSpinBox()
        self.spin_speed.setRange(0.1, 500.0)
        self.spin_speed.setValue(5.0)
        cond_layout.addWidget(self.spin_speed, 0, 1)

        # 파단 감지 드롭
        self.lbl_drop = QLabel("파단 감지 기준 (%):")
        self.spin_drop = QDoubleSpinBox()
        self.spin_drop.setRange(10.0, 95.0)
        self.spin_drop.setValue(50.0)
        cond_layout.addWidget(self.lbl_drop, 1, 0)
        cond_layout.addWidget(self.spin_drop, 1, 1)

        # 굽힘 시험 전용: 굽힘 방식 & 지간 거리 (L)
        self.lbl_bend_type = QLabel("굽힘 방식:")
        self.combo_bend_type = QComboBox()
        self.combo_bend_type.addItems(["3점 굽힘", "4점 굽힘"])
        cond_layout.addWidget(self.lbl_bend_type, 2, 0)
        cond_layout.addWidget(self.combo_bend_type, 2, 1)

        self.lbl_span = QLabel("지지대 간격 (mm):")
        self.spin_span = QDoubleSpinBox()
        self.spin_span.setRange(5.0, 2000.0)
        self.spin_span.setValue(100.0)
        cond_layout.addWidget(self.lbl_span, 3, 0)
        cond_layout.addWidget(self.spin_span, 3, 1)

        # 유지 시험 전용: 유지 방식 & 목표 유지값 & 유지 시간
        self.lbl_hold_type = QLabel("유지 제어 방식:")
        self.combo_hold_type = QComboBox()
        self.combo_hold_type.addItems(["하중 유지 (크리프)", "변위 유지 (이완)"])
        cond_layout.addWidget(self.lbl_hold_type, 4, 0)
        cond_layout.addWidget(self.combo_hold_type, 4, 1)

        self.lbl_hold_val = QLabel("목표 유지값:")
        self.spin_hold_val = QDoubleSpinBox()
        self.spin_hold_val.setRange(0.1, 100000.0)
        self.spin_hold_val.setValue(1000.0)
        cond_layout.addWidget(self.lbl_hold_val, 5, 0)
        cond_layout.addWidget(self.spin_hold_val, 5, 1)

        self.lbl_hold_dur = QLabel("유지 시간 (초):")
        self.spin_hold_dur = QDoubleSpinBox()
        self.spin_hold_dur.setRange(1.0, 86400.0)
        self.spin_hold_dur.setValue(60.0)
        cond_layout.addWidget(self.lbl_hold_dur, 6, 0)
        cond_layout.addWidget(self.spin_hold_dur, 6, 1)

        # 초기 상태 숨김
        self.lbl_bend_type.setVisible(False)
        self.combo_bend_type.setVisible(False)
        self.lbl_span.setVisible(False)
        self.spin_span.setVisible(False)

        self.lbl_hold_type.setVisible(False)
        self.combo_hold_type.setVisible(False)
        self.lbl_hold_val.setVisible(False)
        self.spin_hold_val.setVisible(False)
        self.lbl_hold_dur.setVisible(False)
        self.spin_hold_dur.setVisible(False)

        layout.addWidget(self.cond_group)

        # C-2. 제어 방식 및 소프트 PID (하중 속도 · 응력 속도 · 하중 유지)
        # 생성은 조건 그룹 뒤에서 하지만, 화면에는 시편 정보 다음에 놓는다.
        layout.insertWidget(2, self._create_control_group())

        # D. 장비 조작 버튼
        self.ctrl_group = QGroupBox("장비 조작")
        ctrl_layout = QVBoxLayout(self.ctrl_group)
        ctrl_layout.setSpacing(8)

        self.btn_start = QPushButton("시험 시작")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self._start_test)
        ctrl_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("비상 정지")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_test)
        ctrl_layout.addWidget(self.btn_stop)

        h_sub_btns = QHBoxLayout()
        self.btn_origin = QPushButton("원점 복귀")
        self.btn_origin.clicked.connect(self._return_origin)
        self.btn_reset = QPushButton("데이터 초기화")
        self.btn_reset.clicked.connect(self._reset_data)
        h_sub_btns.addWidget(self.btn_origin)
        h_sub_btns.addWidget(self.btn_reset)
        ctrl_layout.addLayout(h_sub_btns)

        layout.addWidget(self.ctrl_group)

        # E. 데이터 내보내기 그룹 (엑셀 / PDF)
        self.export_group = QGroupBox("성적서 및 데이터 저장")
        export_layout = QVBoxLayout(self.export_group)
        export_layout.setSpacing(8)

        self.btn_excel = QPushButton("엑셀 데이터 저장 (.xlsx)")
        self.btn_excel.setObjectName("btn_excel")
        self.btn_excel.setEnabled(False)
        self.btn_excel.clicked.connect(self._export_excel)
        export_layout.addWidget(self.btn_excel)

        self.btn_pdf = QPushButton("시험 성적서 출력 (.pdf)")
        self.btn_pdf.setObjectName("btn_pdf")
        self.btn_pdf.setEnabled(False)
        self.btn_pdf.clicked.connect(self._export_pdf)
        export_layout.addWidget(self.btn_pdf)

        layout.addWidget(self.export_group)
        layout.addStretch()
        return panel

    # ------------------------------------------------------------------
    # 제어 방식 및 소프트 PID
    # ------------------------------------------------------------------
    def _create_control_group(self) -> QGroupBox:
        self.ctl_group = QGroupBox("제어 방식 및 PID")
        grid = QGridLayout(self.ctl_group)
        grid.setContentsMargins(10, 12, 10, 10)
        grid.setSpacing(6)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        self.lbl_ctl_mode = QLabel("제어 방식:")
        self.combo_control_mode = QComboBox()
        self.combo_control_mode.addItems([
            "변위 속도 (mm/min)", "하중 속도 (N/min)",
            "응력 속도 (MPa/s)", "하중 유지 (N)",
        ])
        self.combo_control_mode.currentIndexChanged.connect(self._on_control_mode_changed)
        grid.addWidget(self.lbl_ctl_mode, 0, 0)
        grid.addWidget(self.combo_control_mode, 0, 1, 1, 3)

        self.lbl_target_rate = QLabel("목표 하중 속도:")
        self.spin_target_rate = QDoubleSpinBox()
        self.spin_target_rate.setRange(0.01, 1_000_000.0)
        self.spin_target_rate.setDecimals(2)
        self.spin_target_rate.setValue(6000.0)
        self.lbl_target_unit = QLabel("N/min")
        self.lbl_target_unit.setStyleSheet("color: #64748B; font-size: 8.5pt; background: transparent;")
        grid.addWidget(self.lbl_target_rate, 1, 0)
        grid.addWidget(self.spin_target_rate, 1, 1, 1, 2)
        grid.addWidget(self.lbl_target_unit, 1, 3)

        self.lbl_pid_mode = QLabel("PID 모드:")
        self.combo_pid_mode = QComboBox()
        for profile in self.pid_manager.list():
            self.combo_pid_mode.addItem(profile.name_ko, profile.id)
        self.combo_pid_mode.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo_pid_mode.setMinimumContentsLength(20)
        self.combo_pid_mode.setCurrentIndex(max(0, self.combo_pid_mode.findData("metal")))
        self.combo_pid_mode.currentIndexChanged.connect(self._on_pid_profile_changed)
        grid.addWidget(self.lbl_pid_mode, 2, 0)
        grid.addWidget(self.combo_pid_mode, 2, 1, 1, 3)

        self.lbl_gains = QLabel("게인:")
        self.spin_kp = QDoubleSpinBox()
        self.spin_ki = QDoubleSpinBox()
        self.spin_kd = QDoubleSpinBox()
        for spin, prefix in ((self.spin_kp, "P "), (self.spin_ki, "I "), (self.spin_kd, "D ")):
            spin.setRange(0.0, 20.0)
            spin.setDecimals(2)
            spin.setSingleStep(0.05)
            spin.setPrefix(prefix)
            spin.setMinimumWidth(64)
        grid.addWidget(self.lbl_gains, 3, 0)
        grid.addWidget(self.spin_kp, 3, 1)
        grid.addWidget(self.spin_ki, 3, 2)
        grid.addWidget(self.spin_kd, 3, 3)

        self.btn_save_pid = QPushButton("게인 저장")
        self.btn_save_pid.setMinimumHeight(26)
        self.btn_save_pid.clicked.connect(self._save_pid_gains)
        self.lbl_pid_state = QLabel("")
        self.lbl_pid_state.setStyleSheet("color: #1D4ED8; font-size: 8pt; background: transparent;")
        grid.addWidget(self.btn_save_pid, 4, 0, 1, 2)
        grid.addWidget(self.lbl_pid_state, 4, 2, 1, 2)

        self.lbl_ctl_delay = QLabel("지연 (ms):")
        self.spin_ctl_delay = QDoubleSpinBox()
        self.spin_ctl_delay.setRange(0.0, 500.0)
        self.spin_ctl_delay.setDecimals(0)
        self.spin_ctl_delay.setValue(35.0)
        self.lbl_ctl_hz = QLabel("주기 (Hz):")
        self.spin_ctl_hz = QDoubleSpinBox()
        self.spin_ctl_hz.setRange(5.0, 100.0)
        self.spin_ctl_hz.setDecimals(0)
        self.spin_ctl_hz.setValue(25.0)
        grid.addWidget(self.lbl_ctl_delay, 5, 0)
        grid.addWidget(self.spin_ctl_delay, 5, 1)
        grid.addWidget(self.lbl_ctl_hz, 5, 2)
        grid.addWidget(self.spin_ctl_hz, 5, 3)

        self.lbl_ctl_status = QLabel("제어 상태: 대기 중")
        self.lbl_ctl_status.setStyleSheet(
            "color: #334155; font-size: 8pt; background: transparent;")
        self.lbl_ctl_status.setWordWrap(True)
        grid.addWidget(self.lbl_ctl_status, 6, 0, 1, 4)

        self.lbl_ctl_hint = QLabel(
            "게인은 추정 강성으로 환산한 변위 오차 기준입니다. "
            "통신 주기(20~50 Hz)보다 빠른 응답은 제어하지 않습니다.")
        self.lbl_ctl_hint.setStyleSheet(
            "color: #64748B; font-size: 7.5pt; background: transparent;")
        self.lbl_ctl_hint.setWordWrap(True)
        grid.addWidget(self.lbl_ctl_hint, 7, 0, 1, 4)

        # 변위 속도 제어에서는 PID 항목을 숨긴다
        self.ctl_pid_widgets = [
            self.lbl_pid_mode, self.combo_pid_mode, self.lbl_gains,
            self.spin_kp, self.spin_ki, self.spin_kd, self.btn_save_pid,
            self.lbl_pid_state, self.lbl_ctl_delay, self.spin_ctl_delay,
            self.lbl_ctl_hz, self.spin_ctl_hz, self.lbl_ctl_hint,
            self.lbl_ctl_status,
        ]
        self._on_pid_profile_changed(self.combo_pid_mode.currentIndex())
        self._on_control_mode_changed(self.combo_control_mode.currentIndex())
        return self.ctl_group

    # ------------------------------------------------------------------
    def _selected_control_mode(self) -> ControlMode:
        return [ControlMode.DISP, ControlMode.LOAD_RATE,
                ControlMode.STRESS_RATE, ControlMode.LOAD_HOLD][
            max(0, min(3, self.combo_control_mode.currentIndex()))]

    def _selected_pid_profile_id(self) -> str:
        data = self.combo_pid_mode.currentData()
        return str(data or "metal")

    def _on_control_mode_changed(self, index: int):
        mode = self._selected_control_mode()
        t = TRANSLATIONS[self.current_lang]
        uses_pid = mode is not ControlMode.DISP

        for widget in getattr(self, "ctl_pid_widgets", []):
            widget.setVisible(uses_pid)
        # 변위 속도는 시험 조건의 '시험 속도'를 쓰므로 목표 속도 줄을 숨긴다
        for widget in (self.lbl_target_rate, self.spin_target_rate, self.lbl_target_unit):
            widget.setVisible(uses_pid)
        self.lbl_speed.setVisible(not uses_pid)
        self.spin_speed.setVisible(not uses_pid)

        if mode is ControlMode.LOAD_RATE:
            self.lbl_target_rate.setText(t["ctl_rate_load"])
            self.lbl_target_unit.setText("N/min")
        elif mode is ControlMode.STRESS_RATE:
            self.lbl_target_rate.setText(t["ctl_rate_stress"])
            self.lbl_target_unit.setText("MPa/s")
        elif mode is ControlMode.LOAD_HOLD:
            self.lbl_target_rate.setText(t["ctl_rate_hold"])
            self.lbl_target_unit.setText("N/min")
            # 하중 유지는 유지 시험의 목표 하중·유지 시간을 사용한다
            if not self.rb_holding.isChecked():
                self.rb_holding.setChecked(True)
        else:
            self.lbl_target_rate.setText(t["ctl_rate_disp"])
            self.lbl_target_unit.setText("mm/min")

        if not uses_pid:
            self.lbl_ctl_status.setText(f'{t["ctl_status"]} {t["ctl_status_idle"]}')

    def _on_pid_profile_changed(self, index: int):
        profile = self.pid_manager.get(self._selected_pid_profile_id())
        for spin, value in ((self.spin_kp, profile.kp), (self.spin_ki, profile.ki),
                            (self.spin_kd, profile.kd)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        if hasattr(self, "lbl_pid_state"):
            self.lbl_pid_state.setText("")

    def _save_pid_gains(self):
        profile_id = self._selected_pid_profile_id()
        profile = self.pid_manager.update(
            profile_id, kp=self.spin_kp.value(), ki=self.spin_ki.value(),
            kd=self.spin_kd.value(),
        )
        t = TRANSLATIONS[self.current_lang]
        self.lbl_pid_state.setText(t["ctl_gains_saved"].format(name=profile.name(self.current_lang)))

    def _refresh_control_status(self):
        t = TRANSLATIONS[self.current_lang]
        text = self.active_driver.current_control_status(self.current_lang)
        self.lbl_ctl_status.setText(f'{t["ctl_status"]} {text or t["ctl_status_idle"]}')

    def _apply_control_language(self, t: dict):
        self.ctl_group.setTitle(t["ctl_group"])
        self.lbl_ctl_mode.setText(t["ctl_mode"])
        self.combo_control_mode.setItemText(0, t["ctl_mode_disp"])
        self.combo_control_mode.setItemText(1, t["ctl_mode_load"])
        self.combo_control_mode.setItemText(2, t["ctl_mode_stress"])
        self.combo_control_mode.setItemText(3, t["ctl_mode_hold"])
        self.lbl_pid_mode.setText(t["ctl_pid_mode"])
        for row in range(self.combo_pid_mode.count()):
            profile = self.pid_manager.get(str(self.combo_pid_mode.itemData(row)))
            self.combo_pid_mode.setItemText(row, profile.name(self.current_lang))
        self.lbl_gains.setText(t["ctl_gains"])
        self.btn_save_pid.setText(t["ctl_save_gains"])
        self.lbl_ctl_delay.setText(t["ctl_delay"])
        self.lbl_ctl_hz.setText(t["ctl_rate"])
        self.lbl_ctl_hint.setText(t["ctl_hint"])
        self._on_control_mode_changed(self.combo_control_mode.currentIndex())
        self._refresh_control_status()

    def _create_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 1. 상단 대형 디지털 계측 타일 4개
        tiles_layout = QHBoxLayout()
        tiles_layout.setSpacing(10)

        self.tile_load, self.lbl_tile_load, self.lbl_load_val = self._create_tile("하중", "0.0", "N")
        self.tile_disp, self.lbl_tile_disp, self.lbl_disp_val = self._create_tile("변위 (이동거리)", "0.000", "mm")
        self.tile_ext, self.lbl_tile_ext, self.lbl_ext_val = self._create_tile("신율계 변위", "0.000", "mm")
        self.tile_stress, self.lbl_tile_stress, self.lbl_stress_val = self._create_tile("응력", "0.0", "MPa")
        self.tile_strain, self.lbl_tile_strain, self.lbl_strain_val = self._create_tile("변형률", "0.00", "%")

        tiles_layout.addWidget(self.tile_load)
        tiles_layout.addWidget(self.tile_disp)
        tiles_layout.addWidget(self.tile_ext)
        tiles_layout.addWidget(self.tile_stress)
        tiles_layout.addWidget(self.tile_strain)
        # 신율계를 사용하지 않으면 신율계 타일은 숨김
        self.tile_ext.setVisible(self.prefs.ext.enabled)
        layout.addLayout(tiles_layout)

        # 2. 실시간 그래프
        self.graph_box = QGroupBox("실시간 시험 곡선 그래프")
        graph_box_layout = QVBoxLayout(self.graph_box)

        graph_ctrl_layout = QHBoxLayout()
        self.rb_graph_ss = QRadioButton("응력 - 변형률 곡선")
        self.rb_graph_ld = QRadioButton("하중 - 변위 곡선")
        self.rb_graph_ss.setChecked(True)
        self.graph_btn_group = QButtonGroup()
        self.graph_btn_group.addButton(self.rb_graph_ss)
        self.graph_btn_group.addButton(self.rb_graph_ld)
        self.rb_graph_ss.toggled.connect(self._replot_graph)

        graph_ctrl_layout.addWidget(self.rb_graph_ss)
        graph_ctrl_layout.addWidget(self.rb_graph_ld)
        graph_ctrl_layout.addStretch()
        graph_box_layout.addLayout(graph_ctrl_layout)

        if HAS_PYQTGRAPH:
            pg.setConfigOption('background', '#FFFFFF')
            pg.setConfigOption('foreground', '#334155')
            pg.setConfigOption('antialias', True)
            self.plot_widget = pg.PlotWidget(
                axisItems={'left': NumberAxis(orientation='left'),
                           'bottom': NumberAxis(orientation='bottom')}
            )
            self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
            self.plot_widget.setLabel('bottom', '변형률 (%)')
            self.plot_widget.setLabel('left', '응력 (MPa)')
            # 축 제목과 눈금 숫자가 겹치지 않도록 축 폭을 명시 (고배율/긴 숫자 대응)
            self.plot_widget.getAxis('left').setWidth(72)
            self.plot_widget.getAxis('bottom').setHeight(42)
            self.plot_curve = self.plot_widget.plot(pen=pg.mkPen(color='#1D4ED8', width=2))
            self.plot_widget.setMinimumHeight(120)
            graph_box_layout.addWidget(self.plot_widget)
        else:
            lbl_nograph = QLabel("pyqtgraph 라이브러리가 설치되지 않아 차트가 비활성화되었습니다.")
            lbl_nograph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            graph_box_layout.addWidget(lbl_nograph)

        layout.addWidget(self.graph_box, stretch=3)
        self.graph_box.setMinimumHeight(160)

        # 3. 시편 세션(오버레이) + 배치 통계
        mid_row = QHBoxLayout()
        mid_row.setSpacing(10)
        mid_row.addWidget(self._create_session_group(), stretch=0)
        mid_row.addWidget(self._create_batch_group(), stretch=1)
        layout.addLayout(mid_row, stretch=2)

        # 4. 시험 결과표
        self.results_group = QGroupBox("시험 결과 분석표")
        res_layout = QVBoxLayout(self.results_group)
        res_layout.setContentsMargins(10, 10, 10, 10)
        res_layout.setSpacing(6)

        self.table_results = QTableWidget(1, len(self.RESULT_COLUMNS))
        self.table_results.verticalHeader().setVisible(False)
        self.table_results.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_results.setFixedHeight(64)
        self.table_results.setStyleSheet("QTableWidget { font-size: 8.5pt; }")

        for col, (label, _) in enumerate(self.RESULT_COLUMNS):
            self.table_results.setHorizontalHeaderItem(col, QTableWidgetItem(label))
            item = QTableWidgetItem("-")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_results.setItem(0, col, item)

        res_layout.addWidget(self.table_results)

        # 변형률 측정 소스 표시 (크로스헤드 / 신율계)
        self.lbl_strain_source = QLabel("변형률 측정 소스: 크로스헤드 변위")
        self.lbl_strain_source.setStyleSheet("color: #64748B; font-size: 8.5pt; font-weight: 600; background: transparent;")
        self.lbl_strain_source.setAlignment(Qt.AlignmentFlag.AlignRight)
        res_layout.addWidget(self.lbl_strain_source)

        layout.addWidget(self.results_group, stretch=0)

        return panel

    # ------------------------------------------------------------------
    # 시편 세션 / 배치 통계 위젯
    # ------------------------------------------------------------------
    def _create_session_group(self) -> QGroupBox:
        self.session_group = QGroupBox("시편 세션 / 오버레이")
        self.session_group.setFixedWidth(300)
        group_layout = QVBoxLayout(self.session_group)
        group_layout.setContentsMargins(10, 12, 10, 10)
        group_layout.setSpacing(6)

        self.table_session = QTableWidget(0, 4)
        self.table_session.setHorizontalHeaderLabels(["보기", "세션", "시편 ID", "최대 하중 (N)"])
        self.table_session.verticalHeader().setVisible(False)
        self.table_session.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table_session.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_session.setColumnWidth(0, 38)
        self.table_session.setColumnWidth(1, 52)
        self.table_session.setColumnWidth(3, 80)
        self.table_session.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_session.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_session.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_session.setWordWrap(False)
        self.table_session.verticalHeader().setDefaultSectionSize(20)
        self.table_session.setFixedHeight(132)
        self.table_session.setStyleSheet("QTableWidget { font-size: 8.5pt; }")
        self.table_session.itemChanged.connect(self._on_session_item_changed)
        group_layout.addWidget(self.table_session)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(5)
        self.btn_session_show_all = QPushButton("전체 보기")
        self.btn_session_hide_all = QPushButton("전체 숨김")
        self.btn_session_remove = QPushButton("선택 삭제")
        self.btn_session_clear = QPushButton("세션 비우기")
        for btn in (self.btn_session_show_all, self.btn_session_hide_all,
                    self.btn_session_remove, self.btn_session_clear):
            btn.setFixedHeight(24)
            btn.setStyleSheet("font-size: 8pt; padding: 2px 3px;")
        self.btn_session_show_all.clicked.connect(lambda: self._set_all_session_visible(True))
        self.btn_session_hide_all.clicked.connect(lambda: self._set_all_session_visible(False))
        self.btn_session_remove.clicked.connect(self._remove_selected_session)
        self.btn_session_clear.clicked.connect(self._clear_session)
        btn_row.addWidget(self.btn_session_show_all)
        btn_row.addWidget(self.btn_session_hide_all)
        btn_row.addWidget(self.btn_session_remove)
        btn_row.addWidget(self.btn_session_clear)
        group_layout.addLayout(btn_row)
        group_layout.addStretch()
        return self.session_group

    def _create_batch_group(self) -> QGroupBox:
        self.batch_group = QGroupBox("배치 통계 (선택 시편)")
        group_layout = QVBoxLayout(self.batch_group)
        group_layout.setContentsMargins(10, 12, 10, 10)
        group_layout.setSpacing(6)

        self.table_batch = QTableWidget(len(BATCH_METRICS), 6)
        self.table_batch.setHorizontalHeaderLabels(["물성", "평균", "표준편차", "CV (%)", "최소", "최대"])
        self.table_batch.verticalHeader().setVisible(False)
        self.table_batch.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_batch.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table_batch.setColumnWidth(0, 108)
        self.table_batch.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_batch.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table_batch.setWordWrap(False)
        self.table_batch.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table_batch.verticalHeader().setDefaultSectionSize(21)
        self.table_batch.setFixedHeight(146)
        self.table_batch.setStyleSheet("QTableWidget { font-size: 8pt; }")
        for row, (key, _unit, _dec) in enumerate(BATCH_METRICS):
            item = QTableWidgetItem(metric_label(key, "KO"))
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.table_batch.setItem(row, 0, item)
            for col in range(1, 6):
                value_item = QTableWidgetItem("-")
                value_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table_batch.setItem(row, col, value_item)
        group_layout.addWidget(self.table_batch)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.btn_batch_excel = QPushButton("배치 요약 엑셀 (.xlsx)")
        self.btn_batch_pdf = QPushButton("배치 요약 PDF (.pdf)")
        self.btn_batch_excel.setMinimumHeight(28)
        self.btn_batch_pdf.setMinimumHeight(28)
        self.btn_batch_excel.clicked.connect(lambda: self._export_batch("xlsx"))
        self.btn_batch_pdf.clicked.connect(lambda: self._export_batch("pdf"))
        btn_row.addWidget(self.btn_batch_excel)
        btn_row.addWidget(self.btn_batch_pdf)
        group_layout.addLayout(btn_row)
        group_layout.addStretch()
        self._refresh_batch_table()
        return self.batch_group

    def _create_hardware_tab(self) -> QWidget:
        # 내용이 많은 탭이므로 스크롤 영역에 넣어 작은 창·고배율 배율에서도 겹치지 않게 함
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.hw_scroll = scroll

        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(14)

        # 1. 상단 통신 설정 카드
        self.settings_group = QGroupBox("통신 포트 및 장비 설정")
        settings_layout = QGridLayout(self.settings_group)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setSpacing(10)

        self.lbl_hw_mode = QLabel("동작 모드:")
        settings_layout.addWidget(self.lbl_hw_mode, 0, 0)
        self.combo_hw_mode = QComboBox()
        self.combo_hw_mode.addItems(["가상 시뮬레이터 (장비 없이 테스트)", "실제 시험기 연결 (봉신 P2020 / P2014)"])
        self.combo_hw_mode.currentIndexChanged.connect(self._on_hw_mode_changed)
        settings_layout.addWidget(self.combo_hw_mode, 0, 1, 1, 2)

        self.lbl_hw_port = QLabel("통신 포트:")
        settings_layout.addWidget(self.lbl_hw_port, 1, 0)
        self.combo_com_port = QComboBox()
        self.btn_refresh_ports = QPushButton("포트 새로고침")
        self.btn_refresh_ports.setFixedWidth(120)
        self.btn_refresh_ports.clicked.connect(self._refresh_com_ports)
        settings_layout.addWidget(self.combo_com_port, 1, 1)
        settings_layout.addWidget(self.btn_refresh_ports, 1, 2)
        self._refresh_com_ports()

        self.lbl_hw_baud = QLabel("통신 속도:")
        settings_layout.addWidget(self.lbl_hw_baud, 2, 0)
        self.combo_baud = QComboBox()
        self.combo_baud.addItems(["115200 (봉신 P2020/2014 표준)", "57600", "38400", "19200", "9600"])
        settings_layout.addWidget(self.combo_baud, 2, 1, 1, 2)

        self.lbl_hw_format = QLabel("통신 규격:")
        settings_layout.addWidget(self.lbl_hw_format, 3, 0)
        lbl_format_val = QLabel("Data 8 Bit / Parity None / Stop 1 Bit (8-N-1)")
        lbl_format_val.setStyleSheet("color: #475569; font-weight: 600;")
        settings_layout.addWidget(lbl_format_val, 3, 1, 1, 2)

        # 시험 중 실시간 속도 변경(SPD) 지원 여부
        self.chk_live_speed = QCheckBox("시험 중 실시간 속도 변경 지원 (SPD 명령)")
        self.chk_live_speed.setChecked(False)
        self.chk_live_speed.setToolTip(
            "인디케이터가 시험 중 SPD 명령을 받는 것이 확인된 경우에만 켭니다. "
            "끄면 초기 강성으로 환산한 속도를 한 번만 넣습니다.")
        settings_layout.addWidget(self.chk_live_speed, 4, 0, 1, 3)

        h_conn = QHBoxLayout()
        self.btn_connect_hw = QPushButton("장비 연결")
        self.btn_connect_hw.setStyleSheet("background-color: #1D4ED8; color: #FFFFFF; font-size: 10pt; font-weight: bold; min-height: 32px;")
        self.btn_connect_hw.clicked.connect(self._toggle_hw_connection)
        
        self.lbl_hw_status = QLabel("● 장비 미연결 (가상 시뮬레이터 동작 중)")
        self.lbl_hw_status.setStyleSheet("color: #64748B; font-weight: 700; font-size: 9.5pt; margin-left: 12px;")
        h_conn.addWidget(self.btn_connect_hw, stretch=1)
        h_conn.addWidget(self.lbl_hw_status, stretch=2)
        settings_layout.addLayout(h_conn, 4, 0, 1, 3)

        main_layout.addWidget(self.settings_group)

        # 2. 영점 맞춤 제어 카드
        self.tare_group = QGroupBox("영점 맞춤")
        tare_layout = QHBoxLayout(self.tare_group)
        tare_layout.setContentsMargins(16, 12, 16, 12)
        tare_layout.setSpacing(14)

        self.btn_tare_load = QPushButton("하중 영점 맞춤 (0.00 N)")
        self.btn_tare_load.setMinimumHeight(32)
        self.btn_tare_load.clicked.connect(self._tare_load)

        self.btn_tare_disp = QPushButton("변위 영점 맞춤 (0.000 mm)")
        self.btn_tare_disp.setMinimumHeight(32)
        self.btn_tare_disp.clicked.connect(self._tare_disp)

        tare_layout.addWidget(self.btn_tare_load)
        tare_layout.addWidget(self.btn_tare_disp)
        tare_layout.addStretch()

        main_layout.addWidget(self.tare_group)

        # 3. 장비 정밀 교정 카드
        self.calib_group = QGroupBox("장비 정밀 교정")
        calib_layout = QVBoxLayout(self.calib_group)
        calib_layout.setContentsMargins(16, 12, 16, 12)
        calib_layout.setSpacing(10)

        # 3-A. 로드셀 2점 교정
        self.box_load_calib = QGroupBox("1) 로드셀 2점 하중 교정")
        grid_load = QGridLayout(self.box_load_calib)
        grid_load.setSpacing(8)

        grid_load.addWidget(QLabel("영점:"), 0, 0)
        self.btn_calib_zero = QPushButton("현재 센서값을 무부하 영점으로 설정")
        self.btn_calib_zero.clicked.connect(self._do_calib_zero)
        grid_load.addWidget(self.btn_calib_zero, 0, 1, 1, 2)

        self.lbl_ref_load = QLabel("기준 하중값:")
        grid_load.addWidget(self.lbl_ref_load, 1, 0)
        self.edit_ref_load = QLineEdit("1000.0")
        self.combo_ref_unit = QComboBox()
        self.combo_ref_unit.addItems(["kgf", "kN", "N"])
        self.btn_calib_span = QPushButton("스팬 교정 실행")
        self.btn_calib_span.setStyleSheet("background-color: #1D4ED8; color: white; font-weight: bold;")
        self.btn_calib_span.clicked.connect(self._do_calib_span)
        grid_load.addWidget(self.edit_ref_load, 1, 1)
        grid_load.addWidget(self.combo_ref_unit, 1, 2)
        grid_load.addWidget(self.btn_calib_span, 1, 3)

        self.lbl_load_factor = QLabel(f"현재 하중 보정 계수: {self.serial_driver.calib_mgr.data.load_scale_factor:.5f} (최근: {self.serial_driver.calib_mgr.data.last_load_calib_date})")
        self.lbl_load_factor.setStyleSheet("color: #0369A1; font-weight: 600; font-size: 8.5pt;")
        grid_load.addWidget(self.lbl_load_factor, 2, 0, 1, 4)
        calib_layout.addWidget(self.box_load_calib)

        # 3-B. 크로스헤드 속도 교정
        self.box_speed_calib = QGroupBox("2) 이동 속도 교정")
        grid_speed = QGridLayout(self.box_speed_calib)
        grid_speed.setSpacing(8)

        self.lbl_target_speed = QLabel("목표 속도 (mm/min):")
        grid_speed.addWidget(self.lbl_target_speed, 0, 0)
        self.edit_target_speed = QLineEdit("50.0")
        grid_speed.addWidget(self.edit_target_speed, 0, 1)

        self.lbl_measured_dist = QLabel("1분간 실측 이동거리 (mm):")
        grid_speed.addWidget(self.lbl_measured_dist, 0, 2)
        self.edit_measured_dist = QLineEdit("48.5")
        grid_speed.addWidget(self.edit_measured_dist, 0, 3)

        self.btn_calib_speed = QPushButton("속도 보정값 계산 및 적용")
        self.btn_calib_speed.setStyleSheet("background-color: #0284C7; color: white; font-weight: bold;")
        self.btn_calib_speed.clicked.connect(self._do_calib_speed)
        grid_speed.addWidget(self.btn_calib_speed, 0, 4)

        self.lbl_speed_factor = QLabel(f"현재 속도 보정 계수: {self.serial_driver.calib_mgr.data.speed_scale_factor:.5f} (최근: {self.serial_driver.calib_mgr.data.last_speed_calib_date})")
        self.lbl_speed_factor.setStyleSheet("color: #0369A1; font-weight: 600; font-size: 8.5pt;")
        grid_speed.addWidget(self.lbl_speed_factor, 1, 0, 1, 5)
        calib_layout.addWidget(self.box_speed_calib)

        main_layout.addWidget(self.calib_group)

        # 4. 실시간 통신 패킷 모니터
        self.mon_group = QGroupBox("실시간 데이터 수신 모니터")
        mon_layout = QVBoxLayout(self.mon_group)
        mon_layout.setContentsMargins(14, 12, 14, 12)
        mon_layout.setSpacing(8)

        self.txt_packet_log = QTextEdit()
        self.txt_packet_log.setReadOnly(True)
        self.txt_packet_log.setMinimumHeight(170)
        self.txt_packet_log.setStyleSheet(
            "background-color: #0F172A; color: #38BDF8; font-family: 'Consolas', monospace; font-size: 9pt; border-radius: 4px; padding: 8px;"
        )
        mon_layout.addWidget(self.txt_packet_log)

        h_mon_ctrl = QHBoxLayout()
        self.btn_clear_log = QPushButton("화면 지우기")
        self.btn_clear_log.setFixedWidth(100)
        self.btn_clear_log.clicked.connect(lambda: self.txt_packet_log.clear())
        h_mon_ctrl.addWidget(self.btn_clear_log)
        h_mon_ctrl.addStretch()
        mon_layout.addLayout(h_mon_ctrl)

        main_layout.addWidget(self.mon_group, stretch=1)
        scroll.setWidget(tab)
        return scroll

    def _create_preferences_tab(self) -> QWidget:
        """환경 설정 탭: 신율계(변위계) 사용 여부와 방식, 계측 파라미터 영구 저장"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pref_scroll = scroll

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        columns = QHBoxLayout()
        columns.setSpacing(16)

        # ---------------- 왼쪽: 신율계 설정 ----------------
        self.pref_ext_group = QGroupBox("신율계(변위계) 설정")
        self.pref_ext_group.setMinimumWidth(470)
        self.pref_ext_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        grid = QGridLayout(self.pref_ext_group)
        grid.setContentsMargins(18, 20, 18, 16)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        self.lbl_pref_ext_use = QLabel("신율계 사용:")
        grid.addWidget(self.lbl_pref_ext_use, 0, 0)

        use_row = QHBoxLayout()
        use_row.setSpacing(18)
        self.rb_ext_off = QRadioButton("사용 안 함 (크로스헤드 변위 사용)")
        self.rb_ext_on = QRadioButton("사용함 (신율계 적용)")
        self.pref_ext_btn_group = QButtonGroup()
        self.pref_ext_btn_group.addButton(self.rb_ext_off, 0)
        self.pref_ext_btn_group.addButton(self.rb_ext_on, 1)
        self.pref_ext_btn_group.idToggled.connect(self._on_pref_ext_toggled)
        use_row.addWidget(self.rb_ext_off)
        use_row.addWidget(self.rb_ext_on)
        use_row.addStretch()
        grid.addLayout(use_row, 0, 1, 1, 3)

        self.lbl_pref_ext_type = QLabel("신호 방식:")
        grid.addWidget(self.lbl_pref_ext_type, 1, 0)
        self.combo_ext_type = QComboBox()
        self.combo_ext_type.addItems(["mV 타입 (아날로그 mV/V)", "펄스 타입 (엔코더 Pulse)"])
        self.combo_ext_type.currentIndexChanged.connect(self._on_pref_type_changed)
        grid.addWidget(self.combo_ext_type, 1, 1, 1, 3)

        self.lbl_pref_gl = QLabel("표점거리 GL (mm):")
        grid.addWidget(self.lbl_pref_gl, 2, 0)
        self.spin_ext_gl = QDoubleSpinBox()
        self.spin_ext_gl.setRange(1.0, 1000.0)
        self.spin_ext_gl.setDecimals(2)
        self.spin_ext_gl.setSingleStep(0.5)
        self.spin_ext_gl.setValue(50.0)
        self.spin_ext_gl.valueChanged.connect(self._on_pref_value_changed)
        grid.addWidget(self.spin_ext_gl, 2, 1)
        self.lbl_pref_gl.setBuddy(self.spin_ext_gl)

        # mV 타입 파라미터
        self.box_mv_params = QGroupBox("mV 타입 설정")
        mv_grid = QGridLayout(self.box_mv_params)
        mv_grid.setContentsMargins(14, 16, 14, 12)
        mv_grid.setHorizontalSpacing(12)
        mv_grid.setVerticalSpacing(8)

        self.lbl_pref_rated = QLabel("정격 출력 (mV/V):")
        mv_grid.addWidget(self.lbl_pref_rated, 0, 0)
        self.spin_rated = QDoubleSpinBox()
        self.spin_rated.setRange(0.1, 10.0)
        self.spin_rated.setDecimals(3)
        self.spin_rated.setSingleStep(0.1)
        self.spin_rated.setValue(2.0)
        self.spin_rated.valueChanged.connect(self._on_pref_value_changed)
        mv_grid.addWidget(self.spin_rated, 0, 1)

        self.lbl_pref_fs = QLabel("정격 변위 (mm):")
        mv_grid.addWidget(self.lbl_pref_fs, 0, 2)
        self.spin_ext_fs = QDoubleSpinBox()
        self.spin_ext_fs.setRange(0.1, 500.0)
        self.spin_ext_fs.setDecimals(2)
        self.spin_ext_fs.setSingleStep(0.5)
        self.spin_ext_fs.setValue(25.0)
        self.spin_ext_fs.valueChanged.connect(self._on_pref_value_changed)
        mv_grid.addWidget(self.spin_ext_fs, 0, 3)

        self.lbl_pref_exc = QLabel("여자 전압 (V):")
        mv_grid.addWidget(self.lbl_pref_exc, 1, 0)
        self.spin_ext_exc = QDoubleSpinBox()
        self.spin_ext_exc.setRange(1.0, 10.0)
        self.spin_ext_exc.setDecimals(1)
        self.spin_ext_exc.setSingleStep(0.5)
        self.spin_ext_exc.setValue(5.0)
        self.spin_ext_exc.valueChanged.connect(self._on_pref_value_changed)
        mv_grid.addWidget(self.spin_ext_exc, 1, 1)

        self.lbl_pref_cal = QLabel("교정 계수:")
        mv_grid.addWidget(self.lbl_pref_cal, 1, 2)
        self.spin_ext_cal = QDoubleSpinBox()
        self.spin_ext_cal.setRange(0.5, 2.0)
        self.spin_ext_cal.setDecimals(4)
        self.spin_ext_cal.setSingleStep(0.001)
        self.spin_ext_cal.setValue(1.0)
        self.spin_ext_cal.valueChanged.connect(self._on_pref_value_changed)
        mv_grid.addWidget(self.spin_ext_cal, 1, 3)

        self.lbl_pref_zero = QLabel("영점 오프셋 (mV):")
        mv_grid.addWidget(self.lbl_pref_zero, 2, 0)
        self.spin_ext_zero = QDoubleSpinBox()
        self.spin_ext_zero.setRange(-100.0, 100.0)
        self.spin_ext_zero.setDecimals(4)
        self.spin_ext_zero.setSingleStep(0.01)
        self.spin_ext_zero.setValue(0.0)
        self.spin_ext_zero.valueChanged.connect(self._on_pref_value_changed)
        mv_grid.addWidget(self.spin_ext_zero, 2, 1)
        grid.addWidget(self.box_mv_params, 3, 0, 1, 4)

        # 펄스 타입 파라미터
        self.box_pulse_params = QGroupBox("펄스 타입 설정")
        pulse_grid = QGridLayout(self.box_pulse_params)
        pulse_grid.setContentsMargins(14, 16, 14, 12)
        pulse_grid.setHorizontalSpacing(12)
        pulse_grid.setVerticalSpacing(8)

        self.lbl_pref_res = QLabel("분해능 (mm/pulse):")
        pulse_grid.addWidget(self.lbl_pref_res, 0, 0)
        self.spin_ext_res = QDoubleSpinBox()
        self.spin_ext_res.setRange(0.00001, 1.0)
        self.spin_ext_res.setDecimals(5)
        self.spin_ext_res.setSingleStep(0.0005)
        self.spin_ext_res.setValue(0.001)
        self.spin_ext_res.valueChanged.connect(self._on_pref_value_changed)
        pulse_grid.addWidget(self.spin_ext_res, 0, 1)

        self.chk_ext_invert = QCheckBox("방향 반전 (하강 시 감소)")
        self.chk_ext_invert.toggled.connect(self._on_pref_value_changed)
        pulse_grid.addWidget(self.chk_ext_invert, 1, 0, 1, 2)
        grid.addWidget(self.box_pulse_params, 4, 0, 1, 4)

        # 환산 결과 안내
        self.lbl_pref_hint = QLabel("")
        self.lbl_pref_hint.setStyleSheet("color: #475569; font-size: 8.5pt; font-weight: 600; background: transparent;")
        grid.addWidget(self.lbl_pref_hint, 5, 0, 1, 4)

        # 버튼
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_pref_save = QPushButton("설정 저장 및 적용")
        self.btn_pref_save.setMinimumWidth(190)
        self.btn_pref_save.setStyleSheet("background-color: #1D4ED8; color: #FFFFFF; font-weight: bold; min-height: 30px;")
        self.btn_pref_save.clicked.connect(lambda: self._save_preferences())

        self.btn_pref_default = QPushButton("기본값 복원")
        self.btn_pref_default.setMinimumWidth(120)
        self.btn_pref_default.setMinimumHeight(30)
        self.btn_pref_default.clicked.connect(lambda: self._restore_pref_defaults())

        self.btn_pref_tare = QPushButton("신율계 영점 맞춤")
        self.btn_pref_tare.setMinimumWidth(140)
        self.btn_pref_tare.setMinimumHeight(30)
        self.btn_pref_tare.clicked.connect(self._tare_extensometer)

        btn_row.addWidget(self.btn_pref_save)
        btn_row.addWidget(self.btn_pref_default)
        btn_row.addWidget(self.btn_pref_tare)
        btn_row.addStretch()
        grid.addLayout(btn_row, 6, 0, 1, 4)

        self.lbl_pref_dirty = QLabel("")
        self.lbl_pref_dirty.setStyleSheet("color: #B45309; font-size: 8.5pt; font-weight: 600; background: transparent;")
        grid.addWidget(self.lbl_pref_dirty, 7, 0, 1, 4)

        columns.addWidget(self.pref_ext_group, stretch=3)

        # ---------------- 오른쪽: 적용 상태 / 실시간 값 ----------------
        right_col = QVBoxLayout()
        right_col.setSpacing(14)

        self.pref_status_group = QGroupBox("현재 적용 상태")
        self.pref_status_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        status_layout = QVBoxLayout(self.pref_status_group)
        status_layout.setContentsMargins(16, 18, 16, 14)
        status_layout.setSpacing(8)
        self.lbl_pref_state = QLabel("")
        self.lbl_pref_state.setStyleSheet("color: #1D4ED8; font-size: 10pt; font-weight: 700; background: transparent;")
        self.lbl_pref_state.setWordWrap(True)
        self.lbl_pref_note = QLabel("")
        self.lbl_pref_note.setWordWrap(True)
        self.lbl_pref_note.setStyleSheet("color: #475569; font-size: 9pt; background: transparent;")
        status_layout.addWidget(self.lbl_pref_state)
        status_layout.addWidget(self.lbl_pref_note)
        right_col.addWidget(self.pref_status_group)

        self.pref_live_group = QGroupBox("신율계 실시간 값")
        self.pref_live_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        live_layout = QGridLayout(self.pref_live_group)
        live_layout.setContentsMargins(16, 18, 16, 14)
        live_layout.setHorizontalSpacing(12)
        live_layout.setVerticalSpacing(8)
        self.lbl_live_raw_title = QLabel("원시 신호")
        self.lbl_live_disp_title = QLabel("환산 변위")
        self.lbl_live_strain_title = QLabel("변형률")
        self.lbl_live_raw = QLabel("-")
        self.lbl_live_disp = QLabel("-")
        self.lbl_live_strain = QLabel("-")
        for row, (title, value) in enumerate(
            ((self.lbl_live_raw_title, self.lbl_live_raw),
             (self.lbl_live_disp_title, self.lbl_live_disp),
             (self.lbl_live_strain_title, self.lbl_live_strain))
        ):
            title.setStyleSheet("color: #64748B; font-size: 9pt; font-weight: 600; background: transparent;")
            value.setStyleSheet("color: #0F172A; font-size: 11pt; font-weight: 700; font-family: 'Consolas', monospace; background: transparent;")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            live_layout.addWidget(title, row, 0)
            live_layout.addWidget(value, row, 1)
        live_layout.setColumnStretch(1, 1)
        right_col.addWidget(self.pref_live_group)
        right_col.addStretch()

        columns.addLayout(right_col, stretch=2)
        layout.addLayout(columns)
        layout.addStretch()
        # 위젯 초기값을 저장된 환경 설정으로 맞춤
        for spin in (self.spin_rated, self.spin_ext_fs, self.spin_ext_exc, self.spin_ext_cal,
                     self.spin_ext_zero, self.spin_ext_res, self.spin_ext_gl):
            spin.setFixedWidth(120)
        mv_grid.setColumnStretch(3, 1)
        pulse_grid.setColumnStretch(1, 1)

        self._sync_pref_widgets_from_model()
        self._apply_pref_group_state()
        self._update_pref_hint()
        self._refresh_pref_state()
        self._update_ext_tile_visibility()
        scroll.setWidget(tab)
        return scroll

    # ------------------------------------------------------------------
    # 환경 설정 동작
    # ------------------------------------------------------------------
    def _sync_pref_widgets_from_model(self):
        """저장된 환경 설정값을 화면 위젯에 반영"""
        ext = self.prefs.ext
        self.rb_ext_on.setChecked(ext.enabled)
        self.rb_ext_off.setChecked(not ext.enabled)
        self.combo_ext_type.setCurrentIndex(0 if ext.is_mv else 1)
        self.spin_ext_gl.setValue(ext.gauge_length_mm)
        self.spin_rated.setValue(ext.rated_output_mv_v)
        self.spin_ext_fs.setValue(ext.full_scale_mm)
        self.spin_ext_exc.setValue(ext.excitation_v)
        self.spin_ext_cal.setValue(ext.calib_factor)
        self.spin_ext_zero.setValue(ext.zero_offset_mv)
        self.spin_ext_res.setValue(ext.resolution_mm_per_pulse)
        self.chk_ext_invert.setChecked(ext.direction_invert)
        self._update_pref_dirty()

    def _ext_settings_from_widgets(self) -> ExtensometerSettings:
        """화면 위젯 값으로 신율계 설정 구성"""
        return ExtensometerSettings(
            enabled=self.rb_ext_on.isChecked(),
            ext_type=ExtensometerType.MV.value if self.combo_ext_type.currentIndex() == 0 else ExtensometerType.PULSE.value,
            gauge_length_mm=self.spin_ext_gl.value(),
            rated_output_mv_v=self.spin_rated.value(),
            full_scale_mm=self.spin_ext_fs.value(),
            excitation_v=self.spin_ext_exc.value(),
            calib_factor=self.spin_ext_cal.value(),
            zero_offset_mv=self.spin_ext_zero.value(),
            resolution_mm_per_pulse=self.spin_ext_res.value(),
            direction_invert=self.chk_ext_invert.isChecked(),
            zero_offset_pulse=self.prefs.ext.zero_offset_pulse,
        )

    def _apply_pref_group_state(self):
        """사용 여부/신호 방식에 따른 입력 활성화 및 표시 전환"""
        on = self.rb_ext_on.isChecked()
        is_mv = self.combo_ext_type.currentIndex() == 0

        self.combo_ext_type.setEnabled(on)
        self.spin_ext_gl.setEnabled(on)
        for w in (self.spin_rated, self.spin_ext_fs, self.spin_ext_exc, self.spin_ext_cal, self.spin_ext_zero):
            w.setEnabled(on and is_mv)
        for w in (self.spin_ext_res, self.chk_ext_invert):
            w.setEnabled(on and not is_mv)

        self.box_mv_params.setVisible(on and is_mv)
        self.box_pulse_params.setVisible(on and not is_mv)
        self.lbl_pref_hint.setVisible(on)
        self.btn_pref_tare.setEnabled(on)

    def _on_pref_ext_toggled(self, btn_id: int, checked: bool):
        if not checked:
            return
        self._apply_pref_group_state()
        self._update_pref_hint()
        self._update_pref_dirty()

    def _on_pref_type_changed(self, index: int):
        self._apply_pref_group_state()
        self._update_pref_hint()
        self._update_pref_dirty()

    def _on_pref_value_changed(self, *args):
        self._update_pref_hint()
        self._update_pref_dirty()

    def _update_pref_hint(self):
        """정격 신호량 / 분해능 환산 결과 안내"""
        t = TRANSLATIONS[self.current_lang]
        if self.combo_ext_type.currentIndex() == 0:
            fs_mv = max(0.0001, self.spin_rated.value() * self.spin_ext_exc.value())
            self.lbl_pref_hint.setText(t["pref_span_hint"].format(mv=fs_mv, mm=self.spin_ext_fs.value()))
        else:
            res = max(0.000001, self.spin_ext_res.value())
            self.lbl_pref_hint.setText(f"{res:.5f} mm/pulse · {1.0 / res:,.0f} pulse/mm")

    def _update_pref_dirty(self):
        """저장값과 화면값 차이 안내"""
        t = TRANSLATIONS[self.current_lang]
        dirty = (self._ext_settings_from_widgets() != self.prefs.ext)
        self.lbl_pref_dirty.setText(t["pref_unapplied"] if dirty else "")
        self.lbl_pref_dirty.setVisible(dirty)

    def _refresh_pref_state(self):
        """현재 적용(저장)된 설정 요약 표시"""
        t = TRANSLATIONS[self.current_lang]
        ext = self.prefs.ext
        if ext.enabled:
            type_txt = t["pref_ext_mv"] if ext.is_mv else t["pref_ext_pulse"]
            self.lbl_pref_state.setText(t["pref_state_on"].format(type=type_txt, gl=ext.gauge_length_mm))
            self.lbl_pref_note.setText(t["pref_note"])
            self.pref_live_group.setVisible(True)
        else:
            self.lbl_pref_state.setText(t["pref_state_off"])
            self.lbl_pref_note.setText(t["pref_note_off"])
            self._set_ext_live_text(None)
        self._adjust_wrapped_labels()

    def _adjust_wrapped_labels(self):
        """줄바꿈 라벨이 잘리지 않도록 필요한 높이를 계산해 최소 높이 설정"""
        if not hasattr(self, "lbl_pref_note"):
            return
        for label in (self.lbl_pref_state, self.lbl_pref_note):
            width = label.width()
            if width <= 0:
                width = max(240, self.pref_status_group.width() - 40)
            fm = label.fontMetrics()
            rect = fm.boundingRect(QRect(0, 0, width, 10000), Qt.TextFlag.TextWordWrap, label.text())
            label.setMinimumHeight(max(rect.height() + 4, fm.lineSpacing() + 4))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._adjust_wrapped_labels()
        self._sync_scroll_min_heights()
        self._fit_batch_metric_column()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_scroll_min_heights()
        self._adjust_wrapped_labels()

    def _sync_scroll_min_heights(self):
        """스크롤 탭 내용이 압축되어 위젯이 겹치지 않도록 실제 필요 높이를 최소 높이로 지정"""
        for attr in ("hw_scroll", "pref_scroll"):
            scroll = getattr(self, attr, None)
            if scroll is None:
                continue
            content = scroll.widget()
            if content is None or content.layout() is None:
                continue
            need = content.layout().sizeHint().height()
            if need > 0 and content.minimumHeight() != need:
                content.setMinimumHeight(need)

        # 대시보드(오른쪽 패널)는 위젯이 자연스럽게 늘어나는 구조이므로
        # "최소 필요 높이"까지만 고정한다 (그래프가 과도하게 커져 스크롤이 생기는 것 방지)
        scroll = getattr(self, "dash_scroll", None)
        if scroll is not None:
            content = scroll.widget()
            if content is not None and content.layout() is not None:
                need = content.minimumSizeHint().height()
                if need > 0 and content.minimumHeight() != need:
                    content.setMinimumHeight(need)

    def _apply_preferences_language(self, t: dict):
        """환경 설정 탭 다국어 갱신"""
        self.pref_ext_group.setTitle(t["pref_ext_group"])
        self.lbl_pref_ext_use.setText(t["pref_ext_use"])
        self.rb_ext_off.setText(t["pref_ext_off"])
        self.rb_ext_on.setText(t["pref_ext_on"])
        self.lbl_pref_ext_type.setText(t["pref_ext_type"])
        self.combo_ext_type.setItemText(0, t["pref_ext_mv"])
        self.combo_ext_type.setItemText(1, t["pref_ext_pulse"])
        self.lbl_pref_gl.setText(t["pref_gl"])
        self.box_mv_params.setTitle(t["pref_sec_mv"])
        self.lbl_pref_rated.setText(t["pref_rated"])
        self.lbl_pref_fs.setText(t["pref_fs"])
        self.lbl_pref_exc.setText(t["pref_exc"])
        self.lbl_pref_cal.setText(t["pref_cal"])
        self.lbl_pref_zero.setText(t["pref_zero_mv"])
        self.box_pulse_params.setTitle(t["pref_sec_pulse"])
        self.lbl_pref_res.setText(t["pref_res"])
        self.chk_ext_invert.setText(t["pref_invert"])
        self.btn_pref_save.setText(t["pref_save"])
        self.btn_pref_default.setText(t["pref_default"])
        self.btn_pref_tare.setText(t["pref_tare_ext"])
        self.pref_status_group.setTitle(t["pref_status_group"])
        self.pref_live_group.setTitle(t["pref_live_group"])
        self.lbl_live_raw_title.setText(t["pref_live_raw"])
        self.lbl_live_disp_title.setText(t["pref_live_disp"])
        self.lbl_live_strain_title.setText(t["pref_live_strain"])
        self._update_pref_hint()
        self._update_pref_dirty()
        self._refresh_pref_state()
        self._adjust_wrapped_labels()

    def _update_ext_tile_visibility(self):
        """신율계 사용 설정에 따라 대시보드 표시 전환"""
        self.tile_ext.setVisible(self.prefs.ext.enabled)
        self._apply_strain_tile_label()
        self._apply_strain_source_label()

    def _apply_strain_tile_label(self):
        t = TRANSLATIONS[self.current_lang]
        self.lbl_tile_strain.setText(t["tile_strain_ext"] if self.prefs.ext.enabled else t["tile_strain_ch"])

    def _apply_strain_source_label(self, source_key: Optional[str] = None):
        """결과표 아래 변형률 측정 소스 표시"""
        t = TRANSLATIONS[self.current_lang]
        ext = self.prefs.ext
        key = source_key
        if key is None:
            key = ("src_mv" if ext.is_mv else "src_pulse") if ext.enabled else "src_crosshead"
        self.lbl_strain_source.setText(t["strain_source_label"].format(src=t[key]))

    def _save_preferences(self, silent: bool = False) -> bool:
        """환경 설정 저장 및 계측 드라이버에 즉시 적용"""
        t = TRANSLATIONS[self.current_lang]
        settings = self._ext_settings_from_widgets()
        self.prefs.data.ext = settings
        ok = self.prefs.save()
        if not ok:
            if silent:
                return False
            QMessageBox.critical(self, t["tab_preferences"], "환경 설정 파일을 저장하지 못했습니다.")
            return False

        self.simulator.set_extensometer(settings)
        self.serial_driver.set_extensometer(settings)
        self._update_ext_tile_visibility()
        self._refresh_pref_state()
        self._update_pref_dirty()
        self._set_ext_live_text(None)
        self.statusBar().showMessage(t["pref_saved"])
        if not silent:
            QMessageBox.information(self, t["tab_preferences"], t["pref_saved"])
        return True

    def _restore_pref_defaults(self, silent: bool = False) -> bool:
        """환경 설정을 기본값으로 복원"""
        t = TRANSLATIONS[self.current_lang]
        if not silent:
            reply = QMessageBox.question(
                self, t["tab_preferences"],
                "신율계 설정을 기본값으로 되돌리시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False

        self.prefs.data.ext = ExtensometerSettings()
        self._sync_pref_widgets_from_model()
        self._apply_pref_group_state()
        ok = self._save_preferences(silent=True)
        if ok:
            self.statusBar().showMessage(t["pref_reset_done"])
            if not silent:
                QMessageBox.information(self, t["tab_preferences"], t["pref_reset_done"])
        return ok

    def _tare_extensometer(self):
        """현재 신율계 원시값을 영점으로 설정하고 저장"""
        t = TRANSLATIONS[self.current_lang]
        self.active_driver.tare_extensometer()
        driver_ext = getattr(self.active_driver, "ext", None)
        if driver_ext is not None:
            self.prefs.data.ext = driver_ext.copy()
            self.prefs.save()
            self.spin_ext_zero.blockSignals(True)
            self.spin_ext_zero.setValue(self.prefs.ext.zero_offset_mv)
            self.spin_ext_zero.blockSignals(False)
        self._set_ext_live_text(None)
        self.statusBar().showMessage(t["pref_tare_done"])

    def _set_ext_live_text(self, point: Optional[DataPoint]):
        """환경 설정 탭의 신율계 실시간 값 표시"""
        ext = self.prefs.ext
        if not ext.enabled:
            self.lbl_live_raw.setText("-")
            self.lbl_live_disp.setText("-")
            self.lbl_live_strain.setText("-")
            return
        if point is None or not point.ext_valid:
            unit = "mV" if ext.is_mv else "pulse"
            self.lbl_live_raw.setText(f"- {unit}")
            self.lbl_live_disp.setText("- mm")
            self.lbl_live_strain.setText("- %")
            return
        if ext.is_mv:
            self.lbl_live_raw.setText(f"{point.ext_raw:.4f} mV")
        else:
            self.lbl_live_raw.setText(f"{point.ext_raw:,.0f} pulse")
        self.lbl_live_disp.setText(f"{point.ext_disp_mm:.3f} mm")
        self.lbl_live_strain.setText(f"{point.ext_strain_pct:.2f} %")

    def _create_tile(self, label_text: str, default_val: str, unit_text: str):
        tile = QFrame()
        tile.setProperty("class", "readout-tile")
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        lbl_title = QLabel(label_text)
        lbl_title.setProperty("class", "readout-label")
        layout.addWidget(lbl_title)

        lbl_val = QLabel(default_val)
        lbl_val.setProperty("class", "readout-value")
        lbl_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(lbl_val)

        lbl_unit = QLabel(unit_text)
        lbl_unit.setProperty("class", "readout-unit")
        lbl_unit.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(lbl_unit)

        return tile, lbl_title, lbl_val

    def _on_test_mode_toggled(self, btn_id: int, checked: bool):
        if not checked:
            return
        is_bend = (btn_id == 2)
        is_hold = (btn_id == 3)
        is_seq = (btn_id == 4)

        # 굽힘·시퀀스는 변위 속도 제어만 지원한다
        if hasattr(self, "combo_control_mode"):
            self.combo_control_mode.setEnabled(not (is_bend or is_seq))
            if (is_bend or is_seq) and self.combo_control_mode.currentIndex() != 0:
                self.combo_control_mode.setCurrentIndex(0)
        # 하중 유지 제어 중에 다른 시험 모드로 바꾸면 하중 속도 제어로 전환
        if not is_hold and hasattr(self, "combo_control_mode") \
                and self.combo_control_mode.currentIndex() == 3:
            self.combo_control_mode.setCurrentIndex(1)

        self.lbl_drop.setVisible(not is_hold)
        self.spin_drop.setVisible(not is_hold)

        self.lbl_bend_type.setVisible(is_bend)
        self.combo_bend_type.setVisible(is_bend)
        self.lbl_span.setVisible(is_bend)
        self.spin_span.setVisible(is_bend)

        self.lbl_hold_type.setVisible(is_hold)
        self.combo_hold_type.setVisible(is_hold)
        self.lbl_hold_val.setVisible(is_hold)
        self.spin_hold_val.setVisible(is_hold)
        self.lbl_hold_dur.setVisible(is_hold)
        self.spin_hold_dur.setVisible(is_hold)

        self.sequence_group.setVisible(is_seq)

    def _on_specimen_type_changed(self, index: int):
        is_flat = (index == 0)
        t = TRANSLATIONS[self.current_lang]
        self.lbl_width.setText(t["spec_width"] if is_flat else t["spec_dia"])
        self.lbl_thick.setVisible(is_flat)
        self.spin_thick.setVisible(is_flat)

    def _get_current_specimen(self) -> Specimen:
        stype = SpecimenType.FLAT if self.combo_type.currentIndex() == 0 else SpecimenType.ROUND
        return Specimen(
            specimen_id=self.edit_specimen_id.text().strip(),
            material=self.edit_material.text().strip(),
            specimen_type=stype,
            width_mm=self.spin_width.value(),
            thickness_mm=self.spin_thick.value() if stype == SpecimenType.FLAT else 0.0,
            diameter_mm=self.spin_width.value() if stype == SpecimenType.ROUND else 0.0,
            gauge_length_mm=self.spin_l0.value()
        )

    def _get_current_config(self) -> TestConfig:
        if self.rb_tensile.isChecked():
            mode = TestMode.TENSILE
        elif self.rb_compression.isChecked():
            mode = TestMode.COMPRESSION
        elif self.rb_bending.isChecked():
            mode = TestMode.BENDING
        elif self.rb_sequence.isChecked():
            mode = TestMode.SEQUENCE
        else:
            mode = TestMode.HOLDING

        btype = BendingType.THREE_POINT if self.combo_bend_type.currentIndex() == 0 else BendingType.FOUR_POINT
        htype = HoldingType.LOAD_HOLD if self.combo_hold_type.currentIndex() == 0 else HoldingType.DISP_HOLD

        # 하중·응력 속도 제어는 소프트 PID 컨트롤러가 매 주기 속도를 정한다
        control = self._selected_control_mode()
        uses_pid = control is not ControlMode.DISP and \
            mode in (TestMode.TENSILE, TestMode.COMPRESSION, TestMode.HOLDING)

        # 곡선 해상도 확보: 시편 표점거리 기준 약 0.02 mm 간격으로 샘플링한다 (20~250 Hz)
        speed_mm_min = self.spin_speed.value()
        samples_per_second = int(round((speed_mm_min / 60.0) / 0.02))
        sampling_hz = 200 if uses_pid else max(20, min(250, samples_per_second))

        return TestConfig(
            mode=mode,
            test_speed_mm_min=speed_mm_min,
            control_mode=control.value if uses_pid else ControlMode.DISP.value,
            target_rate=self.spin_target_rate.value() if uses_pid else 0.0,
            target_load_n=self.spin_hold_val.value() if uses_pid and mode == TestMode.HOLDING else 0.0,
            pid_profile_id=self._selected_pid_profile_id(),
            pid_gains={
                "kp": self.spin_kp.value(),
                "ki": self.spin_ki.value(),
                "kd": self.spin_kd.value(),
            },
            comm_delay_ms=self.spin_ctl_delay.value(),
            control_rate_hz=self.spin_ctl_hz.value(),
            live_speed_control=self.chk_live_speed.isChecked(),
            fracture_drop_ratio=self.spin_drop.value() / 100.0,
            max_displacement_mm=50.0,
            sampling_rate_hz=sampling_hz,
            bending_type=btype,
            span_length_mm=self.spin_span.value(),
            holding_type=htype,
            target_holding_val=self.spin_hold_val.value(),
            holding_duration_s=self.spin_hold_dur.value(),
            ext=self.prefs.ext.copy(),
            sequence=self.sequence_program.copy(),
        )

    def _start_test(self):
        self.data_points.clear()
        self._clear_results_table()
        self._live_record_seq = None
        if HAS_PYQTGRAPH:
            self.plot_curve.setData([], [])
            self._replot_graph()

        specimen = self._get_current_specimen()
        config = self._get_current_config()
        self._active_specimen = specimen
        # 어시스턴트 카드가 열린 채로 좌측 [시험 시작]을 누르면 카드는 닫는다
        if getattr(self, "assistant_panel", None) is not None \
                and self.assistant_panel.state in ("plan", "done"):
            self.assistant_panel.reset()
            self._assistant_auto_export = False

        t = TRANSLATIONS[self.current_lang]
        if config.mode == TestMode.SEQUENCE and not config.sequence.is_valid():
            QMessageBox.warning(self, t["seq_group"], t["seq_empty_error"])
            return

        # 신율계 설정을 활성 드라이버에 적용하고 표시 상태 초기화
        self.active_driver.set_extensometer(config.ext)
        self._update_ext_tile_visibility()
        self.lbl_ext_val.setText("0.000")
        self._set_ext_live_text(None)
        self._apply_strain_source_label()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_excel.setEnabled(False)
        self.btn_pdf.setEnabled(False)

        t = TRANSLATIONS[self.current_lang]
        msg = t["status_running"].format(mode=config.mode.value, specimen=specimen.specimen_id)
        self.statusBar().showMessage(msg)

        # 실장비는 인디케이터가 SPD 명령을 받는지 확인된 경우에만 실시간 제어한다
        self.serial_driver.supports_live_speed_control = self.chk_live_speed.isChecked()
        if config.uses_pid_control:
            self.ctl_timer.start()
        else:
            self.ctl_timer.stop()
            self.lbl_ctl_status.setText(f'{t["ctl_status"]} {t["ctl_status_idle"]}')

        self.active_driver.start_test(specimen, config)

    def _stop_test(self):
        self.ctl_timer.stop()
        self.active_driver.stop_test()
        self._refresh_control_status()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.statusBar().showMessage("시험 중단됨 (Stopped)")

    def _return_origin(self):
        self.lbl_load_val.setText("0.0")
        self.lbl_disp_val.setText("0.000")
        self.lbl_ext_val.setText("0.000")
        self.active_driver.return_to_origin()
        self.statusBar().showMessage("원점 복귀 완료 (Zero Return Complete)")

    def _reset_data(self):
        self.data_points.clear()
        self.current_result = None
        self._live_record_seq = None
        self._clear_results_table()
        if HAS_PYQTGRAPH:
            self.plot_curve.setData([], [])
        self.lbl_load_val.setText("0.0")
        self.lbl_disp_val.setText("0.000")
        self.lbl_ext_val.setText("0.000")
        self.lbl_stress_val.setText("0.0")
        self.lbl_strain_val.setText("0.00")
        self._set_ext_live_text(None)
        self._apply_strain_source_label()
        self.btn_excel.setEnabled(False)
        self.btn_pdf.setEnabled(False)
        self.statusBar().showMessage("데이터 초기화 완료 (Reset Complete)")

    def _on_data_received(self, point: DataPoint):
        self.data_points.append(point)
        self.lbl_load_val.setText(f"{point.load_n:,.1f}")
        self.lbl_disp_val.setText(f"{point.displacement_mm:.3f}")
        self.lbl_stress_val.setText(f"{point.stress_mpa:.1f}")
        self.lbl_strain_val.setText(f"{point.strain_pct:.2f}")
        if self.prefs.ext.enabled and point.ext_valid:
            self.lbl_ext_val.setText(f"{point.ext_disp_mm:.3f}")
        self._set_ext_live_text(point)

        if HAS_PYQTGRAPH and len(self.data_points) % 2 == 0:
            self._replot_graph()

    def _on_test_completed(self, reason: str):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_excel.setEnabled(True)
        self.btn_pdf.setEnabled(True)
        self._last_completion_reason = reason
        self.ctl_timer.stop()

        specimen = self._get_current_specimen()
        config = self._get_current_config()
        self._refresh_control_status()
        self._last_tracking = self._tracking_summary(config, specimen)
        t = TRANSLATIONS[self.current_lang]

        step_events = list(getattr(self.active_driver, "step_events", []) or [])
        self.current_result = MaterialCalculator.calculate(
            specimen, config, self.data_points, reason, sequence_steps=step_events
        )
        self._update_results_table(self.current_result, reason)

        # 1) 시험 이력 자동 저장 (SHA-256 무결성 해시 + 체인)
        summary = None
        try:
            summary = self.history.save(
                specimen, config, self.current_result, self.data_points,
                completion_reason=reason,
                calibration=self._calibration_snapshot(),
                sequence_events=step_events,
            )
        except Exception as exc:  # 저장 실패가 시험 결과 표시를 막지 않는다
            print(f"[MainWindow] 이력 저장 예외: {exc}")

        # 2) 세션(오버레이)에 시편 추가
        record = self.session.add(
            specimen, config, self.current_result, self.data_points,
            completion_reason=reason,
            history_id=summary.record_id if summary else "",
            integrity_digest=summary.digest if summary else "",
            step_events=step_events,
        )
        self._live_record_seq = record.seq
        self._refresh_session_table()
        self._refresh_batch_table()
        self._replot_graph()
        self._update_history_button()

        # 변형률 측정 소스 표시 (실제 시험에 적용된 소스)
        source_key = "src_crosshead"
        if self.current_result.ext_enabled:
            source_key = "src_mv" if self.current_result.ext_type == ExtensometerType.MV.value else "src_pulse"
            if self.current_result.strain_source not in (
                MaterialCalculator.EXT_SOURCE_MV, MaterialCalculator.EXT_SOURCE_PULSE
            ):
                source_key = "src_crosshead"
                self.statusBar().showMessage(t["ext_lost_warning"])
        self._apply_strain_source_label(source_key)

        msg = t["status_done"].format(reason=reason, count=len(self.data_points))
        self.statusBar().showMessage(msg)

        # 3) 어시스턴트로 시작한 시험이면 로우데이터(Excel) · 성적서(PDF) 자동 저장
        export_paths: dict = {}
        export_error = ""
        if self._assistant_auto_export:
            export_paths, export_error = self._finish_assistant_export(specimen, config)
            self._assistant_auto_export = False
        elif getattr(self, "assistant_panel", None) is not None \
                and self.assistant_panel.state == "running":
            # 자동 저장을 끄고 시작한 경우에도 카드는 완료 상태로 닫는다
            self.assistant_panel.mark_completed({}, self.current_result.peak_load_n,
                                                self.current_result.peak_stress_mpa,
                                                specimen.specimen_id)

        # 4) 시편 번호 자동 증가 (배치 연속 시험)
        if self.chk_auto_id.isChecked():
            self._next_specimen_id()

        integrity_note = "-"
        if summary is not None:
            integrity_note = t["history_integrity_ok"]
        else:
            integrity_note = t["hist_save_failed"]

        lines = [
            f"상태: {reason}",
            f"최대 하중: {self.current_result.peak_load_n:,.1f} N",
            f"강도: {self.current_result.peak_stress_mpa:.2f} MPa",
            f"시편 세션: {self.session.records[-1].session_label if self.session.records else '-'}",
            f"이력 · 무결성: {integrity_note}",
        ]
        if self.current_result.sequence_steps:
            lines.append(f"시퀀스: {self.current_result.sequence_name or '-'}")
        if export_paths:
            lines.append(f"로우데이터(Excel): {os.path.normpath(export_paths.get('excel', ''))}")
            lines.append(f"성적서(PDF): {os.path.normpath(export_paths.get('pdf', ''))}")
        elif export_error:
            lines.append(f"자동 저장 실패: {export_error}")
        if self._last_tracking:
            lines.append(self._last_tracking)
        QMessageBox.information(self, "시험 완료", "시험이 완료되었습니다.\n" + "\n".join(lines))

    def _tracking_summary(self, config: TestConfig, specimen: Specimen) -> str:
        """하중·응력 속도 제어 시험의 추종 오차 · 오버슈트 요약 문장"""
        trace = list(getattr(self.active_driver, "control_trace", []) or [])
        if not config.uses_pid_control or not trace:
            return ""
        target_rate_n_s = 0.0
        control = str(config.control_mode).upper()
        if control == ControlMode.STRESS_RATE.value:
            target_rate_n_s = config.target_rate * specimen.cross_sectional_area_mm2
        elif control in (ControlMode.LOAD_RATE.value, ControlMode.LOAD_HOLD.value):
            target_rate_n_s = config.target_rate / 60.0
        target_load = config.target_holding_val if control == ControlMode.LOAD_HOLD.value else 0.0
        metrics = evaluate_tracking(trace, target_rate_n_s=target_rate_n_s,
                                    target_load_n=target_load)
        t = TRANSLATIONS[self.current_lang]
        return t["ctl_result"].format(
            follow=metrics["follow_error_pct"],
            over=metrics["overshoot_pct"],
            hold=metrics["hold_error_pct"],
        )

    # ------------------------------------------------------------------
    # 그래프 (단일 곡선 + 다중 시편 오버레이 + 시퀀스 단계 표시)
    # ------------------------------------------------------------------
    def _clear_overlay_items(self):
        if not HAS_PYQTGRAPH or not hasattr(self, "plot_widget"):
            return
        for item in self._overlay_items + self._step_markers:
            try:
                self.plot_widget.removeItem(item)
            except Exception:
                pass
        self._overlay_items = []
        self._step_markers = []

    @staticmethod
    def _points_xy(points: List[DataPoint], mode: str):
        """곡선 좌표 (ss: 응력-변형률, ld: 하중-변위) - LD 는 크로스헤드 변위 기준"""
        if mode == "ld":
            return [p.displacement_mm for p in points], [p.load_n for p in points]
        return [p.strain_pct for p in points], [p.stress_mpa for p in points]

    def _replot_graph(self):
        if not HAS_PYQTGRAPH or not hasattr(self, "plot_widget"):
            return
        t = TRANSLATIONS[self.current_lang]
        mode = "ss" if self.rb_graph_ss.isChecked() else "ld"
        if mode == "ss":
            self.plot_widget.setLabel('bottom', t["axis_strain"])
            self.plot_widget.setLabel('left', t["axis_stress"])
        else:
            self.plot_widget.setLabel('bottom', t["axis_disp"])
            self.plot_widget.setLabel('left', t["axis_load"])

        self._clear_overlay_items()

        # 1) 이전 시편 오버레이 (보기 체크된 시편만)
        for record in self.session.visible_records:
            if len(record.points) < 2:
                continue
            xs, ys = record.curve(mode)
            item = self.plot_widget.plot(xs, ys, pen=pg.mkPen(color=record.color, width=1.5))
            self._overlay_items.append(item)

        # 2) 현재 시험 곡선 (아직 세션에 들어가지 않은 진행 중 시험만 별도로 그린다)
        if self.data_points:
            if self._live_record_seq is None:
                xs, ys = self._points_xy(self.data_points, mode)
                self.plot_curve.setData(xs, ys)
            else:
                self.plot_curve.setData([], [])
            x_values, y_values = self._points_xy(self.data_points, mode)
            self._draw_step_markers(mode, x_values, y_values)
        else:
            self.plot_curve.setData([], [])

    def _draw_step_markers(self, mode: str, xs: List[float], ys: List[float]):
        """시퀀스 단계 시작 지점을 세로 점선 + S1/S2 표시로 그린다"""
        if not self.current_result or not self.current_result.sequence_steps or not self.data_points:
            return
        top = max(ys) if ys else 1.0
        x_max = max(xs) if xs else 1.0
        for ev in self.current_result.sequence_steps:
            start = float(ev.get("started_at", 0.0) or 0.0)
            point = min(self.data_points, key=lambda p: abs(p.time_s - start))
            x = point.displacement_mm if mode == "ld" else point.strain_pct
            line = pg.InfiniteLine(
                pos=x, angle=90,
                pen=pg.mkPen(color="#94A3B8", width=1, style=Qt.PenStyle.DashLine),
            )
            self.plot_widget.addItem(line)
            self._step_markers.append(line)
            # 오른쪽 끝에 붙는 단계는 라벨을 왼쪽으로 붙이고, 나머지는 선에서 살짝 띄운다
            if x_max > 0 and x > x_max * 0.92:
                anchor, offset = (1, 0), -x_max * 0.006
            else:
                anchor, offset = (0, 0), x_max * 0.006
            label = pg.TextItem(
                html=f'<span style="font-size:7pt; color:#475569;">S{int(ev.get("index", 0)) + 1}</span>',
                anchor=anchor,
            )
            # 단계 시작점이 가까우면 라벨이 겹치므로 계단식으로 높이를 달리 둔다
            stagger = 0.045 * (int(ev.get("index", 0)) % 4)
            label.setPos(x + offset, top * (0.03 + stagger))
            self.plot_widget.addItem(label)
            self._step_markers.append(label)

    def _clear_results_table(self):
        for col in range(len(self.RESULT_COLUMNS)):
            self.table_results.setItem(0, col, QTableWidgetItem("-"))
            if self.table_results.item(0, col):
                self.table_results.item(0, col).setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    def _update_results_table(self, res: TestResult, reason: str):
        t = TRANSLATIONS[self.current_lang]
        status_txt = t["status_fractured"] if res.is_fractured else t["status_completed"]
        vals = [
            f"{res.peak_load_n:,.1f}",
            f"{res.peak_stress_mpa:.2f}",
            f"{res.yield_stress_mpa:.2f}",
            f"{res.elastic_modulus_gpa:.2f}",
            f"{res.elongation_pct:.2f}",
            f"{res.break_displacement_mm:.3f}",
            f"{res.energy_joule:.2f}",
            status_txt
        ]
        for col, val in enumerate(vals):
            item = QTableWidgetItem(val)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_results.setItem(0, col, item)

    # ------------------------------------------------------------------
    # 시편 세션 / 다단계 시퀀스 / 배치 통계
    # ------------------------------------------------------------------
    def _refresh_sequence_view(self):
        """시퀀스 단계 요약 목록 갱신"""
        if not hasattr(self, "list_sequence"):
            return
        t = TRANSLATIONS[self.current_lang]
        program = self.sequence_program
        self.lbl_seq_count.setText(t["seq_count"].format(n=len(program.steps), name=program.name))
        self.list_sequence.clear()
        if not program.steps:
            self.list_sequence.addItem(QListWidgetItem(t["seq_summary_empty"]))
            return
        for index, step in enumerate(program.steps):
            item = QListWidgetItem(f"{index + 1}.  {step.describe(self.current_lang)}")
            item.setToolTip(t["seq_hint"])
            self.list_sequence.addItem(item)

    def _edit_sequence(self):
        """시퀀스 편집 다이얼로그"""
        t = TRANSLATIONS[self.current_lang]
        dialog = SequenceDialog(self.sequence_program, self.current_lang, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            program = dialog.result_program()
            if program.is_valid():
                self.sequence_program = program
                self._refresh_sequence_view()
                self.statusBar().showMessage(
                    t["seq_count"].format(n=len(program.steps), name=program.name)
                )

    def _refresh_session_table(self):
        """세션 시편 목록 (보기 체크박스 + 색상 범례)"""
        if not hasattr(self, "table_session"):
            return
        t = TRANSLATIONS[self.current_lang]
        self.table_session.blockSignals(True)
        self.table_session.setRowCount(0)
        for record in self.session.records:
            row = self.table_session.rowCount()
            self.table_session.insertRow(row)

            check = QTableWidgetItem("")
            check.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            check.setCheckState(
                Qt.CheckState.Checked if record.visible else Qt.CheckState.Unchecked
            )
            check.setData(Qt.ItemDataRole.UserRole, record.seq)
            self.table_session.setItem(row, 0, check)

            label = QTableWidgetItem(record.session_label)
            label.setForeground(QBrush(QColor(record.color)))
            bold = QFont()
            bold.setBold(True)
            label.setFont(bold)
            label.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setToolTip(
                f"{record.specimen_id} · {mode_display(record.test_mode, self.current_lang)}\n"
                f"{record.completed_at}"
                + (f"\n{record.history_id}" if record.history_id else "")
            )
            self.table_session.setItem(row, 1, label)

            spec_item = QTableWidgetItem(record.specimen_id)
            spec_item.setToolTip(record.specimen.material if record.specimen else "")
            self.table_session.setItem(row, 2, spec_item)

            pmax = QTableWidgetItem(f"{record.result.peak_load_n:,.1f}")
            pmax.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table_session.setItem(row, 3, pmax)

        self.table_session.blockSignals(False)
        has_records = len(self.session) > 0
        for btn in (self.btn_session_show_all, self.btn_session_hide_all,
                    self.btn_session_clear):
            btn.setEnabled(has_records)
        self.btn_session_remove.setEnabled(False)
        self._refresh_batch_table()

    def _on_session_item_changed(self, item: QTableWidgetItem):
        if item is None or item.column() != 0:
            return
        seq = item.data(Qt.ItemDataRole.UserRole)
        if seq is None:
            return
        if self.session.set_visible(int(seq), item.checkState() == Qt.CheckState.Checked):
            self._refresh_batch_table()
            self._replot_graph()

    def _selected_session_seq(self) -> Optional[int]:
        row = self.table_session.currentRow()
        if row < 0:
            return None
        item = self.table_session.item(row, 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def _set_all_session_visible(self, visible: bool):
        self.session.set_all_visible(visible)
        self._refresh_session_table()
        self._replot_graph()

    def _remove_selected_session(self):
        seq = self._selected_session_seq()
        if seq is None:
            return
        self.session.remove(seq)
        self._refresh_session_table()
        self._replot_graph()

    def _clear_session(self):
        self.session.clear()
        self._refresh_session_table()
        self._replot_graph()

    def _fit_batch_metric_column(self):
        """창 폭에 맞춰 물성 열 너비를 조정 (좁은 창에서도 숫자가 잘리지 않게)"""
        if not hasattr(self, "table_batch"):
            return
        width = self.table_batch.viewport().width()
        target = 108 if width >= 470 else (88 if width >= 390 else 70)
        if self.table_batch.columnWidth(0) != target:
            self.table_batch.setColumnWidth(0, target)

    def _refresh_batch_table(self):
        """선택(보기) 시편들로 배치 통계 표 갱신"""
        if not hasattr(self, "table_batch"):
            return
        self._fit_batch_metric_column()
        lang = self.current_lang
        t = TRANSLATIONS[lang]
        stats = self.session.statistics()
        selected = len(self.session.visible_records)
        self.batch_group.setTitle(
            f"{t['batch_group']} · {t['batch_n'].format(n=selected)}"
        )
        for row, stat in enumerate(stats):
            header = self.table_batch.item(row, 0)
            if header is not None:
                header.setText(metric_label(stat.key, lang))
            for col, field_name in enumerate(("mean", "std", "cv_pct", "min", "max"), start=1):
                item = self.table_batch.item(row, col)
                if item is None:
                    continue
                item.setText(stat.formatted(field_name))
                item.setToolTip(
                    f"{metric_label(stat.key, lang)} {stat.unit} · n={stat.n}" if stat.has_data else ""
                )

    def _export_batch(self, kind: str):
        """배치 요약(시편별 결과 + 통계) 엑셀/PDF 출력"""
        t = TRANSLATIONS[self.current_lang]
        records = self.session.records
        if not records:
            QMessageBox.warning(self, t["batch_group"], t["batch_export_empty"])
            return
        stats = self.session.statistics()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if kind == "xlsx":
            default_name = f"UTM_Batch_{stamp}.xlsx"
            file_filter = "Excel Files (*.xlsx)"
        else:
            default_name = f"UTM_Batch_{stamp}.pdf"
            file_filter = "PDF Files (*.pdf)"
        filepath, _ = QFileDialog.getSaveFileName(self, t["batch_group"], default_name, file_filter)
        if not filepath:
            return
        try:
            if kind == "xlsx":
                ExcelExporter.export_batch(filepath, records, stats, self.current_lang)
            else:
                PDFExporter.export_batch(filepath, records, stats, self.current_lang)
        except Exception as exc:
            QMessageBox.critical(self, t["batch_group"], str(exc))
            return
        QMessageBox.information(self, t["batch_group"], t["batch_export_done"].format(path=filepath))

    # ------------------------------------------------------------------
    # 시험 이력 / 무결성
    # ------------------------------------------------------------------
    def _update_history_button(self):
        if not hasattr(self, "btn_history"):
            return
        t = TRANSLATIONS[self.current_lang]
        try:
            count = self.history.count()
        except Exception:
            count = 0
        self.btn_history.setText(t["history_btn"].format(n=count))

    def _open_history(self):
        dialog = HistoryDialog(
            self.history, self.current_lang,
            load_callback=self._load_history_record, parent=self,
        )
        dialog.exec()
        self._update_history_button()

    def _load_history_record(self, record_id: str):
        """이력 1건을 세션(오버레이)과 비교표에 불러온다"""
        t = TRANSLATIONS[self.current_lang]
        if self.session.has_history_record(record_id):
            return False, t["history_duplicate"]
        record = self.history.load(record_id)
        if record is None:
            return False, t["history_load_failed"]
        self.session.add(**self.history.record_to_session_input(record))
        self._refresh_session_table()
        self._refresh_batch_table()
        self._replot_graph()
        return True, t["history_loaded"].format(id=record_id)

    def _calibration_snapshot(self) -> dict:
        """이력에 함께 저장하는 교정 상태 스냅샷"""
        if self.active_driver is self.serial_driver:
            data = self.serial_driver.calib_mgr.data
            return {
                "source": "RS-232 (Bongshin P2020 / P2014)",
                "load_zero_offset": data.load_zero_offset,
                "load_scale_factor": data.load_scale_factor,
                "disp_zero_offset": data.disp_zero_offset,
                "speed_scale_factor": data.speed_scale_factor,
                "last_load_calib_date": data.last_load_calib_date,
                "last_speed_calib_date": data.last_speed_calib_date,
            }
        return {
            "source": "VirtualUTMSimulator",
            "load_zero_offset": 0.0,
            "load_scale_factor": 1.0,
            "disp_zero_offset": 0.0,
            "speed_scale_factor": 1.0,
            "last_load_calib_date": "-",
            "last_speed_calib_date": "-",
        }

    def _next_specimen_id(self):
        """시편 ID 끝 번호를 하나 올린다 (예: SALT-SP-001 -> SALT-SP-002)"""
        current = self.edit_specimen_id.text().strip()
        if not current:
            return
        match = re.search(r"(\d+)(\D*)$", current)
        if match:
            digits = match.group(1)
            new_number = str(int(digits) + 1).zfill(len(digits))
            updated = current[:match.start(1)] + new_number + match.group(2)
        else:
            updated = current + "-2"
        self.edit_specimen_id.setText(updated)

    def _export_excel(self):
        if not self.current_result or not self.data_points:
            QMessageBox.warning(self, "경고", "내보낼 시험 데이터가 없습니다.")
            return
        specimen = self._get_current_specimen()
        config = self._get_current_config()
        default_filename = f"UTM_{specimen.specimen_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        filepath, _ = QFileDialog.getSaveFileName(self, "엑셀 시험 데이터 저장", default_filename, "Excel Files (*.xlsx)")
        if filepath:
            ExcelExporter.export(filepath, specimen, config, self.current_result, self.data_points)
            QMessageBox.information(self, "저장 완료", f"저장되었습니다:\n{filepath}")

    def _export_pdf(self):
        if not self.current_result or not self.data_points:
            QMessageBox.warning(self, "경고", "내보낼 시험 데이터가 없습니다.")
            return
        specimen = self._get_current_specimen()
        config = self._get_current_config()
        default_filename = f"Cert_{specimen.specimen_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        filepath, _ = QFileDialog.getSaveFileName(self, "성적서 PDF 저장", default_filename, "PDF Files (*.pdf)")
        if filepath:
            PDFExporter.export(filepath, specimen, config, self.current_result, self.data_points)
            QMessageBox.information(self, "저장 완료", f"저장되었습니다:\n{filepath}")

    def _on_hw_mode_changed(self, idx: int):
        if idx == 0:
            self.active_driver = self.simulator
            self.lbl_hw_status.setText("● 가상 시뮬레이터 모드 동작 중")
            self.lbl_hw_status.setStyleSheet("color: #64748B; font-weight: 700; font-size: 9.5pt; margin-left: 12px;")
        else:
            self.active_driver = self.serial_driver
            self.lbl_hw_status.setText("● RS-232 실장비 대기 (포트 연결 필요)")
            self.lbl_hw_status.setStyleSheet("color: #D97706; font-weight: 700; font-size: 9.5pt; margin-left: 12px;")

    def _refresh_com_ports(self):
        self.combo_com_port.clear()
        ports = SerialUTMDriver.list_available_ports()
        if ports:
            for p in ports:
                self.combo_com_port.addItem(p, p)
        else:
            self.combo_com_port.addItem("연결 가능한 시리얼 포트 없음", None)

    def _toggle_hw_connection(self):
        if not self.serial_driver.is_connected:
            port = self.combo_com_port.currentData()
            if not port:
                QMessageBox.warning(self, "포트 오류", "유효한 COM 포트를 선택해 주세요.")
                return
            baud = int(self.combo_baud.currentText().split()[0])
            if self.serial_driver.connect(port, baud):
                self.btn_connect_hw.setText("연결 해제" if self.current_lang == "KO" else "Disconnect")
                self.btn_connect_hw.setStyleSheet("background-color: #DC2626; color: #FFFFFF; font-weight: bold; min-height: 32px;")
                self.lbl_hw_status.setText(f"● {port} 연결됨 (115200 bps)")
                self.lbl_hw_status.setStyleSheet("color: #059669; font-weight: 700; font-size: 9.5pt; margin-left: 12px;")
        else:
            self.serial_driver.disconnect()
            self.btn_connect_hw.setText("장비 연결" if self.current_lang == "KO" else "Connect")
            self.btn_connect_hw.setStyleSheet("background-color: #1D4ED8; color: #FFFFFF; font-weight: bold; min-height: 32px;")
            self.lbl_hw_status.setText("● 연결 해제됨")
            self.lbl_hw_status.setStyleSheet("color: #64748B; font-weight: 700; font-size: 9.5pt; margin-left: 12px;")

    def _tare_load(self):
        self.active_driver.tare_load()
        self.lbl_load_val.setText("0.0")
        self.statusBar().showMessage("하중 영점 맞춤 완료 (0.00 N)")

    def _tare_disp(self):
        self.active_driver.tare_displacement()
        self.lbl_disp_val.setText("0.000")
        self.statusBar().showMessage("변위 영점 맞춤 완료 (0.000 mm)")

    def _do_calib_zero(self):
        self.serial_driver.tare_load()
        offset = self.serial_driver.calib_mgr.data.load_zero_offset
        QMessageBox.information(self, "영점 교정", f"무부하 영점 오프셋이 설정되었습니다: {offset:.2f} N")

    def _do_calib_span(self):
        try:
            val = float(self.edit_ref_load.text().strip())
            unit = self.combo_ref_unit.currentText()
            factor = self.serial_driver.calibrate_load_span(val, unit)
            self.lbl_load_factor.setText(f"현재 하중 보정 계수: {factor:.5f} (최근 갱신됨)")
            QMessageBox.information(self, "스팬 교정", f"스팬 교정이 완료되었습니다!\n적용된 보정 계수: {factor:.5f}")
        except Exception as e:
            QMessageBox.critical(self, "교정 오류", f"입력값을 확인해 주세요: {e}")

    def _do_calib_speed(self):
        try:
            target = float(self.edit_target_speed.text().strip())
            measured = float(self.edit_measured_dist.text().strip())
            factor = self.serial_driver.calibrate_speed(target, measured)
            self.lbl_speed_factor.setText(f"현재 속도 보정 계수: {factor:.5f} (최근 갱신됨)")
            QMessageBox.information(self, "속도 교정", f"속도 보정 계수가 적용되었습니다!\n보정 계수: {factor:.5f}")
        except Exception as e:
            QMessageBox.critical(self, "교정 오류", f"입력값을 확인해 주세요: {e}")

    def _on_raw_packet_received(self, raw_line: str):
        if self.txt_packet_log.document().lineCount() > 200:
            self.txt_packet_log.clear()
        self.txt_packet_log.append(raw_line)
