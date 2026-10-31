"""
Salt Sw ver.1 - Universal Testing Machine (UTM) Software
메인 실행 진입점 (Application Entrypoint)
"""

import sys
import os

# 모듈 경로 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow


def main():
    """애플리케이션 초기화 및 실행"""
    # 고해상도(High DPI) 디스플레이 설정
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("Salt Sw ver.1")
    app.setOrganizationName("Salt Tech")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
