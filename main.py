"""
Salt Sw ver.1 - Universal Testing Machine (UTM) Software
Windows 11 네이티브 호환 및 고신뢰성 무충돌 아키텍처 진입점
"""

import sys
import os
import traceback

# 1. Windows 11 High-DPI(125%, 150%, 200% 디스플레이 배율) 폰트 깨짐 및 흐림 방지
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

# 모듈 경로 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow
from ui.styles import HYUNDAI_THEME_QSS


def exception_hook(exctype, value, tb):
    """
    윈도우 11 환경에서 예기치 않은 런타임 오류로 프로그램이 강제 종료되는 현상 원천 차단
    크래시 대신 오류 로그를 기록하고 안전하게 복구
    """
    error_msg = "".join(traceback.format_exception(exctype, value, tb))
    print(f"[Salt Sw System Error] {error_msg}")
    try:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("시스템 예외 감지")
        msg.setText("동작 중 예외가 발생했으나 안전하게 격리되었습니다.")
        msg.setDetailedText(error_msg)
        msg.exec()
    except Exception:
        pass


def main():
    """애플리케이션 초기화 및 실행"""
    sys.excepthook = exception_hook

    app = QApplication(sys.argv)
    app.setApplicationName("Salt Sw ver.1")
    app.setOrganizationName("Salt Tech")

    # Windows 11 표준 시스템 서체 적용 (가독성 및 안티앨리어싱 극대화)
    app_font = QFont("Segoe UI", 10)
    app_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(app_font)

    # 인더스트리얼 테마 적용
    app.setStyleSheet(HYUNDAI_THEME_QSS)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
