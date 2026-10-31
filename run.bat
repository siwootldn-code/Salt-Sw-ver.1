@echo off
chcp 65001 > nul
title Salt Sw ver.1 - Universal Testing Machine (UTM)

echo ======================================================================
echo    Salt Sw ver.1 — Universal Testing Machine (UTM) Software
echo ======================================================================
echo.

:: 1. 파이썬 설치 여부 확인
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] Python이 설치되어 있지 않거나 환경 변수(PATH)에 등록되지 않았습니다.
    echo https://www.python.org 에서 Python 3.10 이상을 설치하실 때
    echo "Add python.exe to PATH" 체크박스를 꼭 선택해 주세요.
    echo.
    pause
    exit /b
)

:: 2. 필수 패키지 설치 확인
echo [1/2] 필수 라이브러리(PyQt6, pyqtgraph, reportlab 등) 확인 중...
pip install -r requirements.txt --quiet

:: 3. 프로그램 실행
echo [2/2] Salt Sw ver.1 프로그램을 시작합니다...
echo.
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [안내] 프로그램이 종료되었습니다.
    pause
)
