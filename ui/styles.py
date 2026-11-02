"""
Salt Sw ver.1 - Hyundai Marine Style Light Theme (현대해상 스타일 클린 테마)
현대해상 어플리케이션 특유의 신뢰감 있고 직관적인 화이트 & 하이 블루(Hi-Blue) 디자인
- 배경: 깨끗하고 부드러운 오프화이트 (#F3F5F8)
- 카드/컨테이너: 라운드 코너 순백색 카드 (#FFFFFF, Border-Radius: 12px)
- 브랜드 컬러: 현대해상 시그니처 블루 (#0047BA, #002C6C) & 하이 포인트 오렌지 (#FF5722)
- 텍스트: 높은 가독성의 딥 차콜 (#191F28) 및 소프트 슬레이트 (#64748B)
"""

HYUNDAI_THEME_QSS = """
QMainWindow {
    background-color: #F3F5F8;
}

QWidget {
    background-color: #F3F5F8;
    color: #191F28;
    font-family: 'Malgun Gothic', '맑은 고딕', 'Pretendard', 'Segoe UI', sans-serif;
    font-size: 10pt;
}

/* 상단 탭 위젯 (현대해상 스타일 모던 탭) */
QTabWidget::pane {
    border: 1px solid #E5E8EB;
    border-radius: 12px;
    background-color: #FFFFFF;
    top: -1px;
}

QTabBar::tab {
    background-color: #E2E8F0;
    color: #475569;
    font-size: 10.5pt;
    font-weight: 700;
    padding: 10px 22px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    margin-right: 6px;
    min-height: 22px;
}

QTabBar::tab:selected {
    background-color: #0047BA;
    color: #FFFFFF;
    font-weight: 800;
}

QTabBar::tab:hover:!selected {
    background-color: #CBD5E1;
    color: #002C6C;
}

/* 현대해상 스타일 카드형 그룹 박스 */
QGroupBox {
    border: 1px solid #E5E8EB;
    border-radius: 12px;
    margin-top: 14px;
    padding: 14px 10px 10px 10px;
    background-color: #FFFFFF;
    font-weight: bold;
    color: #002C6C;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 2px 8px;
    color: #0047BA;
    background-color: #EBF3FE;
    border-radius: 6px;
    font-size: 9.5pt;
    font-weight: bold;
}

/* 스크롤 영역 (테두리 없이 깔끔하게) */
QScrollArea {
    background-color: transparent;
    border: none;
}

QScrollBar:vertical {
    border: none;
    background: #F1F5F9;
    width: 8px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: #CBD5E1;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #94A3B8;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* 입력 필드 (화이트 & 블루 포커스) */
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {
    background-color: #FFFFFF;
    border: 1px solid #D1D5DB;
    border-radius: 8px;
    padding: 4px 8px;
    min-height: 28px;
    color: #191F28;
    selection-background-color: #0047BA;
    selection-color: #FFFFFF;
    font-size: 9.5pt;
}

QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {
    border: 2px solid #0047BA;
    background-color: #FFFFFF;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #E5E8EB;
    border-radius: 8px;
    selection-background-color: #EBF3FE;
    selection-color: #0047BA;
    padding: 4px;
}

/* 라디오 버튼 */
QRadioButton {
    background-color: transparent;
    color: #333D4B;
    font-weight: 500;
    spacing: 8px;
    min-height: 24px;
}

QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 2px solid #D1D5DB;
    background-color: #FFFFFF;
}

QRadioButton::indicator:checked {
    border: 5px solid #0047BA;
    background-color: #FFFFFF;
}

/* 체크박스 (결과 필터용) */
QCheckBox {
    background-color: transparent;
    color: #333D4B;
    font-size: 9pt;
    font-weight: 500;
    spacing: 6px;
    min-height: 22px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1.5px solid #94A3B8;
    background-color: #FFFFFF;
}

QCheckBox::indicator:checked {
    border: 1.5px solid #0047BA;
    background-color: #0047BA;
    image: none;
}

QCheckBox::indicator:hover {
    border-color: #0047BA;
}

/* 일반 버튼 (모던 플랫 화이트) */
QPushButton {
    background-color: #FFFFFF;
    border: 1px solid #D1D5DB;
    border-radius: 8px;
    padding: 6px 12px;
    min-height: 26px;
    font-weight: 600;
    color: #333D4B;
}

QPushButton:hover {
    background-color: #F8FAFC;
    border-color: #94A3B8;
}

QPushButton:pressed {
    background-color: #E2E8F0;
}

QPushButton:disabled {
    background-color: #F1F5F9;
    border-color: #E2E8F0;
    color: #94A3B8;
}

/* 주요 CTA 버튼 (현대해상 시그니처 컬러) */
QPushButton#btn_start {
    background-color: #0047BA;
    border: none;
    border-radius: 10px;
    color: #FFFFFF;
    font-size: 11pt;
    font-weight: bold;
    padding: 8px 16px;
    min-height: 32px;
}
QPushButton#btn_start:hover {
    background-color: #003893;
}
QPushButton#btn_start:pressed {
    background-color: #002C6C;
}

/* 비상 정지 버튼 (현대해상 오렌지 레드 포인트) */
QPushButton#btn_stop {
    background-color: #FF5722;
    border: none;
    border-radius: 10px;
    color: #FFFFFF;
    font-size: 11pt;
    font-weight: bold;
    padding: 8px 16px;
    min-height: 32px;
}
QPushButton#btn_stop:hover {
    background-color: #E64A19;
}
QPushButton#btn_stop:pressed {
    background-color: #BF360C;
}

/* 데이터 내보내기 버튼 */
QPushButton#btn_excel {
    background-color: #059669;
    border: none;
    border-radius: 8px;
    color: #FFFFFF;
    font-weight: bold;
    min-height: 28px;
}
QPushButton#btn_excel:hover {
    background-color: #047857;
}

QPushButton#btn_pdf {
    background-color: #0047BA;
    border: none;
    border-radius: 8px;
    color: #FFFFFF;
    font-weight: bold;
    min-height: 28px;
}
QPushButton#btn_pdf:hover {
    background-color: #003893;
}

/* 대형 디지털 계측값 타일 (현대해상 카드 UI) */
QFrame.readout-tile {
    background-color: #FFFFFF;
    border: 1px solid #E5E8EB;
    border-radius: 14px;
    padding: 8px 12px;
}

QLabel.readout-label {
    background-color: transparent;
    font-size: 9pt;
    font-weight: 600;
    color: #6B7684;
}

QLabel.readout-value {
    background-color: transparent;
    font-family: 'Consolas', 'Segoe UI', monospace;
    font-size: 24pt;
    font-weight: 800;
    color: #002C6C;
}

QLabel.readout-unit {
    background-color: transparent;
    font-size: 10pt;
    font-weight: 700;
    color: #0047BA;
}

/* 상태 바 */
QStatusBar {
    background-color: #FFFFFF;
    color: #64748B;
    border-top: 1px solid #E5E8EB;
    padding: 4px 10px;
    font-size: 9pt;
}

/* 결과 분석 테이블 */
QTableWidget {
    background-color: #FFFFFF;
    border: 1px solid #E5E8EB;
    border-radius: 10px;
    gridline-color: #F1F5F9;
    color: #191F28;
    font-size: 9.5pt;
}

QHeaderView::section {
    background-color: #F8FAFC;
    color: #475569;
    font-weight: bold;
    padding: 6px 4px;
    border: none;
    border-bottom: 2px solid #E2E8F0;
    font-size: 9pt;
}

QTableWidget::item:selected {
    background-color: #EBF3FE;
    color: #0047BA;
}
"""

DARK_THEME_QSS = HYUNDAI_THEME_QSS
