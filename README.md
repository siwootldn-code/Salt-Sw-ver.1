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
6. **신율계(Extensometer) 호환 — mV 타입 · 펄스 타입 (Extensometer Support)**
   - 환경 설정에서 **사용 안 함 / 사용함**을 선택하고, 사용 시 **mV 타입(아날로그 mV/V)** 또는 **펄스 타입(엔코더 Pulse)** 을 지정
   - mV 타입: 정격 출력(mV/V)·정격 변위(mm)·여자 전압(V)·교정 계수·영점 오프셋(mV), 표점거리(GL)
   - 펄스 타입: 분해능(mm/pulse)·방향 반전·영점 카운트, 표점거리(GL)
   - 신율계를 사용하면 **탄성계수(E)·0.2% 오프셋 항복강도(Rp0.2)·연신율(A)** 을 신율계 변위 기준으로 계산하고, 결과·엑셀·PDF 성적서에 **측정 소스(크로스헤드 / 신율계 mV / 신율계 펄스)** 를 기록
   - 설정은 `preferences.json`에 저장되어 다음 실행에도 유지 (설정 파일이 없거나 일부 항목이 빠져도 기본값으로 동작)
7. **다중 시편 오버레이 & 배치 통계 (Multi-Specimen Overlay & Batch Statistics)**
   - 완료된 시편을 세션 목록(**SP-001, SP-002, SP-003 …**)에 보관하고, 시편마다 다른 산업용 색상으로 구분
   - **보기 체크박스**로 곡선을 골라 겹쳐 그리기 — 응력-변형률 곡선과 하중-변위 곡선 모두 지원
   - 선택한 시편들로 **평균 · 표준편차(n-1) · 변동계수(CV%) · 최소 · 최대** 자동 계산 (최대 하중, Rm, Rp0.2, E, 연신율)
   - 배치 요약을 **엑셀(시편별 결과 + 통계 + 오버레이 원시 데이터)** 또는 **PDF(표 + 통계 + 다색 오버레이 곡선)** 로 출력
8. **시험 이력 자동 저장 & 무결성 해시 (Automatic Test History & Integrity)**
   - 시험이 끝나면 조건·시편·교정 스냅샷·원시 데이터·계산 결과를 `history/` 폴더에 **읽기 쉬운 JSON** 으로 자동 저장
   - **SHA-256 해시**로 저장 당시 그대로인지 검증하고, 직전 이력의 해시를 함께 보관해 **체인(연결)** 을 만듦
   - 상단 **시험 이력** 버튼에서 과거 시험 목록 · 무결성 검증(개별/전체 체인) · **오버레이로 불러오기** 가능
   - 앱에는 이력 삭제 기능을 두지 않음 (감사 추적 보존)
9. **다단계 시험 시퀀스 (Multi-Step Sequence)**
   - `시험 종류`에서 **다단계 시퀀스 시험** 선택 → **시퀀스 편집** 창에서 단계를 구성
   - 단계 동작: **목표 하중까지 가압 / 목표 변위까지 이동 / N초 유지 / 파단까지 가압 / 원점 복귀**
   - 단계별 속도(mm/min)와 목표값, 유지 시간을 지정하고 위·아래로 순서 변경, 프리셋(표준 인장 4단계 / 변위 제어 3단계) 제공
   - 시험 중 목표 도달 시 다음 단계로 자동 전환하며, **전환 기록(시작·종료 시각, 변위, 하중, 결과)** 을 결과·그래프(단계 구분선 S1~S4)·엑셀·PDF에 남김
10. **소프트 PID 하중·응력 속도 제어 (Soft-PID + Stiffness Feed-Forward)**
   - 제어 방식을 **변위 속도(mm/min) · 하중 속도(N/min) · 응력 속도(MPa/s) · 하중 유지(N)** 중에서 선택
   - 재질군별 **PID 3종 프리셋** (PID 1 연질 / PID 2 중질 / PID 3 고강성) — 게인(P·I·D)을 따로 저장·불러오기
   - 시험 초반에 측정한 **시편 강성 k = ΔF/Δx(N/mm)** 로 기준 변위 속도를 환산하는 **피드포워드** + 남은 오차만 보정하는 **Soft-PID**
   - 통신 지연 20~50 ms · 제어 주기 20~50 Hz 조건에서도 오버슈트를 억제하도록 **목표 근접 감속 · Anti-Windup · 속도 변화율 제한** 적용
   - 실시간 속도 변경(SPD)이 확인되지 않은 인디케이터에서는 **초기 강성 환산 고정 속도로 자동 폴백**

