# Salt Sw ver.1 — Universal Testing Machine (UTM) Software

만능재료시험기(Universal Testing Machine, UTM)의 실시간 계측, 인장·압축 시험 제어, 물성치 자동 계산 및 엑셀(Excel)·PDF 성적서 출력 소프트웨어입니다.

---

## 📌 주요 기능 (Key Features)

1. **실시간 데이터 계측 및 디스플레이 (Real-time DAQ & Monitoring)**
   - **Load (하중, N / kN)**, **Disp (변위, mm)**, **Stress (응력, MPa)**, **Strain (변형률, %)** 고시인성 대형 디지털 타일 표시
   - 고속 실시간 **S-S Curve (응력-변형률 곡선)** 및 **하중-변위 곡선** 동적 플로팅
2. **다양한 시험 모드 및 시편 설정 (Test Modes & Specimen Setup)**
   - **인장 시험 (Tensile Test)** / **압축 시험 (Compression Test)** 지원
   - 시편 형태 지원: 판재(Flat), 봉재(Round), 관형(Tube)
   - 폭, 두께, 직경, 표점거리(L0) 입력에 따른 단면적(A0) 자동 계산
   - 크로스헤드 시험 속도(mm/min) 및 피크 하중 대비 파단 감지 드롭 비율(%) 설정
3. **재료 기계적 물성치 자동 산출 (Material Property Calculation)**
   - **최대 하중 (Peak Load, Pmax)** 및 **인장/압축 강도 (Tensile/Compressive Strength, Rm)**
   - **0.2% 오프셋 항복강도 (Yield Strength, Rp0.2)** 및 항복 하중
   - **탄성 계수 (Young's Modulus, E)** 자동 선형 회귀 분석
   - **파단 연신율 (Elongation at Break, A)** 및 파단 변위
   - **흡수 에너지 (Toughness / Absorbed Energy, U)** 적분 연산
4. **보고서 및 데이터 내보내기 (Reports & Exporting)**
   - **엑셀 (.xlsx)**: 시험 제원 요약 시트 + 전 시점 원시 계측 데이터(Raw Data) 시트 분리 출력
   - **PDF 시험 성적서 (.pdf)**: 시험 결과 요약표 + 선명한 벡터 S-S 곡선 그래프 + 결재/서명란 포함 정식 시험 성적서
5. **가상 계측 시뮬레이터 내장 (Built-in Virtual Hardware Simulator)**
   - 실제 하드웨어 연결 전에도 개발, 검증, 시연이 가능하도록 물리 기반 가상 하드웨어 엔진 탑재 (선형 탄성, 소성 가공경화, 네킹, 파단 시뮬레이션)

---

## 🏗 프로젝트 구조 (Architecture)

```text
salt-sw-v1/
├── core/
│   ├── __init__.py
│   ├── models.py              # 시편, 시험조건, 계측데이터, 시험결과 데이터 모델
│   ├── simulator.py           # 가상 계측기 하드웨어 물리 시뮬레이터
│   ├── calculator.py          # 물성치(인장강도, 항복강도, 연신율 등) 자동 연산기
│   └── hardware_interface.py  # 실제 장비 연동용 추상 하드웨어 인터페이스
├── exporters/
│   ├── __init__.py
│   ├── excel_exporter.py      # openpyxl 기반 스타일 서식 적용 엑셀 생성기
│   └── pdf_exporter.py        # reportlab 기반 벡터 S-S 곡선 포함 PDF 성적서 생성기
├── ui/
│   ├── __init__.py
│   ├── main_window.py         # PyQt6 기반 전문 UTM 대시보드 윈도우
│   └── styles.py              # 산업용 고시인성 다크 테마 QSS
├── output/                    # 엑셀 및 PDF 결과물 저장 디렉토리
├── cli_demo.py                # 터미널 즉시 실행 및 기능 검증 데모 스크립트
├── main.py                    # GUI 메인 애플리케이션 실행 파일
├── requirements.txt           # 필수 패키지 목록
└── README.md                  # 프로젝트 설명서
```

---

## 🚀 빠른 시작 (Quick Start)

### 1. 환경 설정 및 의존성 설치
```bash
git clone https://github.com/siwootldn-code/Salt-Sw-ver.1.git
cd Salt-Sw-ver.1

# 가상환경 생성 (권장)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 패키지 설치
pip install -r requirements.txt
```

### 2. GUI 프로그램 실행
```bash
python main.py
```

### 3. 터미널(CLI) 데모 및 리포트 생성 테스트
디스플레이 화면이 없는 환경이나 빠른 기능 검증을 위해 CLI 데모를 실행할 수 있습니다.
```bash
python cli_demo.py
```
실행 시 가상 인장 시험이 진행되고, `output/` 폴더에 즉시 엑셀(`Salt_UTM_Demo_Report.xlsx`)과 PDF(`Salt_UTM_Demo_Certificate.pdf`)가 생성됩니다.

---

## 🔌 실제 시험기 하드웨어 연동 안내 (Hardware Integration)

`core/hardware_interface.py`의 `HardwareInterface` 추상 클래스를 상속받아 실제 로드셀 인디케이터나 모터 컨트롤러 드라이버를 구현할 수 있습니다.

```python
from core.hardware_interface import HardwareInterface
from core.models import DataPoint, Specimen, TestConfig
import serial

class SerialUTMHardware(HardwareInterface):
    def connect(self, port="COM3", baudrate=115200):
        self.ser = serial.Serial(port, baudrate, timeout=1.0)
        self.is_connected = True
        return True

    def start_test(self, specimen: Specimen, config: TestConfig):
        # 1. 모터 속도 설정 명령 송신 (예: Modbus 또는 ASCII Command)
        # 2. 로드셀/인코더 계측 스레드 시작
        # 3. 실시간 DataPoint 생성 후 self.on_data_received(point) 호출
        pass

    def stop_test(self):
        # 모터 긴급 정지 명령 송신
        self.ser.write(b"STOP\r\n")
```

---

## 📄 라이선스 (License)
Copyright (c) 2026 Salt Tech / 강태관. All rights reserved.
