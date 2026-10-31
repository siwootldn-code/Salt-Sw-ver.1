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
    QTableWidgetItem, QFileDialog, QMessageBox, QFrame, QHeaderView
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
from ui.styles import DARK_THEME_QSS


class CommunicateBridge(QObject):
    """스레드 안전한 실시간 데이터 전송 브리지"""
    data_received = pyqtSignal(DataPoint)
    test_completed = pyqtSignal(str)
    raw_data_received = pyqtSignal(str)


class MainWindow(QMainWindow):
    """Salt Sw ver.1 메인 애플리케이션 윈도우"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Salt Sw ver.1 — Universal Testing Machine (UTM)")
        self.resize(1280, 850)
        self.setStyleSheet(DARK_THEME_QSS)

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
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(14)

        # 1. 좌측 제어 및 설정 패널 (폭 360px)
        left_panel = self._create_left_panel()
        main_layout.addWidget(left_panel, stretch=0)

        # 2. 우측 모니터링 패널 (계측 타일 + 실시간 그래프 + 결과표)
        right_panel = self._create_right_panel()
        main_layout.addWidget(right_panel, stretch=1)

        # 상태 바
        self.statusBar().showMessage("장비 상태: 대기 중 (READY) | 가상 계측기 활성화됨")

    def _create_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 브랜드 헤더
        brand_label = QLabel("SALT SW VER.1")
        brand_label.setStyleSheet("font-size: 16pt; font-weight: bold; color: #38BDF8; letter-spacing: 1px;")
        sub_label = QLabel("Universal Testing Machine Control System")
        sub_label.setStyleSheet("font-size: 9pt; color: #64748B; margin-bottom: 4px;")
        layout.addWidget(brand_label)
        layout.addWidget(sub_label)

        # 0. 계측 장비 연동 그룹 (Bongshin P2020 / P2014)
        hw_group = QGroupBox("계측 장비 연동 (Hardware & RS-232)")
        hw_layout = QGridLayout(hw_group)
        hw_layout.setSpacing(6)

        hw_layout.addWidget(QLabel("동작 모드:"), 0, 0)
        self.combo_hw_mode = QComboBox()
        self.combo_hw_mode.addItems(["가상 시뮬레이터 (Virtual)", "RS-232 실장비 (봉신 P2020/2014)"])
        self.combo_hw_mode.currentIndexChanged.connect(self._on_hw_mode_changed)
        hw_layout.addWidget(self.combo_hw_mode, 0, 1, 1, 2)

        hw_layout.addWidget(QLabel("COM 포트:"), 1, 0)
        self.combo_com_port = QComboBox()
        self.btn_refresh_ports = QPushButton("🔄")
        self.btn_refresh_ports.setToolTip("포트 목록 새로고침")
        self.btn_refresh_ports.setFixedWidth(36)
        self.btn_refresh_ports.clicked.connect(self._refresh_com_ports)
        hw_layout.addWidget(self.combo_com_port, 1, 1)
        hw_layout.addWidget(self.btn_refresh_ports, 1, 2)
        self._refresh_com_ports()

        hw_layout.addWidget(QLabel("통신 속도:"), 2, 0)
        self.combo_baud = QComboBox()
        self.combo_baud.addItems(["115200 (봉신 P2020/2014)", "57600", "38400", "19200", "9600"])
        hw_layout.addWidget(self.combo_baud, 2, 1, 1, 2)

        self.btn_connect_hw = QPushButton("🔌 장비 연결 (Connect)")
        self.btn_connect_hw.clicked.connect(self._toggle_hw_connection)
        hw_layout.addWidget(self.btn_connect_hw, 3, 0, 1, 3)

        # 영점 맞춤(Tare) 버튼
        h_tare = QHBoxLayout()
        self.btn_tare_load = QPushButton("0️⃣ 하중 영점")
        self.btn_tare_load.clicked.connect(self._tare_load)
        self.btn_tare_disp = QPushButton("0️⃣ 변위 영점")
        self.btn_tare_disp.clicked.connect(self._tare_disp)
        h_tare.addWidget(self.btn_tare_load)
        h_tare.addWidget(self.btn_tare_disp)
        hw_layout.addLayout(h_tare, 4, 0, 1, 3)

        # 수신 패킷 모니터링 라벨
        self.lbl_raw_packet = QLabel("수신 패킷: 대기 중")
        self.lbl_raw_packet.setStyleSheet("font-size: 8pt; color: #94A3B8; background: #0B0F19; padding: 4px; border-radius: 4px;")
        hw_layout.addWidget(self.lbl_raw_packet, 5, 0, 1, 3)

        layout.addWidget(hw_group)

        # A. 시험 모드 선택 그룹
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

        # B. 시편 제원 설정 그룹
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

        # C. 시험 조건 설정 그룹
        cond_group = QGroupBox("시험 조건 (Test Conditions)")
        cond_layout = QGridLayout(cond_group)

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

    def _create_right_panel() -> QWidget:
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
            pg.setConfigOption('background', '#0B0F19')
            pg.setConfigOption('foreground', '#94A3B8')
            pg.setConfigOptions(antialias=True)
            self.plot_widget = pg.PlotWidget()
            self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
            self.plot_widget.setLabel('bottom', 'Strain (%)')
            self.plot_widget.setLabel('left', 'Stress (MPa)')
            self.plot_curve = self.plot_widget.plot(pen=pg.mkPen(color='#38BDF8', width=2))
            graph_box_layout.addWidget(self.plot_widget)
        else:
            self.plot_widget = QLabel("PyQtGraph 라이브러리가 설치되면 고속 실시간 그래프가 활성화됩니다.")
            self.plot_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.plot_widget.setStyleSheet("background-color: #0B0F19; border: 1px solid #334155; border-radius: 6px;")
            graph_box_layout.addWidget(self.plot_widget)

        layout.addWidget(graph_box, stretch=3)

        # 3. 하단 시험 결과 요약 테이블
        res_box = QGroupBox("주요 기계적 물성 분석 결과 (Test Results)")
        res_layout = QVBoxLayout(res_box)
        self.table_results = QTableWidget()
        self.table_results.setColumnCount(8)
        self.table_results.setHorizontalHeaderLabels([
            "최대 하중 (Pmax, N)", "인장/압축강도 (Rm, MPa)", "항복강도 (Rp0.2, MPa)",
            "탄성계수 (E, GPa)", "파단 연신율 (A, %)", "파단 변위 (dL, mm)",
            "흡수에너지 (U, J)", "시험 결과 판정"
        ])
        self.table_results.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_results.setRowCount(1)
        self._clear_results_table()
        res_layout.addWidget(self.table_results)
        layout.addWidget(res_box, stretch=1)

        return panel

    def _create_tile(self, label_text: str, default_val: str, unit_text: str):
        tile = QFrame()
        tile.setProperty("class", "readout-tile")
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        lbl = QLabel(label_text)
        lbl.setProperty("class", "readout-label")
        val = QLabel(default_val)
        val.setProperty("class", "readout-value")
        val.setAlignment(Qt.AlignmentFlag.AlignRight)
        unit = QLabel(unit_text)
        unit.setProperty("class", "readout-unit")
        unit.setAlignment(Qt.AlignmentFlag.AlignRight)

        layout.addWidget(lbl)
        layout.addWidget(val)
        layout.addWidget(unit)
        return tile, val

    def _on_specimen_type_changed(self, index: int):
        if index == 1:  # Round
            self.lbl_width.setText("직경 (Dia, mm):")
            self.lbl_thick.setEnabled(False)
            self.spin_thick.setEnabled(False)
        else:
            self.lbl_width.setText("폭 (Width, mm):")
            self.lbl_thick.setEnabled(True)
            self.spin_thick.setEnabled(True)

    def _get_current_specimen(self) -> Specimen:
        spec_type = SpecimenType.ROUND if self.combo_type.currentIndex() == 1 else SpecimenType.FLAT
        return Specimen(
            specimen_id=self.edit_specimen_id.text().strip() or "SPECIMEN-001",
            material=self.edit_material.text().strip() or "SS400",
            specimen_type=spec_type,
            width_mm=self.spin_width.value(),
            thickness_mm=self.spin_thick.value(),
            diameter_mm=self.spin_width.value(),
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
        self.statusBar().showMessage(f"시험 진행 중... [모드: {config.mode.value}, 시편: {specimen.specimen_id}]")

        self.active_driver.start_test(specimen, config)

    def _stop_test(self):
        self.active_driver.stop_test()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.statusBar().showMessage("시험이 사용자에 의해 정지되었습니다.")

    def _return_origin(self):
        self.active_driver.return_to_origin()
        self.lbl_load_val.setText("0.0")
        self.lbl_disp_val.setText("0.000")
        self.lbl_stress_val.setText("0.0")
        self.lbl_strain_val.setText("0.00")
        self.statusBar().showMessage("크로스헤드가 원점으로 복귀했습니다.")

    def _refresh_com_ports(self):
        current = self.combo_com_port.currentText()
        self.combo_com_port.clear()
        ports = SerialUTMDriver.list_available_ports()
        self.combo_com_port.addItems(ports)
        idx = self.combo_com_port.findText(current)
        if idx >= 0:
            self.combo_com_port.setCurrentIndex(idx)

    def _on_hw_mode_changed(self, idx: int):
        if idx == 0:
            self.active_driver = self.simulator
            self.statusBar().showMessage("장비 상태: 가상 시뮬레이터 활성화됨")
        else:
            self.active_driver = self.serial_driver
            self.statusBar().showMessage("장비 상태: RS-232 실장비 모드 (봉신 P2020/P2014) 활성화됨")

    def _toggle_hw_connection(self):
        if not self.serial_driver.is_connected:
            port = self.combo_com_port.currentText()
            baud_text = self.combo_baud.currentText().split()[0]
            baud = int(baud_text)
            ok = self.serial_driver.connect(port=port, baudrate=baud)
            if ok:
                self.btn_connect_hw.setText("🔌 연결 해제 (Disconnect)")
                self.btn_connect_hw.setStyleSheet("background-color: #EF4444; color: white;")
                self.combo_hw_mode.setCurrentIndex(1)
                self.statusBar().showMessage(f"장비 연결 성공: {port} @ {baud} bps")
                QMessageBox.information(self, "연결 성공", f"봉신 P2020/P2014 인디케이터가 {port} ({baud} bps)에 정상 연결되었습니다.")
            else:
                QMessageBox.warning(self, "연결 실패", f"{port} 포트에 연결할 수 없습니다.\n케이블 연결 및 COM 포트 번호를 확인해 주세요.")
        else:
            self.serial_driver.disconnect()
            self.btn_connect_hw.setText("🔌 장비 연결 (Connect)")
            self.btn_connect_hw.setStyleSheet("")
            self.lbl_raw_packet.setText("수신 패킷: 대기 중")
            self.statusBar().showMessage("장비 연결이 해제되었습니다.")

    def _tare_load(self):
        self.active_driver.tare_load()
        self.lbl_load_val.setText("0.0")
        self.statusBar().showMessage("하중 영점(Tare)이 현재 값으로 세팅되었습니다.")

    def _tare_disp(self):
        self.active_driver.tare_displacement()
        self.lbl_disp_val.setText("0.000")
        self.statusBar().showMessage("변위 영점(Tare)이 현재 값으로 세팅되었습니다.")

    def _on_raw_data_received(self, raw: str):
        self.lbl_raw_packet.setText(f"수신: {raw[:30]}")

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

        # 실시간 그래프 업데이트 (5개 샘플마다 갱신하여 렌더링 최적화)
        if HAS_PYQTGRAPH and len(self.data_points) % 2 == 0:
            if self.rb_graph_ss.isChecked():
                xs = [p.strain_pct for p in self.data_points]
                ys = [p.stress_mpa for p in self.data_points]
            else:
                xs = [p.displacement_mm for p in self.data_points]
                ys = [p.load_n for p in self.data_points]
            self.plot_curve.setData(xs, ys)

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
        for col in range(8):
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
        for col, v in enumerate(vals):
            item = QTableWidgetItem(v)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_results.setItem(0, col, item)

    def _export_excel(self):
        if not self.data_points or not self.current_result:
            QMessageBox.warning(self, "저장 불가", "내보낼 시험 데이터가 없습니다.")
            return

        filename = f"Salt_UTM_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        filepath, _ = QFileDialog.getSaveFileName(self, "엑셀 파일로 저장", filename, "Excel Files (*.xlsx)")
        if filepath:
            try:
                ExcelExporter.export(
                    filepath, self._get_current_specimen(),
                    self._get_current_config(), self.current_result, self.data_points
                )
                QMessageBox.information(self, "저장 완료", f"엑셀 파일이 성공적으로 저장되었습니다:\n{filepath}")
            except Exception as e:
                QMessageBox.critical(self, "저장 실패", f"엑셀 저장 중 오류가 발생했습니다:\n{str(e)}")

    def _export_pdf(self):
        if not self.data_points or not self.current_result:
            QMessageBox.warning(self, "저장 불가", "내보낼 시험 데이터가 없습니다.")
            return

        filename = f"Salt_UTM_Certificate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        filepath, _ = QFileDialog.getSaveFileName(self, "시험 성적서 PDF 저장", filename, "PDF Files (*.pdf)")
        if filepath:
            try:
                PDFExporter.export(
                    filepath, self._get_current_specimen(),
                    self._get_current_config(), self.current_result, self.data_points
                )
                QMessageBox.information(self, "저장 완료", f"시험 성적서 PDF가 성공적으로 저장되었습니다:\n{filepath}")
            except Exception as e:
                QMessageBox.critical(self, "저장 실패", f"PDF 저장 중 오류가 발생했습니다:\n{str(e)}")