---

## 🏗 프로젝트 구조 (Architecture)

```text
salt-sw-v1/
├── core/
│   ├── __init__.py
│   ├── models.py              # 시편, 시험조건, 신율계 설정, 시퀀스, 계측데이터, 시험결과 데이터 모델
│   ├── simulator.py           # 가상 계측기 물리 시뮬레이터 (재질 프로필·시편 편차·시퀀스 실행)
│   ├── sequence.py            # 다단계 시퀀스 정의·단계 판정 컨트롤러·명령 문자열
│   ├── pid_controller.py      # 소프트 PID(하중·응력 속도·유지) · 재질별 게인 프로필 · 강성 피드포워드
│   ├── session.py             # 시편 세션(오버레이 색상/보기)과 배치 통계(평균·표준편차·CV)
│   ├── history.py             # 시험 이력 JSON 저장·불러오기·SHA-256 무결성/체인 검증
│   ├── calculator.py          # 물성치(인장강도, 항복강도, 탄성계수, 연신율 등) 자동 연산기
│   ├── preferences.py         # 환경 설정(신율계 구성) 영구 저장 관리자 (preferences.json)
│   ├── serial_driver.py       # 봉신 P2020/P2014 RS-232 드라이버 (신율계 채널 선택 파싱)
│   ├── calibration.py         # 하중/속도/변위 정밀 교정 관리자
│   ├── i18n.py                # 한/영 UI 문자열
│   └── hardware_interface.py  # 실제 장비 연동용 추상 하드웨어 인터페이스
├── exporters/
│   ├── __init__.py
│   ├── excel_exporter.py      # openpyxl 기반 스타일 서식 적용 엑셀 생성기
│   └── pdf_exporter.py        # reportlab 기반 벡터 S-S 곡선 포함 PDF 성적서 생성기
├── ui/
│   ├── __init__.py
│   ├── main_window.py         # PyQt6 기반 전문 UTM 대시보드 윈도우 + 환경 설정 탭
│   ├── dialogs.py             # 시퀀스 편집 창 · 시험 이력(무결성) 창
│   └── styles.py              # 산업용 고시인성 테마 QSS
├── tests/                     # 신율계·환경설정·오버레이·이력·시퀀스·소프트 PID 자동 검증 (unittest/pytest, 137개)
├── tools/capture_ui.py        # offscreen UI 스크린샷 생성 스크립트
├── tools/capture_pid_ui.py    # 소프트 PID 제어 화면 스크린샷 생성
├── tools/pid_benchmark.py     # 재질 3종 PID vs 고정 속도 추종 성능 측정·그래프
├── docs/screenshots/          # UI 검증 스크린샷
├── history/                   # 시험 이력 자동 저장 폴더 (실행 시 생성, JSON + SHA-256)
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
python cli_demo.py          # 신율계 미사용 / mV 타입 / 펄스 타입 3종 비교
python cli_demo.py mv       # mV 타입만
python cli_demo.py pulse    # 펄스 타입만
python cli_demo.py off      # 신율계 미사용만
python cli_demo.py seq      # 다단계 시퀀스 시험 (가압-유지-파단-복귀) + 단계 기록 출력
python cli_demo.py batch    # 3시편 배치 + 배치 통계 + 이력/무결성 + 배치 엑셀·PDF
```
실행 시 가상 인장 시험이 진행되고, `output/` 폴더에 엑셀(`Salt_UTM_Demo_Report_mv.xlsx` 등)과 PDF 성적서가 생성됩니다.

### 4. 자동 검증 테스트
```bash
python -m unittest discover -s tests -v
```
신율계 신호 환산(mV/펄스), 환경 설정 저장·복원, RS-232 패킷 파싱, 3가지 모드의 전 과정 시험·계산·성적서 출력,
환경 설정 탭 UI, **배치 통계·오버레이·시험 이력(무결성/변조 감지)·다단계 시퀀스** 동작을 검증합니다.

