"""
Salt Sw ver.1 - Industrial Precision Theme (글로벌 정밀 계측기 표준 테마)
Instron Bluehill & Shimadzu TRAPEZIUM 스타일의 고정밀 산업용 시험기 UI
- AI 슬롭/플라스틱 효과 100% 배제: 과도한 그라데이션, 유치한 라운딩, 이모지 일체 제거
- 정갈한 타이포그래피: Windows 11 Malgun Gothic / Segoe UI 고정폭 정렬
- 명확한 시인성: Slate-900 (#0F172A), Precision Blue (#1D4ED8), Neutral Slate Border (#CBD5E1)
- 윈도우 11 충돌 방지: High-DPI 100~200% 스케일링 완전 대응 및 네이티브 프레임 친화성
"""

HYUNDAI_THEME_QSS = """
QMainWindow {
    background-color: #F8FAFC;
}

QWidget {
    background-color: #F8FAFC;
    color: #0F172A;
    font-family: 'Segoe UI', 'Malgun Gothic', '맑은 고딕', sans-serif;
    font-size: 9.5pt;
}

/* 상단 탭 위젯 (Windows 11 인더스트리얼 세그먼트 탭) */
QTabWidget::pane {
    border: 1px solid #CBD5E1;
    border-radius: 4px;
    background-color: #FFFFFF;
    top: -1px;
}

QTabBar::tab {
    background-color: #F1F5F9;
    color: #475569;
    font-size: 10pt;
    font-weight: 600;
    padding: 8px 20px;
    border: 1px solid #CBD5E1;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 4px;
    min-height: 20px;
}

QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: #1D4ED8;
    font-weight: 700;
    border-bottom: 2px solid #1D4ED8;
}

QTabBar::tab:hover:!selected {
    background-color: #E2E8F0;
    color: #1E293B;
}

/* 정밀 카드형 그룹 박스 (Instron 스타일 간결한 라벨) */
QGroupBox {
    border: 1px solid #CBD5E1;
    border-radius: 4px;
    margin-top: 10px;
    padding: 12px 10px 10px 10px;
    background-color: #FFFFFF;
    font-weight: 700;
    color: #0F172A;
    font-size: 9.5pt;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 1px 6px;
    color: #1E293B;
    background-color: #F1F5F9;
    border: 1px solid #CBD5E1;
    border-radius: 3px;
    font-size: 8.5pt;
    font-weight: 700;
}

/* 스크롤 영역 */
QScrollArea {
    background-color: transparent;
    border: none;
}

QScrollBar:vertical {
    border: none;
    background: #F1F5F9;
    width: 6px;
    border-radius: 3px;
}

QScrollBar::handle:vertical {
    background: #94A3B8;
    min-height: 24px;
    border-radius: 3px;
}

QScrollBar::handle:vertical:hover {
    background: #64748B;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* 텍스트 입력창 및 스핀박스 */
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    border: 1px solid #CBD5E1;
    border-radius: 3px;
    padding: 4px 8px;
    background-color: #FFFFFF;
    color: #0F172A;
    font-size: 9.5pt;
    min-height: 24px;
}

QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #1D4ED8;
    background-color: #FFFFFF;
}

QLineEdit:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled, QComboBox:disabled {
    background-color: #F1F5F9;
    color: #94A3B8;
    border-color: #E2E8F0;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border-left: 1px solid #CBD5E1;
    background-color: #F8FAFC;
}

/* 라디오 버튼 (간결한 세그먼트 느낌) */
QRadioButton {
    font-size: 9.5pt;
    font-weight: 600;
    color: #334155;
    spacing: 6px;
}

QRadioButton:checked {
    color: #1D4ED8;
}

QRadioButton::indicator {
    width: 14px;
    height: 14px;
}

/* 표준 계측기 제어 버튼 (Flat Solid Design) */
QPushButton {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 3px;
    color: #1E293B;
    font-size: 9.5pt;
    font-weight: 600;
    padding: 6px 14px;
    min-height: 26px;
}

QPushButton:hover {
    background-color: #F1F5F9;
    border-color: #94A3B8;
}

QPushButton:pressed {
    background-color: #E2E8F0;
}

QPushButton:disabled {
    background-color: #F8FAFC;
    color: #94A3B8;
    border-color: #E2E8F0;
}

/* 주요 액션 버튼 (Primary, Start, Stop) */
QPushButton#btn_start {
    background-color: #059669;
    color: #FFFFFF;
    border: 1px solid #047857;
    font-weight: 700;
    font-size: 10.5pt;
    min-height: 34px;
}

QPushButton#btn_start:hover {
    background-color: #047857;
}

QPushButton#btn_stop {
    background-color: #DC2626;
    color: #FFFFFF;
    border: 1px solid #B91C1C;
    font-weight: 700;
    font-size: 10.5pt;
    min-height: 34px;
}

QPushButton#btn_stop:hover {
    background-color: #B91C1C;
}

QPushButton#btn_stop:disabled {
    background-color: #F1F5F9;
    color: #94A3B8;
    border-color: #E2E8F0;
}

/* 대형 디지털 계측 타일 (Instron Bluehill Style Readout) */
QFrame[class="readout-tile"] {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 4px;
    border-top: 3px solid #1D4ED8;
}

QLabel[class="readout-label"] {
    font-size: 8pt;
    font-weight: 700;
    color: #64748B;
    letter-spacing: 0.5px;
    background-color: transparent;
}

QLabel[class="readout-value"] {
    font-size: 20pt;
    font-weight: 800;
    color: #0F172A;
    font-family: 'Consolas', 'Segoe UI', monospace;
    background-color: transparent;
}

QLabel[class="readout-unit"] {
    font-size: 9pt;
    font-weight: 600;
    color: #64748B;
    background-color: transparent;
}

/* 결과 테이블 (고대비 그리드) */
QTableWidget {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 3px;
    gridline-color: #E2E8F0;
    font-size: 9pt;
}

QHeaderView::section {
    background-color: #F1F5F9;
    color: #334155;
    font-size: 8.5pt;
    font-weight: 700;
    padding: 6px 4px;
    border: none;
    border-right: 1px solid #E2E8F0;
    border-bottom: 1px solid #CBD5E1;
}

/* 상태 바 */
QStatusBar {
    background-color: #FFFFFF;
    border-top: 1px solid #CBD5E1;
    color: #475569;
    font-size: 8.5pt;
    min-height: 22px;
}
"""
