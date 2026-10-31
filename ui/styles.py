"""
Salt Sw ver.1 - Modern Industrial Dark Theme
산업용 계측기 및 정밀 시험 소프트웨어에 최적화된 고시인성 다크 테마
"""

DARK_THEME_QSS = """
QMainWindow {
    background-color: #0F172A;
}

QWidget {
    background-color: #0F172A;
    color: #F8FAFC;
    font-family: 'Segoe UI', '맑은 고딕', sans-serif;
    font-size: 10pt;
}

/* 그룹 박스 */
QGroupBox {
    border: 1px solid #334155;
    border-radius: 8px;
    margin-top: 18px;
    padding-top: 14px;
    background-color: #1E293B;
    font-weight: bold;
    color: #94A3B8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #38BDF8;
}

/* 입력 위젯 */
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {
    background-color: #0F172A;
    border: 1px solid #475569;
    border-radius: 5px;
    padding: 6px 10px;
    color: #F8FAFC;
    selection-background-color: #0284C7;
}

QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #38BDF8;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

/* 버튼 스타일 */
QPushButton {
    background-color: #334155;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
    color: #F8FAFC;
}

QPushButton:hover {
    background-color: #475569;
}

QPushButton:pressed {
    background-color: #1E293B;
}

/* 주요 제어 버튼 특수 색상 */
QPushButton#btn_start {
    background-color: #059669;
    border: 1px solid #10B981;
    font-size: 11pt;
}
QPushButton#btn_start:hover {
    background-color: #10B981;
}

QPushButton#btn_stop {
    background-color: #DC2626;
    border: 1px solid #EF4444;
    font-size: 11pt;
}
QPushButton#btn_stop:hover {
    background-color: #EF4444;
}

QPushButton#btn_excel {
    background-color: #15803D;
    border: 1px solid #22C55E;
}
QPushButton#btn_excel:hover {
    background-color: #16A34A;
}

QPushButton#btn_pdf {
    background-color: #B91C1C;
    border: 1px solid #F87171;
}
QPushButton#btn_pdf:hover {
    background-color: #DC2626;
}

/* 대형 디지털 계측값 타일 (LCD Readout Style) */
QFrame.readout-tile {
    background-color: #1E293B;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 8px;
}

QLabel.readout-label {
    font-size: 10pt;
    font-weight: bold;
    color: #94A3B8;
}

QLabel.readout-value {
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 26pt;
    font-weight: bold;
    color: #38BDF8;
}

QLabel.readout-unit {
    font-size: 11pt;
    font-weight: bold;
    color: #64748B;
}

/* 상태 바 */
QStatusBar {
    background-color: #0B0F19;
    color: #94A3B8;
    border-top: 1px solid #1E293B;
}

/* 테이블 위젯 */
QTableWidget {
    background-color: #1E293B;
    border: 1px solid #334155;
    border-radius: 6px;
    gridline-color: #334155;
}

QHeaderView::section {
    background-color: #0F172A;
    color: #94A3B8;
    font-weight: bold;
    padding: 6px;
    border: 1px solid #334155;
}
"""