```bash
python -m unittest tests.test_overlay_history_sequence -v   # 오버레이 · 이력 · 시퀀스 (핵심 로직)
python -m unittest tests.test_ui_overlay -v                 # 화면 연동 (세션 · 통계 · 이력 · 시퀀스)
```

---

## ⚙️ 신율계(Extensometer) 설정 방법

1. 상단 **환경 설정** 탭을 엽니다.
2. **신율계 사용**에서 `사용함 (신율계 적용)`을 선택합니다.
3. **신호 방식**을 고릅니다.
   - `mV 타입 (아날로그 mV/V)`: 정격 출력(mV/V), 정격 변위(mm), 여자 전압(V), 교정 계수, 영점 오프셋(mV)
   - `펄스 타입 (엔코더 Pulse)`: 분해능(mm/pulse), 방향 반전
4. **표점거리 GL(mm)** 을 입력합니다 (연신율·탄성계수 계산 기준 길이).
5. **설정 저장 및 적용**을 누르면 `preferences.json`에 저장되고 다음 시험부터 적용됩니다.
   - 시험 중 신율계 영점이 필요하면 **신율계 영점 맞춤**을 누릅니다.
6. 시험 화면에는 **신율계 변위** 타일이 추가되고, 결과표 아래에 **변형률 측정 소스**가 표시됩니다.

> 신율계 채널이 없는 패킷만 들어오면 자동으로 크로스헤드 변위 기준으로 계산하고, 결과에 그 사실을 기록합니다.

### RS-232 신율계 채널 패킷 예 (선택 항목)
```text
ST,GS,+0012.35kg,+0001.20mm,+3.421mV     # mV 타입
ST,GS,+0012.35kg,+0001.20mm,#12450       # 펄스 타입 (펄스 카운트)
ST,GS,+0012.35kg,+0001.20mm,+3.421       # 세 번째 필드를 선택된 타입으로 해석
ST,GS,+0012.35kg,+0001.20mm              # 신율계 없음 (크로스헤드 변위 기준)
```

---

## 🧪 배치 시험 · 시험 이력 · 다단계 시퀀스 사용법

### 배치(다중 시편) 시험
1. 시편을 준비하고 `시험 시작` → 완료되면 시편이 **세션 목록(SP-001 …)** 에 자동으로 쌓입니다.
2. `시험 후 시편 번호 자동 증가`를 켜 두면 시편 번호가 `SALT-SP-001 → SALT-SP-002` 로 올라갑니다.
3. 세션 목록의 **보기** 체크박스로 그래프에 겹쳐 그릴 시편을 고릅니다 (색상이 곡선 색입니다).
4. **배치 통계** 표에서 선택 시편의 평균·표준편차(n-1)·CV%·최소·최대를 확인합니다.
5. `배치 요약 엑셀 / PDF` 로 시편별 결과·통계·오버레이 곡선을 한 문서로 출력합니다.

### 시험 이력과 무결성
- 시험이 끝날 때마다 `history/` 에 JSON 한 파일이 저장됩니다 (조건, 시편, 교정 스냅샷, 신율계 설정, 원시 데이터, 계산 결과).
- 파일에는 **SHA-256 해시**와 **직전 이력의 해시(prev_digest)** 가 함께 기록됩니다.
- 상단 **시험 이력** 버튼 → 목록에서 `무결성 검증`(선택 건) / `전체 체인 검증`(모든 건의 연결) 을 실행합니다.
- 값을 하나라도 고치면 해시가 달라져 `불일치`로 표시되고, 과거 기록을 고치면 그 뒤 기록의 연결도 함께 끊어집니다.
- `오버레이에 추가` 를 누르면 과거 시험을 지금 시험과 같은 그래프에 겹쳐 비교할 수 있습니다.

