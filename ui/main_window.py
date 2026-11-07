"""
Salt Sw ver.1 - Main Dashboard Window
만능재료시험기(UTM) 제어, 실시간 하중/변위/응력/변형률 모니터링 및 엑셀·PDF 출력 메인 윈도우
"""

import os
from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QComboBox, QDoubleSpinBox,
    QPushButton, QRadioButton, QButtonGroup, QTableWidget,
    QTableWidgetItem, QFileDialog, QMessageBox, QFrame, QHeaderView,
    QTabWidget, QCheckBox, QScrollArea, QTextEdit
)

try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

from core.models import Specimen, SpecimenType, TestConfig, TestMode, DataPoint, TestResult
from core.simulator import VirtualUTMSimulator
from core.serial_driver import SerialUTMDriver
from core.hardware_interface import HardwareInterface
from core.calculator import MaterialCalculator
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

    # 결과 테이블 컬럼 정의
    RESULT_COLUMNS = [
        ("최대 하중 (Pmax, N)", "최대하중"),
        ("인장/압축강도 (Rm, MPa)", "인장/압축강도"),
        ("항복강도 (Rp0.2, MPa)", "항복강도"),
        ("탄성계수 (E, GPa)", "탄성계수"),
        ("파단 연신율 (A, %)", "연신율"),
        ("파단 변위 (dL, mm)", "파단변위"),
        ("흡수에너지 (U, J)", "흡수에너지"),
        ("시험 결과 판정", "결과판정")
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Salt Sw ver.1 — Universal Testing Machine (UTM)")
        self.resize(1360, 900)
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(HYUNDAI_THEME_QSS)

        # 데이터 저장소 및 하드웨어
        self.data_points: List[DataPoint] = []
        self.current_result: Optional[TestResult] = None
        self.simulator = VirtualUTMSimulator()
        self.serial_driver = SerialUTMDriver()
        self.active_driver: HardwareInterface = self.simulator

        self.bridge = CommunicateBridge()
        self.bridge.data_received.connect(self._on_data_received)
        self.bridge.test_completed.connect(self._on_test_completed)
        self.bridge.raw_data_received.connect(self._on_raw_data_received)

        self.simulator.on_data_received = lambda dp: self.bridge.data_received.emit(dp)
        self.simulator.on_test_completed = lambda reason: self.bridge.test_completed.emit(reason)

        self.serial_driver.on_data_received = lambda dp: self.bridge.data_received.emit(dp)
        self.serial_driver.on_test_completed = lambda reason: self.bridge.test_completed.emit(reason)
        self.serial_driver.on_raw_data_received = lambda raw: self.bridge.raw_data_received.emit(raw)

        self._init_ui()

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        root_layout = QVBoxLayout(main_widget)
        root_layout.setContentsMargins(12, 10, 12, 10)
        root_layout.setSpacing(8)

        # 상단 탭 위젯 생성
        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)

        # 탭 1: 메인 시험 진행 및 모니터링 대시보드
        tab_dashboard = self._create_dashboard_tab()
        self.tabs.addTab(tab_dashboard, "📊  시험 제어 및 실시간 모니터링")

        # 탭 2: 계측 장비 연동 및 통신 설정 (RS-232 / 봉신 P2020)
        tab_hardware = self._create_hardware_tab()
        self.tabs.addTab(tab_hardware, "🔌  계측 장비 연동 설정 (RS-232 / 봉신)")

        # 상태 바
        self.statusBar().showMessage("장비 상태: 대기 중 (READY) | 가상 시뮬레이터 동작 중")

    def _create_dashboard_tab(self) -> QWidget:
        """메인 대시보드 탭 생성 (좌측 제어 + 우측 계측 모니터링)"""
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        # 좌측 패널 (스크롤 영역에 감싸 세로 찌그러짐 원천 차단)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(380)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        left_content = self._create_left_panel()
        left_scroll.setWidget(left_content)
        layout.addWidget(left_scroll, stretch=0)

        # 우측 패널 (계측 타일 + 그래프 + 필터링 결과표)
        right_panel = self._create_right_panel()
        layout.addWidget(right_panel, stretch=1)

        return tab

    def _create_left_panel(self) -> QWidget:
        """좌측 제어 패널: 시편 설정, 조건 설정, 동작 제어, 파일 출력"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 10, 6)
        layout.setSpacing(10)

        # 브랜드 헤더
        brand_box = QFrame()
        brand_layout = QVBoxLayout(brand_box)
        brand_layout.setContentsMargins(4, 2, 4, 4)
        brand_layout.setSpacing(2)
        brand_label = QLabel("SALT SW VER.1")
        brand_label.setStyleSheet("font-size: 16pt; font-weight: 800; color: #0047BA; letter-spacing: 0.5px;")
        sub_label = QLabel("Universal Testing Machine Control System")
        sub_label.setStyleSheet("font-size: 8.5pt; color: #64748B;")
        brand_layout.addWidget(brand_label)
        brand_layout.addWidget(sub_label)
        layout.addWidget(brand_box)

        # A. 시험 모드 선택
        mode_group = QGroupBox("시험 모드 (Test Mode)")
        mode_layout = QHBoxLayout(mode_group)
        self.rb_tensile = QRadioButton("인장 시험 (Tensile)")
        self.rb_compression = QRadioButton("압축 시험 (Compression)")
        self.rb_tensile.setChecked(True)
        self.mode_btn_group = QButtonGroup()
        self.mode_btn_group.addButton(self.rb_tensile)
        self.mode_btn_group.addButton(self.rb_compression)
        mode_layout.addWidget(self.rb_tensile)
        mode_layout.addWidget(self.rb_compression)
        layout.addWidget(mode_group)

        # B. 시편 제원 설정
        spec_group = QGroupBox("시편 제원 설정 (Specimen)")
        spec_layout = QGridLayout(spec_group)
        spec_layout.setSpacing(8)

        spec_layout.addWidget(QLabel("시편 ID:"), 0, 0)
        self.edit_specimen_id = QLineEdit("SALT-SP-001")
        spec_layout.addWidget(self.edit_specimen_id, 0, 1)

        spec_layout.addWidget(QLabel("재질:"), 1, 0)
        self.edit_material = QLineEdit("SS400 (Structural Steel)")
        spec_layout.addWidget(self.edit_material, 1, 1)

        spec_layout.addWidget(QLabel("시편 형태:"), 2, 0)
        self.combo_type = QComboBox()
        self.combo_type.addItems(["판재 (Flat)", "봉재 (Round)"])
        self.combo_type.currentIndexChanged.connect(self._on_specimen_type_changed)
        spec_layout.addWidget(self.combo_type, 2, 1)

        self.lbl_width = QLabel("폭 (Width, mm):")
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(0.1, 500.0)
        self.spin_width.setValue(12.5)
        spec_layout.addWidget(self.lbl_width, 3, 0)
        spec_layout.addWidget(self.spin_width, 3, 1)

        self.lbl_thick = QLabel("두께 (Thick, mm):")
        self.spin_thick = QDoubleSpinBox()
        self.spin_thick.setRange(0.01, 200.0)
        self.spin_thick.setValue(3.0)
        spec_layout.addWidget(self.lbl_thick, 4, 0)
        spec_layout.addWidget(self.spin_thick, 4, 1)

        spec_layout.addWidget(QLabel("표점거리 (L0, mm):"), 5, 0)
        self.spin_l0 = QDoubleSpinBox()
        self.spin_l0.setRange(1.0, 1000.0)
        self.spin_l0.setValue(50.0)
        spec_layout.addWidget(self.spin_l0, 5, 1)

        layout.addWidget(spec_group)

        # C. 시험 조건 설정
        cond_group = QGroupBox("시험 조건 (Test Conditions)")
        cond_layout = QGridLayout(cond_group)
        cond_layout.setSpacing(8)

        cond_layout.addWidget(QLabel("시험 속도 (mm/min):"), 0, 0)
        self.spin_speed = QDoubleSpinBox()
        self.spin_speed.setRange(0.1, 500.0)
        self.spin_speed.setValue(5.0)
        cond_layout.addWidget(self.spin_speed, 0, 1)

        cond_layout.addWidget(QLabel("파단 감지 드롭 (%):"), 1, 0)
        self.spin_drop = QDoubleSpinBox()
        self.spin_drop.setRange(10.0, 95.0)
        self.spin_drop.setValue(50.0)
        cond_layout.addWidget(self.spin_drop, 1, 1)

        layout.addWidget(cond_group)

        # D. 장비 조작 버튼
        ctrl_group = QGroupBox("시험기 제어 (Operation)")
        ctrl_layout = QVBoxLayout(ctrl_group)
        ctrl_layout.setSpacing(8)

        self.btn_start = QPushButton("▶  시험 시작 (START)")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.clicked.connect(self._start_test)
        ctrl_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹  비상 정지 (STOP)")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_test)
        ctrl_layout.addWidget(self.btn_stop)

        h_sub_btns = QHBoxLayout()
        self.btn_origin = QPushButton("🔄 원점 복귀")
        self.btn_origin.clicked.connect(self._return_origin)
        self.btn_reset = QPushButton("🗑 데이터 초기화")
        self.btn_reset.clicked.connect(self._reset_data)
        h_sub_btns.addWidget(self.btn_origin)
        h_sub_btns.addWidget(self.btn_reset)
        ctrl_layout.addLayout(h_sub_btns)

        layout.addWidget(ctrl_group)

        # E. 데이터 내보내기 그룹 (엑셀 / PDF)
        export_group = QGroupBox("데이터 저장 및 리포트 (Export)")
        export_layout = QVBoxLayout(export_group)
        export_layout.setSpacing(8)

        self.btn_excel = QPushButton("📊  엑셀 데이터 저장 (.xlsx)")
        self.btn_excel.setObjectName("btn_excel")
        self.btn_excel.setEnabled(False)
        self.btn_excel.clicked.connect(self._export_excel)
        export_layout.addWidget(self.btn_excel)

        self.btn_pdf = QPushButton("📄  시험 성적서 PDF 출력 (.pdf)")
        self.btn_pdf.setObjectName("btn_pdf")
        self.btn_pdf.setEnabled(False)
        self.btn_pdf.clicked.connect(self._export_pdf)
        export_layout.addWidget(self.btn_pdf)

        layout.addWidget(export_group)
        layout.addStretch()
        return panel

    def _create_right_panel(self) -> QWidget:
        """우측 패널: 대형 디지털 타일, 실시간 그래프, 필터링 결과 테이블"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 1. 상단 대형 디지털 계측 타일 4개
        tiles_layout = QHBoxLayout()
        tiles_layout.setSpacing(10)

        self.tile_load, self.lbl_load_val = self._create_tile("LOAD (하중)", "0.0", "N")
        self.tile_disp, self.lbl_disp_val = self._create_tile("DISP (변위)", "0.000", "mm")
        self.tile_stress, self.lbl_stress_val = self._create_tile("STRESS (응력)", "0.0", "MPa")
        self.tile_strain, self.lbl_strain_val = self._create_tile("STRAIN (변형률)", "0.00", "%")

        tiles_layout.addWidget(self.tile_load)
        tiles_layout.addWidget(self.tile_disp)
        tiles_layout.addWidget(self.tile_stress)
        tiles_layout.addWidget(self.tile_strain)
        layout.addLayout(tiles_layout)

        # 2. 실시간 그래프 (S-S Curve / Load-Disp)
        graph_box = QGroupBox("실시간 시험 곡선 (Real-time S-S Curve)")
        graph_box_layout = QVBoxLayout(graph_box)

        # 그래프 축 전환 라디오
        graph_ctrl_layout = QHBoxLayout()
        self.rb_graph_ss = QRadioButton("응력 - 변형률 곡선 (Stress vs Strain)")
        self.rb_graph_ld = QRadioButton("하중 - 변위 곡선 (Load vs Displacement)")
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
            pg.setConfigOptions(antialias=True)
            self.plot_widget = pg.PlotWidget()
            self.plot_widget.setBackground('#FFFFFF')
            self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
            self.plot_widget.setLabel('bottom', 'Strain (%)')
            self.plot_widget.setLabel('left', 'Stress (MPa)')
            self.plot_curve = self.plot_widget.plot(pen=pg.mkPen(color='#0047BA', width=2.5))
            graph_box_layout.addWidget(self.plot_widget)
        else:
            self.plot_widget = QLabel("PyQtGraph 라이브러리가 설치되면 고속 실시간 그래프가 활성화됩니다.")
            self.plot_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.plot_widget.setStyleSheet("background-color: #FFFFFF; border: 1px solid #E5E8EB; border-radius: 8px; color: #64748B;")
            graph_box_layout.addWidget(self.plot_widget)

        layout.addWidget(graph_box, stretch=3)

        # 3. 하단 시험 결과 요약 테이블 + 사용자 맞춤 체크박스 필터링 바
        res_box = QGroupBox("주요 기계적 물성 분석 결과 (Test Results)")
        res_layout = QVBoxLayout(res_box)
        res_layout.setSpacing(6)

        # 체크박스 필터 바
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)
        lbl_filter_title = QLabel("⚙️ 표시 항목 선택:")
        lbl_filter_title.setStyleSheet("font-weight: 700; color: #0047BA; font-size: 9pt;")
        filter_layout.addWidget(lbl_filter_title)

        self.col_checkboxes: List[QCheckBox] = []
        for col_idx, (full_title, short_title) in enumerate(self.RESULT_COLUMNS):
            cb = QCheckBox(short_title)
            cb.setChecked(True)
            cb.setToolTip(full_title)
            # 클로저 바인딩
            cb.toggled.connect(lambda checked, idx=col_idx: self._toggle_column_visibility(idx, checked))
            self.col_checkboxes.append(cb)
            filter_layout.addWidget(cb)

        btn_select_all = QPushButton("전체")
        btn_select_all.setFixedWidth(50)
        btn_select_all.clicked.connect(self._select_all_columns)
        filter_layout.addWidget(btn_select_all)
        filter_layout.addStretch()

        res_layout.addLayout(filter_layout)

        # 결과 테이블
        self.table_results = QTableWidget()
        self.table_results.setColumnCount(len(self.RESULT_COLUMNS))
        self.table_results.setHorizontalHeaderLabels([col[0] for col in self.RESULT_COLUMNS])
        self.table_results.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_results.setRowCount(1)
        self.table_results.setFixedHeight(75)
        self._clear_results_table()
        res_layout.addWidget(self.table_results)

        layout.addWidget(res_box, stretch=1)
        return panel

    def _create_hardware_tab(self) -> QWidget:
        """상단 탭 2: 계측 장비 연동 및 통신 설정 전용 화면"""
        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        main_layout.setContentsMargins(18, 14, 18, 14)
        main_layout.setSpacing(14)

        # 1. 상단 통신 설정 카드
        settings_group = QGroupBox("RS-232 시리얼 통신 및 장비 설정 (Bongshin Loadcell & Indicator)")
        settings_layout = QGridLayout(settings_group)
        settings_layout.setContentsMargins(16, 18, 16, 16)
        settings_layout.setSpacing(12)

        settings_layout.addWidget(QLabel("동작 모드:"), 0, 0)
        self.combo_hw_mode = QComboBox()
        self.combo_hw_mode.addItems(["가상 시뮬레이터 (Virtual Simulator)", "RS-232 실장비 (봉신 P2020 / P2014)"])
        self.combo_hw_mode.currentIndexChanged.connect(self._on_hw_mode_changed)
        settings_layout.addWidget(self.combo_hw_mode, 0, 1, 1, 2)

        settings_layout.addWidget(QLabel("COM 포트 (COM Port):"), 1, 0)
        self.combo_com_port = QComboBox()
        self.btn_refresh_ports = QPushButton("🔄 포트 새로고침")
        self.btn_refresh_ports.setFixedWidth(120)
        self.btn_refresh_ports.clicked.connect(self._refresh_com_ports)
        settings_layout.addWidget(self.combo_com_port, 1, 1)
        settings_layout.addWidget(self.btn_refresh_ports, 1, 2)
        self._refresh_com_ports()

        settings_layout.addWidget(QLabel("통신 속도 (Baudrate):"), 2, 0)
        self.combo_baud = QComboBox()
        self.combo_baud.addItems(["115200 (봉신 P2020/2014 표준)", "57600", "38400", "19200", "9600"])
        settings_layout.addWidget(self.combo_baud, 2, 1, 1, 2)

        settings_layout.addWidget(QLabel("통신 규격 (Format):"), 3, 0)
        lbl_format = QLabel("Data 8 Bit / Parity None / Stop 1 Bit (8-N-1)")
        lbl_format.setStyleSheet("color: #475569; font-weight: 600;")
        settings_layout.addWidget(lbl_format, 3, 1, 1, 2)

        # 연결 버튼 및 상태 인디케이터
        h_conn = QHBoxLayout()
        self.btn_connect_hw = QPushButton("🔌  장비 연결 (Connect)")
        self.btn_connect_hw.setStyleSheet("background-color: #0047BA; color: #FFFFFF; font-size: 11pt; font-weight: bold; min-height: 34px;")
        self.btn_connect_hw.clicked.connect(self._toggle_hw_connection)
        
        self.lbl_hw_status = QLabel("● 장비 미연결 (가상 시뮬레이터 모드)")
        self.lbl_hw_status.setStyleSheet("color: #64748B; font-weight: 700; font-size: 10pt; margin-left: 12px;")
        h_conn.addWidget(self.btn_connect_hw, stretch=1)
        h_conn.addWidget(self.lbl_hw_status, stretch=2)
        settings_layout.addLayout(h_conn, 4, 0, 1, 3)

        main_layout.addWidget(settings_group)

        # 2. 영점 맞춤(Tare) 제어 카드
        tare_group = QGroupBox("장비 영점 보정 (Zero / Tare)")
        tare_layout = QHBoxLayout(tare_group)
        tare_layout.setContentsMargins(16, 16, 16, 16)
        tare_layout.setSpacing(14)

        self.btn_tare_load = QPushButton("0️⃣  하중 영점 맞춤 (Tare Load)")
        self.btn_tare_load.setMinimumHeight(34)
        self.btn_tare_load.clicked.connect(self._tare_load)

        self.btn_tare_disp = QPushButton("0️⃣  변위 영점 맞춤 (Tare Disp)")
        self.btn_tare_disp.setMinimumHeight(34)
        self.btn_tare_disp.clicked.connect(self._tare_disp)

        lbl_tare_desc = QLabel("※ 시험 시작 전 현재 하중과 변위를 0.00으로 보정합니다.")
        lbl_tare_desc.setStyleSheet("color: #64748B; font-size: 9pt;")

        tare_layout.addWidget(self.btn_tare_load)
        tare_layout.addWidget(self.btn_tare_disp)
        tare_layout.addWidget(lbl_tare_desc)
        tare_layout.addStretch()

        main_layout.addWidget(tare_group)

        # 3. 장비 정밀 교정 카드 (로드셀 2점 교정 및 크로스헤드 속도 교정)
        calib_group = QGroupBox("🎯 장비 정밀 교정 (Load Cell & Speed Calibration)")
        calib_layout = QVBoxLayout(calib_group)
        calib_layout.setContentsMargins(16, 16, 16, 16)
        calib_layout.setSpacing(12)

        # 3-A. 로드셀 2점 교정 (하중 Zero & Span)
        box_load_calib = QGroupBox("1) 봉신 로드셀 2점 교정 (Zero & Span)")
        grid_load = QGridLayout(box_load_calib)
        grid_load.setSpacing(10)

        grid_load.addWidget(QLabel("① 영점 교정:"), 0, 0)
        self.btn_calib_zero = QPushButton("0️⃣  현재 상태를 무부하 영점(Zero)으로 설정")
        self.btn_calib_zero.clicked.connect(self._do_calib_zero)
        grid_load.addWidget(self.btn_calib_zero, 0, 1, 1, 2)

        grid_load.addWidget(QLabel("② 스팬 교정:"), 1, 0)
        self.edit_ref_load = QLineEdit("1000.0")
        self.edit_ref_load.setPlaceholderText("기준 하중값")
        self.combo_ref_unit = QComboBox()
        self.combo_ref_unit.addItems(["kgf", "kN", "N"])
        self.btn_calib_span = QPushButton("⚖️  기준 하중 인가 후 스팬 교정 실행")
        self.btn_calib_span.setStyleSheet("background-color: #0047BA; color: white; font-weight: bold;")
        self.btn_calib_span.clicked.connect(self._do_calib_span)
        grid_load.addWidget(self.edit_ref_load, 1, 1)
        grid_load.addWidget(self.combo_ref_unit, 1, 2)
        grid_load.addWidget(self.btn_calib_span, 1, 3)

        self.lbl_load_factor = QLabel(f"현재 하중 보정 계수: {self.serial_driver.calib_mgr.data.load_scale_factor:.5f} (최근: {self.serial_driver.calib_mgr.data.last_load_calib_date})")
        self.lbl_load_factor.setStyleSheet("color: #0369A1; font-weight: 600; font-size: 9pt;")
        grid_load.addWidget(self.lbl_load_factor, 2, 0, 1, 4)
        calib_layout.addWidget(box_load_calib)

        # 3-B. 크로스헤드 속도 교정 (Speed Scale Factor)
        box_speed_calib = QGroupBox("2) 크로스헤드 이송 속도 교정 (Speed Calibration)")
        grid_speed = QGridLayout(box_speed_calib)
        grid_speed.setSpacing(10)

        grid_speed.addWidget(QLabel("목표 속도 (mm/min):"), 0, 0)
        self.edit_target_speed = QLineEdit("50.0")
        grid_speed.addWidget(self.edit_target_speed, 0, 1)

        grid_speed.addWidget(QLabel("1분간 실측 이동거리 (mm):"), 0, 2)
        self.edit_measured_dist = QLineEdit("48.5")
        grid_speed.addWidget(self.edit_measured_dist, 0, 3)

        self.btn_calib_speed = QPushButton("⏱️  속도 보정 계수 자동 계산 및 적용")
        self.btn_calib_speed.setStyleSheet("background-color: #0284C7; color: white; font-weight: bold;")
        self.btn_calib_speed.clicked.connect(self._do_calib_speed)
        grid_speed.addWidget(self.btn_calib_speed, 0, 4)

        self.lbl_speed_factor = QLabel(f"현재 속도 보정 계수: {self.serial_driver.calib_mgr.data.speed_scale_factor:.5f} (최근: {self.serial_driver.calib_mgr.data.last_speed_calib_date})")
        self.lbl_speed_factor.setStyleSheet("color: #0369A1; font-weight: 600; font-size: 9pt;")
        grid_speed.addWidget(self.lbl_speed_factor, 1, 0, 1, 5)
        calib_layout.addWidget(box_speed_calib)

        main_layout.addWidget(calib_group)

        # 4. 실시간 통신 패킷 수신 모니터 카드
        mon_group = QGroupBox("실시간 RS-232 통신 데이터 패킷 모니터링 (Raw Packet Monitor)")
        mon_layout = QVBoxLayout(mon_group)
        mon_layout.setContentsMargins(16, 16, 16, 16)
        mon_layout.setSpacing(8)

        self.txt_packet_log = QTextEdit()
        self.txt_packet_log.setReadOnly(True)
        self.txt_packet_log.setStyleSheet(
            "background-color: #0F172A; color: #38BDF8; font-family: 'Consolas', monospace; font-size: 9.5pt; border-radius: 8px; padding: 10px;"
        )
        self.txt_packet_log.setPlaceholderText("장비가 연결되면 수신되는 원시 데이터 스트림(ASCII/Hex)이 여기에 표시됩니다...")
        mon_layout.addWidget(self.txt_packet_log)

        h_mon_ctrl = QHBoxLayout()
        self.btn_clear_log = QPushButton("로그 지우기")
        self.btn_clear_log.setFixedWidth(100)
        self.btn_clear_log.clicked.connect(lambda: self.txt_packet_log.clear())
        h_mon_ctrl.addWidget(self.btn_clear_log)
        h_mon_ctrl.addStretch()
        mon_layout.addLayout(h_mon_ctrl)

        main_layout.addWidget(mon_group, stretch=1)
        return tab

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

        return tile, lbl_val

    def _toggle_column_visibility(self, col_idx: int, visible: bool):
        """체크박스 토글에 따라 결과 테이블 컬럼 표시/숨김"""
        self.table_results.setColumnHidden(col_idx, not visible)

    def _select_all_columns(self):
        """결과 테이블 전체 컬럼 선택"""
        for cb in self.col_checkboxes:
            cb.setChecked(True)

    def _on_specimen_type_changed(self, index: int):
        is_flat = (index == 0)
        self.lbl_width.setText("폭 (Width, mm):" if is_flat else "직경 (Dia, mm):")
        self.lbl_thick.setVisible(is_flat)
        self.spin_thick.setVisible(is_flat)

    def _get_current_specimen(self) -> Specimen:
        stype = SpecimenType.FLAT if self.combo_type.currentIndex() == 0 else SpecimenType.ROUND
        return Specimen(
            specimen_id=self.edit_specimen_id.text().strip(),
            material_name=self.edit_material.text().strip(),
            specimen_type=stype,
            width_or_diameter_mm=self.spin_width.value(),
            thickness_mm=self.spin_thick.value() if stype == SpecimenType.FLAT else None,
            gauge_length_mm=self.spin_l0.value()
        )

    def _get_current_config(self) -> TestConfig:
        mode = TestMode.TENSILE if self.rb_tensile.isChecked() else TestMode.COMPRESSION
        return TestConfig(
            mode=mode,
            test_speed_mm_min=self.spin_speed.value(),
            fracture_drop_ratio=self.spin_drop.value() / 100.0,
            max_displacement_mm=50.0,
            sampling_rate_hz=20
        )

    def _start_test(self):
        self.data_points.clear()
        self._clear_results_table()
        if HAS_PYQTGRAPH:
            self.plot_curve.setData([], [])

        specimen = self._get_current_specimen()
        config = self._get_current_config()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_excel.setEnabled(False)
        self.btn_pdf.setEnabled(False)

        mode_str = "인장 시험" if config.mode == TestMode.TENSILE else "압축 시험"
        self.statusBar().showMessage(f"시험 진행 중... [모드: {mode_str}, 시편: {specimen.specimen_id}]")

        self.active_driver.start_test(specimen, config)

    def _stop_test(self):
        self.active_driver.stop_test()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.statusBar().showMessage("시험이 사용자에 의해 중단되었습니다.")

    def _return_origin(self):
        self.lbl_load_val.setText("0.0")
        self.lbl_disp_val.setText("0.000")
        self.lbl_stress_val.setText("0.0")
        self.lbl_strain_val.setText("0.00")
        self.statusBar().showMessage("크로스헤드가 원점으로 복귀했습니다.")

    def _refresh_com_ports(self):
        self.combo_com_port.clear()
        ports = SerialUTMDriver.list_available_ports()
        if ports:
            for p, desc in ports:
                self.combo_com_port.addItem(f"{p} ({desc})", p)
        else:
            self.combo_com_port.addItem("검색된 COM 포트 없음", "")

    def _on_hw_mode_changed(self, idx: int):
        if idx == 0:
            self.active_driver = self.simulator
            self.lbl_hw_status.setText("● 가상 시뮬레이터 동작 중")
            self.lbl_hw_status.setStyleSheet("color: #0047BA; font-weight: 700; font-size: 10pt; margin-left: 12px;")
            self.statusBar().showMessage("동작 모드: 가상 물리 시뮬레이터 (Virtual)")
        else:
            self.active_driver = self.serial_driver
            self.lbl_hw_status.setText("● 실장비 모드 (연결 대기)")
            self.lbl_hw_status.setStyleSheet("color: #EA580C; font-weight: 700; font-size: 10pt; margin-left: 12px;")
            self.statusBar().showMessage("동작 모드: RS-232 실장비 (봉신 P2020/P2014)")

    def _toggle_hw_connection(self):
        if not self.serial_driver.is_connected:
            port = self.combo_com_port.currentData()
            if not port:
                QMessageBox.warning(self, "포트 선택 필요", "연결할 COM 포트를 선택해 주세요.\n(포트 새로고침 버튼을 눌러보세요)")
                return
            baud_str = self.combo_baud.currentText().split()[0]
            baud = int(baud_str)
            ok = self.serial_driver.connect(port=port, baudrate=baud)
            if ok:
                self.btn_connect_hw.setText("🔌  장비 연결 해제 (Disconnect)")
                self.btn_connect_hw.setStyleSheet("background-color: #E11D48; color: #FFFFFF; font-size: 11pt; font-weight: bold; min-height: 34px;")
                self.lbl_hw_status.setText(f"● 정상 연결됨 ({port} @ {baud} bps)")
                self.lbl_hw_status.setStyleSheet("color: #16A34A; font-weight: 700; font-size: 10pt; margin-left: 12px;")
                self.statusBar().showMessage(f"장비 연결 성공: {port} (봉신 P2020 / {baud} bps)")
            else:
                QMessageBox.critical(self, "연결 실패", f"{port} 포트에 연결할 수 없습니다.\n케이블 결선 및 전원을 확인해 주세요.")
        else:
            self.serial_driver.disconnect()
            self.btn_connect_hw.setText("🔌  장비 연결 (Connect)")
            self.btn_connect_hw.setStyleSheet("background-color: #0047BA; color: #FFFFFF; font-size: 11pt; font-weight: bold; min-height: 34px;")
            self.lbl_hw_status.setText("● 연결 해제됨")
            self.lbl_hw_status.setStyleSheet("color: #64748B; font-weight: 700; font-size: 10pt; margin-left: 12px;")
            self.statusBar().showMessage("장비 연결이 해제되었습니다.")

    def _tare_load(self):
        self.serial_driver.tare_load()
        self.lbl_load_val.setText("0.0")
        self.lbl_stress_val.setText("0.0")
        self.statusBar().showMessage("하중 영점(Tare Load)이 현재 값으로 보정되었습니다.")

    def _tare_disp(self):
        self.serial_driver.tare_displacement()
        self.lbl_disp_val.setText("0.000")
        self.lbl_strain_val.setText("0.00")
        self.statusBar().showMessage("변위 영점(Tare Disp)이 현재 값으로 보정되었습니다.")

    def _do_calib_zero(self):
        self.serial_driver.tare_load()
        offset = self.serial_driver.calib_mgr.data.load_zero_offset
        factor = self.serial_driver.calib_mgr.data.load_scale_factor
        self.lbl_load_factor.setText(f"현재 하중 보정 계수: {factor:.5f} (영점 오프셋: {offset:.2f})")
        QMessageBox.information(self, "영점 교정 완료", f"현재 센서값({offset:.2f})이 무부하 영점(Zero)으로 설정되었습니다.")

    def _do_calib_span(self):
        try:
            ref_val = float(self.edit_ref_load.text())
            unit = self.combo_ref_unit.currentText()
            factor = self.serial_driver.calibrate_load_span(ref_val, unit)
            last_date = self.serial_driver.calib_mgr.data.last_load_calib_date
            self.lbl_load_factor.setText(f"현재 하중 보정 계수: {factor:.5f} (최근: {last_date})")
            QMessageBox.information(self, "스팬 교정 완료", f"기준 하중 {ref_val} {unit}에 대한 스팬 교정이 완료되었습니다!\n계산된 보정 계수: {factor:.5f}\n(calib_config.json에 영구 저장됨)")
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 기준 하중 숫자를 입력해 주세요.")

    def _do_calib_speed(self):
        try:
            target_sp = float(self.edit_target_speed.text())
            dist = float(self.edit_measured_dist.text())
            factor = self.serial_driver.calibrate_speed(target_sp, dist, duration_sec=60.0)
            last_date = self.serial_driver.calib_mgr.data.last_speed_calib_date
            self.lbl_speed_factor.setText(f"현재 속도 보정 계수: {factor:.5f} (최근: {last_date})")
            QMessageBox.information(self, "속도 교정 완료", f"목표 속도 {target_sp} mm/min 대비 실측 {dist} mm 기준 속도 교정이 완료되었습니다!\n계산된 보정 계수: {factor:.5f}\n(calib_config.json에 영구 저장됨)")
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "올바른 속도 및 이동거리 숫자를 입력해 주세요.")

    def _on_raw_data_received(self, raw: str):
        # 탭 2 로그 창에 타임스탬프와 함께 출력
        now_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.txt_packet_log.append(f"[{now_str}] {raw.strip()}")
        # 너무 길어지면 위쪽 줄 정리 (최대 100줄)
        if self.txt_packet_log.document().lineCount() > 100:
            cursor = self.txt_packet_log.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.select(cursor.SelectionType.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    def _reset_data(self):
        self.data_points.clear()
        self.current_result = None
        self._return_origin()
        if HAS_PYQTGRAPH:
            self.plot_curve.setData([], [])
        self._clear_results_table()
        self.btn_excel.setEnabled(False)
        self.btn_pdf.setEnabled(False)
        self.statusBar().showMessage("계측 데이터가 초기화되었습니다.")

    def _on_data_received(self, point: DataPoint):
        self.data_points.append(point)

        # 계측 타일 업데이트
        self.lbl_load_val.setText(f"{point.load_n:,.1f}")
        self.lbl_disp_val.setText(f"{point.displacement_mm:.3f}")
        self.lbl_stress_val.setText(f"{point.stress_mpa:.1f}")
        self.lbl_strain_val.setText(f"{point.strain_pct:.2f}")

        # 실시간 곡선 플로팅 (성능 최적화: 2점마다 렌더링)
        if HAS_PYQTGRAPH and len(self.data_points) % 2 == 0:
            self._replot_graph()

    def _on_test_completed(self, reason: str):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_excel.setEnabled(True)
        self.btn_pdf.setEnabled(True)

        specimen = self._get_current_specimen()
        config = self._get_current_config()

        # 물성 계산
        self.current_result = MaterialCalculator.calculate(specimen, config, self.data_points, reason)
        self._update_results_table(self.current_result, reason)
        self._replot_graph()

        self.statusBar().showMessage(f"시험 완료: {reason} | 총 계측점: {len(self.data_points):,}개")
        QMessageBox.information(self, "시험 완료", f"시험이 완료되었습니다!\n결과: {reason}\n최대 하중: {self.current_result.peak_load_n:,.1f} N\n인장/압축강도: {self.current_result.peak_stress_mpa:.1f} MPa")

    def _replot_graph(self):
        if not HAS_PYQTGRAPH or not self.data_points:
            return
        if self.rb_graph_ss.isChecked():
            self.plot_widget.setLabel('bottom', 'Strain (%)')
            self.plot_widget.setLabel('left', 'Stress (MPa)')
            xs = [p.strain_pct for p in self.data_points]
            ys = [p.stress_mpa for p in self.data_points]
        else:
            self.plot_widget.setLabel('bottom', 'Displacement (mm)')
            self.plot_widget.setLabel('left', 'Load (N)')
            xs = [p.displacement_mm for p in self.data_points]
            ys = [p.load_n for p in self.data_points]
        self.plot_curve.setData(xs, ys)

    def _clear_results_table(self):
        for col in range(len(self.RESULT_COLUMNS)):
            self.table_results.setItem(0, col, QTableWidgetItem("-"))
            if self.table_results.item(0, col):
                self.table_results.item(0, col).setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    def _update_results_table(self, res: TestResult, reason: str):
        vals = [
            f"{res.peak_load_n:,.1f}",
            f"{res.peak_stress_mpa:.2f}",
            f"{res.yield_stress_mpa:.2f}",
            f"{res.elastic_modulus_gpa:.2f}",
            f"{res.elongation_pct:.2f}",
            f"{res.break_displacement_mm:.3f}",
            f"{res.energy_joule:.2f}",
            "파단 완료" if res.is_fractured else "시험 종료"
        ]
        for col, val in enumerate(vals):
            item = QTableWidgetItem(val)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_results.setItem(0, col, item)

    def _export_excel(self):
        if not self.current_result or not self.data_points:
            QMessageBox.warning(self, "경고", "내보낼 시험 결과 데이터가 없습니다.")
            return

        specimen = self._get_current_specimen()
        config = self._get_current_config()
        default_filename = f"UTM_{specimen.specimen_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        filepath, _ = QFileDialog.getSaveFileName(
            self, "엑셀 시험 데이터 저장", default_filename, "Excel Files (*.xlsx)"
        )
        if filepath:
            ExcelExporter.export(specimen, config, self.data_points, self.current_result, filepath)
            QMessageBox.information(self, "저장 완료", f"성공적으로 저장되었습니다:\n{filepath}")
            self.statusBar().showMessage(f"엑셀 저장 완료: {filepath}")

    def _export_pdf(self):
        if not self.current_result or not self.data_points:
            QMessageBox.warning(self, "경고", "내보낼 시험 결과 데이터가 없습니다.")
            return

        specimen = self._get_current_specimen()
        config = self._get_current_config()
        default_filename = f"Certificate_{specimen.specimen_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

        filepath, _ = QFileDialog.getSaveFileName(
            self, "PDF 시험 성적서 출력", default_filename, "PDF Files (*.pdf)"
        )
        if filepath:
            PDFExporter.export(specimen, config, self.data_points, self.current_result, filepath)
            QMessageBox.information(self, "출력 완료", f"공식 시험 성적서가 생성되었습니다:\n{filepath}")
            self.statusBar().showMessage(f"PDF 성적서 출력 완료: {filepath}")
