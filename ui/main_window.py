"""
Salt Sw ver.1 - Main Dashboard Window
만능재료시험기(UTM) 제어, 실시간 하중/변위/응력/변형률 모니터링 및 엑셀·PDF 출력 메인 윈도우
- 현장 작업자 최적화 직관적인 쉬운 한국어 기본 탑재 (불필요한 외래어 배제)
- 글로벌 수출 및 해외 바이어용 원클릭 영문(ASTM 표준) 전환 탑재
- Windows 11 High-DPI 무충돌 아키텍처
"""

import os
from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QRect
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QComboBox, QDoubleSpinBox,
    QPushButton, QRadioButton, QButtonGroup, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QFrame, QHeaderView,
    QTabWidget, QCheckBox, QScrollArea, QTextEdit, QSizePolicy
)

try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

from core.models import (
    Specimen, SpecimenType, TestConfig, TestMode, BendingType, HoldingType,
    DataPoint, TestResult, ExtensometerSettings, ExtensometerType
)
from core.simulator import VirtualUTMSimulator
from core.serial_driver import SerialUTMDriver
from core.hardware_interface import HardwareInterface
from core.calculator import MaterialCalculator
from core.preferences import PreferencesManager
from core.i18n import TRANSLATIONS
from exporters.excel_exporter import ExcelExporter
from exporters.pdf_exporter import PDFExporter
from ui.styles import HYUNDAI_THEME_QSS


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
        self.resize(1360, 900)
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(HYUNDAI_THEME_QSS)

        # 데이터 저장소 및 하드웨어
        self.data_points: List[DataPoint] = []
        self.current_result: Optional[TestResult] = None
        self.prefs = PreferencesManager()
        self.simulator = VirtualUTMSimulator()
        self.serial_driver = SerialUTMDriver()
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

        # Specimen
        self.group_spec.setTitle(t["spec_title"])
        self.lbl_spec_id.setText(t["spec_id"])
        self.lbl_mat.setText(t["spec_mat"])
        self.lbl_spec_type.setText(t["spec_type"])
        is_flat = (self.combo_type.currentIndex() == 0)
        self.lbl_width.setText(t["spec_width"] if is_flat else t["spec_dia"])
        self.lbl_thick.setText(t["spec_thick"])
        self.lbl_l0.setText(t["spec_l0"])

        # Conditions
        self.cond_group.setTitle(t["cond_title"])
        self.lbl_speed.setText(t["cond_speed"])
        self.lbl_drop.setText(t["cond_drop"])
        self.lbl_bend_type.setText(t["cond_bend_type"])
        self.lbl_span.setText(t["cond_span"])
        self.lbl_hold_type.setText(t["cond_hold_type"])
        self.lbl_hold_val.setText(t["cond_hold_val"])
        self.lbl_hold_dur.setText(t["cond_hold_dur"])

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

        # Hardware Tab
        self.settings_group.setTitle(t["hw_conn_title"])
        self.lbl_hw_mode.setText(t["hw_mode"])
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

        # Preferences Tab
        self._apply_preferences_language(t)

    def _create_dashboard_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(380)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        left_content = self._create_left_panel()
        left_scroll.setWidget(left_content)
        layout.addWidget(left_scroll, stretch=0)

        right_panel = self._create_right_panel()
        layout.addWidget(right_panel, stretch=1)
        return tab

    def _create_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 10, 6)
        layout.setSpacing(10)

        # A. 시험 모드 선택 (4대 시험 모드)
        self.group_mode = QGroupBox("시험 종류 선택")
        mode_layout = QGridLayout(self.group_mode)
        mode_layout.setSpacing(6)
        self.rb_tensile = QRadioButton("인장 시험")
        self.rb_compression = QRadioButton("압축 시험")
        self.rb_bending = QRadioButton("굽힘 시험")
        self.rb_holding = QRadioButton("유지 시험")
        self.rb_tensile.setChecked(True)

        self.mode_btn_group = QButtonGroup()
        self.mode_btn_group.addButton(self.rb_tensile, 0)
        self.mode_btn_group.addButton(self.rb_compression, 1)
        self.mode_btn_group.addButton(self.rb_bending, 2)
        self.mode_btn_group.addButton(self.rb_holding, 3)
        self.mode_btn_group.idToggled.connect(self._on_test_mode_toggled)

        mode_layout.addWidget(self.rb_tensile, 0, 0)
        mode_layout.addWidget(self.rb_compression, 0, 1)
        mode_layout.addWidget(self.rb_bending, 1, 0)
        mode_layout.addWidget(self.rb_holding, 1, 1)
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

        layout.addWidget(self.group_spec)

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

    def _create_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

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
            self.plot_widget = pg.PlotWidget()
            self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
            self.plot_widget.setLabel('bottom', '변형률 (%)')
            self.plot_widget.setLabel('left', '응력 (MPa)')
            self.plot_curve = self.plot_widget.plot(pen=pg.mkPen(color='#1D4ED8', width=2))
            graph_box_layout.addWidget(self.plot_widget)
        else:
            lbl_nograph = QLabel("pyqtgraph 라이브러리가 설치되지 않아 차트가 비활성화되었습니다.")
            lbl_nograph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            graph_box_layout.addWidget(lbl_nograph)

        layout.addWidget(self.graph_box, stretch=2)

        # 3. 시험 결과표
        self.results_group = QGroupBox("시험 결과 분석표")
        res_layout = QVBoxLayout(self.results_group)
        res_layout.setContentsMargins(10, 10, 10, 10)
        res_layout.setSpacing(6)

        self.table_results = QTableWidget(1, len(self.RESULT_COLUMNS))
        self.table_results.verticalHeader().setVisible(False)
        self.table_results.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_results.setFixedHeight(72)

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
        else:
            mode = TestMode.HOLDING

        btype = BendingType.THREE_POINT if self.combo_bend_type.currentIndex() == 0 else BendingType.FOUR_POINT
        htype = HoldingType.LOAD_HOLD if self.combo_hold_type.currentIndex() == 0 else HoldingType.DISP_HOLD

        return TestConfig(
            mode=mode,
            test_speed_mm_min=self.spin_speed.value(),
            fracture_drop_ratio=self.spin_drop.value() / 100.0,
            max_displacement_mm=50.0,
            sampling_rate_hz=20,
            bending_type=btype,
            span_length_mm=self.spin_span.value(),
            holding_type=htype,
            target_holding_val=self.spin_hold_val.value(),
            holding_duration_s=self.spin_hold_dur.value(),
            ext=self.prefs.ext.copy(),
        )

    def _start_test(self):
        self.data_points.clear()
        self._clear_results_table()
        if HAS_PYQTGRAPH:
            self.plot_curve.setData([], [])

        specimen = self._get_current_specimen()
        config = self._get_current_config()

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

        self.active_driver.start_test(specimen, config)

    def _stop_test(self):
        self.active_driver.stop_test()
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

        specimen = self._get_current_specimen()
        config = self._get_current_config()

        self.current_result = MaterialCalculator.calculate(specimen, config, self.data_points, reason)
        self._update_results_table(self.current_result, reason)
        self._replot_graph()

        # 변형률 측정 소스 표시 (실제 시험에 적용된 소스)
        source_key = "src_crosshead"
        if self.current_result.ext_enabled:
            source_key = "src_mv" if self.current_result.ext_type == ExtensometerType.MV.value else "src_pulse"
            if self.current_result.strain_source not in (
                MaterialCalculator.EXT_SOURCE_MV, MaterialCalculator.EXT_SOURCE_PULSE
            ):
                source_key = "src_crosshead"
                self.statusBar().showMessage(TRANSLATIONS[self.current_lang]["ext_lost_warning"])
        self._apply_strain_source_label(source_key)

        t = TRANSLATIONS[self.current_lang]
        msg = t["status_done"].format(reason=reason, count=len(self.data_points))
        self.statusBar().showMessage(msg)
        QMessageBox.information(
            self,
            "시험 완료",
            f"시험이 완료되었습니다.\n상태: {reason}\n최대 하중: {self.current_result.peak_load_n:,.1f} N\n강도: {self.current_result.peak_stress_mpa:.2f} MPa"
        )

    def _replot_graph(self):
        if not HAS_PYQTGRAPH or not self.data_points:
            return
        use_ext = self.current_result.ext_enabled if self.current_result else self.prefs.ext.enabled
        if self.rb_graph_ss.isChecked():
            self.plot_widget.setLabel('bottom', '변형률 (%)' if self.current_lang == "KO" else 'Strain (%)')
            self.plot_widget.setLabel('left', '응력 (MPa)' if self.current_lang == "KO" else 'Stress (MPa)')
            xs = [p.strain_pct for p in self.data_points]
            ys = [p.stress_mpa for p in self.data_points]
        else:
            ext_disp = use_ext and any(p.ext_valid for p in self.data_points)
            if ext_disp:
                bottom = '신율계 변위 (mm)' if self.current_lang == "KO" else 'Extensometer travel (mm)'
            else:
                bottom = '변위 (mm)' if self.current_lang == "KO" else 'Displacement (mm)'
            self.plot_widget.setLabel('bottom', bottom)
            self.plot_widget.setLabel('left', '하중 (N)' if self.current_lang == "KO" else 'Load (N)')
            xs = [(p.ext_disp_mm if (ext_disp and p.ext_valid) else p.displacement_mm) for p in self.data_points]
            ys = [p.load_n for p in self.data_points]
        self.plot_curve.setData(xs, ys)

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