### 다단계 시퀀스
1. `시험 종류` 에서 **다단계 시퀀스 시험** 을 선택합니다.
2. **시퀀스 편집** 에서 단계를 추가하고 동작·목표값·속도·유지 시간을 입력합니다.

   | 동작 | 목표값 | 설명 |
   | --- | --- | --- |
   | 목표 하중 가압 | N | 설정 하중에 도달하면 다음 단계로 |
   | 목표 변위 이동 | mm | 설정 변위에 도달하면 다음 단계로 |
   | 유지 | 초 | 크로스헤드를 멈추고 지정 시간 유지 |
   | 파단까지 가압 | - | 하중이 피크 대비 설정 비율(%) 이상 떨어지면 파단으로 판정 |
   | 원점 복귀 | - | 변위가 0에 가까워질 때까지 복귀 |

3. 시험 중에는 단계가 자동으로 넘어가고, 완료 후 결과표·그래프(세로 점선 S1~S4)·엑셀·PDF에 단계 전환 기록이 남습니다.

> **정직한 한계**: 봉신 P2020/P2014 는 RS-232 텍스트 인터페이스로 1~5 kHz 폐루프 변형률 속도 제어를 지원하지 않습니다.
> 이 기능은 **소프트웨어 오케스트레이션** 방식이며, 단계 판정 주기는 통신 패킷 주기(약 10~20 Hz)입니다.
> 시퀀스 명령 문자열(`SPD/RUN/HLD/STP/ORG`)은 일반적인 ASCII 니모닉이며, 실제 인디케이터 명령 체계에 맞게
> `core/sequence.py` 의 `SEQUENCE_COMMAND_MAP` 을 조정해야 합니다. 전송한 명령은 패킷 모니터에 그대로 표시됩니다.

---

## 🎛 소프트 PID 하중·응력 속도 제어 (Soft-PID Control)

RS-232 인디케이터는 패킷 주기가 20~50 Hz 수준이라 1~5 kHz 폐루프처럼 빠른 보정은 불가능합니다.
그래서 이 기능은 **피드포워드로 기준 속도를 만들고, 남은 오차만 PID로 보정**하는 2단 구조입니다.

### 제어 방식
| 제어 방식 | 목표값 | 비고 |
|---|---|---|
| 변위 속도 | mm/min | 기존 방식 (PID 미사용) |
| 하중 속도 | N/min | 시편 강성으로 기준 속도 환산 + PID 보정 |
| 응력 속도 | MPa/s | 단면적으로 하중 속도 환산 후 동일 제어 |
| 하중 유지 | N | 목표 하중까지 접근 후 설정 시간 동안 유지 |

### 재질별 PID 프리셋 (기본값)
| 프리셋 | 대상 | 특징 |
|---|---|---|
| PID 1: 연질 | 플라스틱 · 고무 · 스프링 | 큰 변형, 빠른 응답, 강한 적분 |
| PID 2: 중질 | 필름 · 복합재 | 균형 게인, 중간 감쇠 |
| PID 3: 고강성 | 금속 | 낮은 속도 상한, 목표 근접 조기 감속(제동 거리) |

게인은 **추정 강성으로 환산한 변위 오차(mm)** 기준이므로 기종이나 시편 크기가 달라도 같은 프리셋을 쓸 수 있습니다.
화면의 P·I·D 값을 고친 뒤 **게인 저장**을 누르면 `pid_profiles.json` 에 저장되어 다음 실행에도 유지됩니다.

### 사용 순서
1. 시험 종류를 선택하고 시편 제원을 입력합니다.
2. **제어 방식 및 PID** 에서 제어 방식을 고르고 목표 속도를 입력합니다 (하중 유지는 유지 시험의 목표 하중·유지 시간 사용).
3. PID 모드를 고르고 필요하면 P·I·D를 조정한 뒤 **게인 저장**을 누릅니다.
4. **장비 연결 및 정밀 교정** 탭에서 인디케이터가 시험 중 `SPD` 명령을 받는 것이 확인된 경우에만
   **시험 중 실시간 속도 변경 지원** 을 켭니다. 끄면 초기 강성으로 환산한 속도를 한 번만 넣습니다.
5. 시험 중 화면 하단에 **강성 · 기준 속도 · 보정량 · 현재/목표 하중** 이 표시되고,
   시험 완료 창에 **추종 오차 · 오버슈트 · 유지 오차** 가 함께 나옵니다.

