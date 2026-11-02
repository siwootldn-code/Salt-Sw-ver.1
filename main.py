"""
Salt Sw ver.1 - Universal Testing Machine (UTM) Software
메인 실행 진입점 (Application Entrypoint)
"""

import sys
import os

# 고해상도(High DPI) 및 폰트 렌더링 최적화 환경변수 (QApplication 생성 전 설정)
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

# 모듈 경로 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow


def main():
    """애플리케이션 초기화 및 실행"""
    app = QApplication(sys.argv)
    app.setApplicationName("Salt Sw ver.1")
    app.setOrganizationName("Salt Tech")

    # 윈도우 한글 폰트 선명도 기본값 적용
    app_font = QFont("Malgun Gothic", 10)
    app_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(app_font)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