### 시뮬레이션 검증 결과 (통신 지연 40 ms · 제어 주기 25 Hz, 2,000 N 유지 기준)
| 재질 | 오버슈트 Soft-PID | 오버슈트 고정 속도 | 추종 오차 Soft-PID | 추종 오차 고정 속도 |
|---|---|---|---|---|
| 고무 (NBR) | 1.2 % | 3.6 % | 2.9 % | 4.2 % |
| 필름 (PET) | 3.4 % | 11.9 % | 3.1 % | 7.1 % |
| 금속 (SS400) | 3.2 % | 12.1 % | 3.7 % | 7.2 % |

유지 오차는 Soft-PID 기준 고무 0.2 %, 필름 0.8 %, 금속 0.5 % 였습니다.

20 Hz/50 ms 조건에서 오버슈트 1.0~3.3 %, 50 Hz/20 ms 조건에서 1.3~3.2 % 로 유지 시험을 완료했습니다
(`tests/test_pid_controller.py`, `tools/pid_benchmark.py`, 그래프 `docs/screenshots/17_pid_tracking_compare_ko.png`).

### 한계
- 판정 주기는 통신 패킷 주기(20~50 Hz)입니다. 그보다 빠른 과도 응답은 제어하지 않습니다.
- 프리셋 최소 속도보다 느린 속도가 필요한 조건에서는 크로스헤드가 멈추므로 정밀한 저속 제어가 되지 않습니다.
- 시편이 항복해 강성이 바뀌면 피드포워드가 어긋나므로 소성역에서는 추종 오차가 커집니다.
- 인디케이터의 실시간 `SPD` 지원 여부와 명령 형식은 장비 매뉴얼로 확인해야 합니다 (미확인 상태의 기본값은 미지원).
- 강성 실측에는 변위 채널이 필요합니다. 하중만 출력하는 단일 스트림에서는 재질·제원으로 계산한 초기 강성만 사용합니다.

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

## 🖼 UI 검증 스크린샷 (docs/screenshots)

| 파일 | 내용 |
| --- | --- |
| `01_dashboard_ext_off_ko.png` | 신율계 미사용 대시보드 |
| `02_preferences_ext_off_ko.png` | 환경 설정 탭 (사용 안 함) |
| `03_preferences_ext_mv_ko.png` | 환경 설정 탭 (mV 타입) |
| `04_dashboard_ext_mv_live_ko.png` | mV 신율계 시험 중 화면 |
| `05_dashboard_ext_mv_result_ko.png` | 시험 완료 결과표 (측정 소스 표기) |
| `06_preferences_ext_pulse_en.png` | 영문 UI · 펄스 타입 설정 |
| `07_preferences_ext_off_en.png` | 영문 UI · 사용 안 함 |
| `08_preferences_pulse_min_size_ko.png` | 최소 창 크기(1120x740) 레이아웃 확인 |
| `09_dashboard_ext_pulse_live_ko.png` | 펄스 신율계 시험 중 화면 |
| `11_overlay_batch_stats_ko.png` | 3시편 오버레이(응력-변형률) + 배치 통계 (한글) |
| `11b_overlay_load_disp_ko.png` | 3시편 오버레이(하중-변위) — 시편 두께별 곡선 분리 |
| `12_overlay_batch_stats_en.png` | 영문 UI 오버레이 + 배치 통계 |
| `13_sequence_dialog_ko.png` | 다단계 시퀀스 편집 창 |
| `14_sequence_result_ko.png` | 시퀀스 시험 완료 — 단계 구분선(S1~S4)과 단계 목록 |
| `14b_sequence_result_en.png` | 영문 UI 시퀀스 시험 완료 |
| `15_history_dialog_ko.png` | 시험 이력 창 — 무결성/체인 검증 결과 |
| `15b_history_dialog_en.png` | 영문 UI 시험 이력 창 |
| `16_overlay_min_size_ko.png` | 최소 창 크기(1120x740)에서 겹침 없이 스크롤되는 레이아웃 |

스크린샷 재생성: `QT_QPA_PLATFORM=offscreen python tools/capture_ui.py`

---

## 📄 라이선스 (License)
Copyright (c) 2026 Salt Tech / 강태관. All rights reserved.
