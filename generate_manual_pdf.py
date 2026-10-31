"""
Salt Sw ver.1 - User Manual PDF Generator (사용자 매뉴얼 PDF 생성기)
ReportLab을 활용하여 현대해상 블루/화이트 스타일의 고품질 사용자 가이드 PDF 문서 생성
"""

import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

# 한글 폰트 등록
FONT_NAME = "HYGothic-Medium"
pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))

# 현대해상 컬러 팔레트
C_PRIMARY = colors.HexColor("#0047BA")       # 현대해상 하이 블루
C_NAVY = colors.HexColor("#002C6C")          # 딥 네이비
C_ORANGE = colors.HexColor("#FF5722")        # 하이 포인트 오렌지
C_BG_LIGHT = colors.HexColor("#F3F5F8")      # 오프화이트 배경
C_CARD_BG = colors.HexColor("#FFFFFF")       # 카드 배경
C_CARD_BORDER = colors.HexColor("#E5E8EB")   # 경계선
C_BLUE_TINT = colors.HexColor("#EBF3FE")     # 블루 틴트 배경
C_TEXT_MAIN = colors.HexColor("#191F28")     # 본문 차콜
C_TEXT_SUB = colors.HexColor("#64748B")      # 부가 설명 슬레이트
C_WHITE = colors.HexColor("#FFFFFF")
C_GREEN = colors.HexColor("#059669")


class NumberedCanvas(canvas.Canvas):
    """페이지 번호와 헤더/푸터를 동적으로 기록하는 캔버스"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages):
        # 1페이지(표지)는 헤더/푸터 제외
        if self._pageNumber == 1:
            return

        self.saveState()
        self.setFont(FONT_NAME, 8.5)
        self.setFillColor(C_TEXT_SUB)

        # 상단 헤더
        self.drawString(40, 810, "Salt Sw ver.1 — 만능재료시험기(UTM) 사용자 운영 매뉴얼")
        self.setStrokeColor(C_CARD_BORDER)
        self.setLineWidth(0.75)
        self.line(40, 802, 555, 802)

        # 하단 푸터
        self.line(40, 40, 555, 40)
        page_str = f"- {self._pageNumber} / {total_pages} -"
        self.drawCentredString(297, 26, page_str)
        self.drawRightString(555, 26, "Salt Tech & Bongshin Loadcell")
        self.restoreState()


def create_manual(output_path: str):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=44,
        bottomMargin=44
    )

    # 스타일 정의
    s_title = ParagraphStyle(
        'CoverTitle',
        fontName=FONT_NAME,
        fontSize=28,
        leading=36,
        textColor=C_NAVY,
        spaceAfter=10
    )
    s_subtitle = ParagraphStyle(
        'CoverSub',
        fontName=FONT_NAME,
        fontSize=13,
        leading=18,
        textColor=C_PRIMARY,
        spaceAfter=25
    )
    s_h1 = ParagraphStyle(
        'H1',
        fontName=FONT_NAME,
        fontSize=15,
        leading=20,
        textColor=C_NAVY,
        spaceBefore=0,
        spaceAfter=8,
        keepWithNext=True
    )
    s_h2 = ParagraphStyle(
        'H2',
        fontName=FONT_NAME,
        fontSize=11.5,
        leading=16,
        textColor=C_PRIMARY,
        spaceBefore=8,
        spaceAfter=4,
        keepWithNext=True
    )
    s_body = ParagraphStyle(
        'Body',
        fontName=FONT_NAME,
        fontSize=9,
        leading=14.5,
        textColor=C_TEXT_MAIN,
        spaceAfter=5
    )
    s_body_sub = ParagraphStyle(
        'BodySub',
        fontName=FONT_NAME,
        fontSize=8.5,
        leading=13,
        textColor=C_TEXT_SUB,
        spaceAfter=3
    )
    s_code = ParagraphStyle(
        'Code',
        fontName=FONT_NAME,
        fontSize=8.5,
        leading=12.5,
        textColor=C_NAVY,
        backColor=C_BG_LIGHT,
        borderPadding=6,
        spaceAfter=6
    )
    s_callout = ParagraphStyle(
        'Callout',
        fontName=FONT_NAME,
        fontSize=8.5,
        leading=13.5,
        textColor=C_NAVY,
        spaceAfter=4
    )

    story = []

    # ==========================================
    # PAGE 1: 표지 (COVER)
    # ==========================================
    story.append(Spacer(1, 40))
    
    badge_table = Table([[Paragraph("<b>UNIVERSAL TESTING MACHINE SOFTWARE MANUAL</b>", ParagraphStyle('B', fontName=FONT_NAME, fontSize=9, textColor=C_PRIMARY))]], colWidths=[310])
    badge_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), C_BLUE_TINT),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(badge_table)
    story.append(Spacer(1, 15))

    story.append(Paragraph("Salt Sw ver.1<br/>사용자 운영 매뉴얼", s_title))
    story.append(Paragraph("봉신(Bongshin) 로드셀 & P2020 / P2014 인디케이터 연동 가이드", s_subtitle))
    story.append(HRFlowable(width="100%", thickness=3, color=C_PRIMARY, spaceBefore=0, spaceAfter=25))

    story.append(Paragraph("<b>현대해상 스타일의 직관적인 UI</b>를 기반으로 만능재료시험기(UTM)의 인장·압축 시험, 고속 RS-232 시리얼 통신(115,200 bps), 실시간 하중·변위 그래프 모니터링, 기계적 물성치 자동 계산, 그리고 엑셀 및 공식 PDF 시험 성적서 출력까지의 전 과정을 상세히 안내합니다.", s_body))
    story.append(Spacer(1, 150))

    meta_data = [
        [Paragraph("<b>문서 번호</b>", s_body_sub), Paragraph("SALT-DOC-2026-V1", s_body)],
        [Paragraph("<b>소프트웨어 버전</b>", s_body_sub), Paragraph("Salt Sw ver.1.0 (Build 2026.10)", s_body)],
        [Paragraph("<b>적용 대상 장비</b>", s_body_sub), Paragraph("만능재료시험기 (Bongshin Loadcell / P2020 · P2014 Indicator)", s_body)],
        [Paragraph("<b>통신 인터페이스</b>", s_body_sub), Paragraph("RS-232 Serial Port (115,200 bps / 8-N-1)", s_body)],
        [Paragraph("<b>발행일 / 작성사</b>", s_body_sub), Paragraph("2026년 10월 31일 | Salt Tech & Pickle", s_body)],
    ]
    meta_table = Table(meta_data, colWidths=[120, 395])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), C_CARD_BG),
        ('BOX', (0,0), (-1,-1), 1, C_CARD_BORDER),
        ('INNERGRID', (0,0), (-1,-1), 0.5, C_CARD_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 7),
        ('BOTTOMPADDING', (0,0), (-1,-1), 7),
        ('LEFTPADDING', (0,0), (-1,-1), 12),
        ('RIGHTPADDING', (0,0), (-1,-1), 12),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(meta_table)

    story.append(PageBreak())

    # ==========================================
    # PAGE 2: 목차 및 1장 시스템 개요
    # ==========================================
    story.append(Paragraph("목차 (Table of Contents)", s_h1))
    story.append(HRFlowable(width="100%", thickness=1, color=C_CARD_BORDER, spaceBefore=0, spaceAfter=8))

    toc_data = [
        [Paragraph("<b>제 1 장</b>", s_body), Paragraph("<b>시스템 개요 및 특징</b> .................................................................................", s_body), Paragraph("Page 2", s_body)],
        [Paragraph("<b>제 2 장</b>", s_body), Paragraph("<b>PC 설치 및 구동 방법 (Windows 1-Click Guide)</b> ........................................", s_body), Paragraph("Page 3", s_body)],
        [Paragraph("<b>제 3 장</b>", s_body), Paragraph("<b>장비 연동 및 통신 설정 (RS-232 / 115,200 bps)</b> ......................................", s_body), Paragraph("Page 4", s_body)],
        [Paragraph("<b>제 4 장</b>", s_body), Paragraph("<b>재료 시험 진행 및 실시간 모니터링</b> ...........................................................", s_body), Paragraph("Page 5", s_body)],
        [Paragraph("<b>제 5 장</b>", s_body), Paragraph("<b>데이터 관리 및 공식 성적서(엑셀·PDF) 출력</b> .............................................", s_body), Paragraph("Page 6", s_body)],
        [Paragraph("<b>제 6 장</b>", s_body), Paragraph("<b>문제 해결 및 FAQ (Troubleshooting)</b> ......................................................", s_body), Paragraph("Page 7", s_body)],
    ]
    t_toc = Table(toc_data, colWidths=[55, 405, 55])
    t_toc.setStyle(TableStyle([
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 2),
        ('RIGHTPADDING', (0,0), (-1,-1), 2),
    ]))
    story.append(t_toc)
    story.append(Spacer(1, 14))

    story.append(Paragraph("제 1 장. 시스템 개요 및 특징", s_h1))
    story.append(HRFlowable(width="100%", thickness=1.5, color=C_PRIMARY, spaceBefore=0, spaceAfter=8))

    story.append(Paragraph("1.1 소프트웨어 소개", s_h2))
    story.append(Paragraph("<b>Salt Sw ver.1</b>은 금속, 고분자, 플라스틱, 섬유 등 각종 산업 소재의 물성을 정밀 측정하는 만능재료시험기(Universal Testing Machine, UTM) 전용 통합 운영 소프트웨어입니다. 복잡한 산업용 계측 소프트웨어의 진입 장벽을 낮추기 위해 <b>현대해상 어플리케이션과 같은 현대적이고 직관적인 카드형 화이트 UI</b>를 채택하여, 초보자도 손쉽게 정밀 시험을 수행할 수 있도록 설계되었습니다.", s_body))

    story.append(Paragraph("1.2 핵심 특징 (Key Highlights)", s_h2))
    feat_data = [
        [Paragraph("<b>주요 항목</b>", ParagraphStyle('TH', fontName=FONT_NAME, fontSize=8.5, textColor=C_NAVY, alignment=1)),
         Paragraph("<b>주요 기능 및 성능</b>", ParagraphStyle('TH', fontName=FONT_NAME, fontSize=8.5, textColor=C_NAVY, alignment=1))],
        [Paragraph("<b>현대해상 스타일 UI</b>", s_body), Paragraph("화이트·하이 블루 톤의 고시인성 카드형 레이아웃, 대형 디지털 계측 타일 적용", s_body)],
        [Paragraph("<b>고속 RS-232 통신</b>", s_body), Paragraph("봉신 로드셀 및 P2020, P2014 인디케이터 전용 115,200 bps 고속 데이터 수신 스레드 탑재", s_body)],
        [Paragraph("<b>가상 시뮬레이터 내장</b>", s_body), Paragraph("실제 하드웨어가 없는 PC에서도 선형탄성-가공경화-네킹-파단 전 과정을 완벽 재현", s_body)],
        [Paragraph("<b>실시간 S-S 곡선 가시화</b>", s_body), Paragraph("PyQtGraph 하드웨어 가속 기반으로 하중-변위 및 응력-변형률 곡선 초고속 렌더링", s_body)],
        [Paragraph("<b>국제 표준 물성 자동 계산</b>", s_body), Paragraph("ASTM E8 / ISO 6892 준수: 최대하중, 인장강도, 0.2% Offset 항복강도, 연신율, 탄성계수 계산", s_body)],
        [Paragraph("<b>원클릭 성적서 발행</b>", s_body), Paragraph("수집 데이터 전수 엑셀(.xlsx) 저장 및 벡터 그래프가 수록된 공식 시험 성적서 PDF 즉시 출력", s_body)],
    ]
    t_feat = Table(feat_data, colWidths=[135, 380])
    t_feat.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_BLUE_TINT),
        ('BOX', (0,0), (-1,-1), 1, C_CARD_BORDER),
        ('INNERGRID', (0,0), (-1,-1), 0.5, C_CARD_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 4.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4.5),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t_feat)

    story.append(PageBreak())

    # ==========================================
    # PAGE 3: 2장 PC 설치 및 구동 방법
    # ==========================================
    story.append(Paragraph("제 2 장. PC 설치 및 구동 방법", s_h1))
    story.append(HRFlowable(width="100%", thickness=1.5, color=C_PRIMARY, spaceBefore=0, spaceAfter=8))

    story.append(Paragraph("2.1 시스템 요구 사양", s_h2))
    story.append(Paragraph("• <b>운영체제</b>: Windows 10 / 11 (64-bit 권장) 또는 macOS / Linux<br/>• <b>Python 버전</b>: Python 3.10 이상 (https://www.python.org)<br/>• <b>통신 포트</b>: RS-232 시리얼 9핀 포트 또는 USB-to-RS232 FTDI/CH340 시리얼 변환 젠더", s_body))

    story.append(Paragraph("2.2 파이썬 설치 시 필수 주의사항", s_h2))
    callout_data = [[
        Paragraph("<b>[필수 확인] PATH 환경변수 자동 등록 설정</b><br/>Python 공식 설치 프로그램을 실행할 때, 첫 화면 하단에 위치한 <b>[Add python.exe to PATH]</b> 체크박스를 반드시 체크한 후 'Install Now'를 클릭해야 합니다. 체크하지 않으면 명령 프롬프트나 실행 배치 파일에서 python 명령어를 인식하지 못합니다.", s_callout)
    ]]
    t_callout = Table(callout_data, colWidths=[515])
    t_callout.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#FFF7ED")),
        ('BOX', (0,0), (-1,-1), 1, C_ORANGE),
        ('TOPPADDING', (0,0), (-1,-1), 7),
        ('BOTTOMPADDING', (0,0), (-1,-1), 7),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(t_callout)
    story.append(Spacer(1, 8))

    story.append(Paragraph("2.3 윈도우 원클릭 실행 (run.bat)", s_h2))
    story.append(Paragraph("Salt Sw ver.1 프로젝트 폴더에는 윈도우 환경에서 명령어 입력 없이 프로그램을 한 번에 구동할 수 있는 <b>run.bat</b> 파일이 포함되어 있습니다.", s_body))
    story.append(Paragraph("1. 압축 파일(<b>Salt_Sw_ver.1.zip</b>)을 원하는 작업 폴더(예: C:\\UTM\\Salt-Sw-ver.1)에 압축 해제합니다.<br/>2. 폴더 내의 <b>run.bat</b> 파일을 마우스로 <b>더블클릭</b>합니다.<br/>3. 실행기가 자동으로 필수 라이브러리(PyQt6, pyserial, pyqtgraph 등) 설치 여부를 점검하고 대시보드 화면을 즉시 띄웁니다.", s_body))

    story.append(Paragraph("2.4 명령 프롬프트(CMD) 직접 실행 방법", s_h2))
    story.append(Paragraph("개발자 또는 수동 실행을 선호하시는 경우 명령 프롬프트에서 아래 명령어를 순서대로 입력합니다:", s_body))
    story.append(Paragraph("<code># 1. 필수 라이브러리 일괄 설치 (최초 1회)<br/>pip install -r requirements.txt<br/><br/># 2. 메인 GUI 대시보드 실행<br/>python main.py<br/><br/># (선택) 콘솔 시뮬레이터 데모 즉시 실행<br/>python cli_demo.py</code>", s_code))

    story.append(PageBreak())

    # ==========================================
    # PAGE 4: 3장 장비 연동 및 통신 설정
    # ==========================================
    story.append(Paragraph("제 3 장. 장비 연동 및 통신 설정 (RS-232)", s_h1))
    story.append(HRFlowable(width="100%", thickness=1.5, color=C_PRIMARY, spaceBefore=0, spaceAfter=8))

    story.append(Paragraph("3.1 하드웨어 구성 및 결선도", s_h2))
    story.append(Paragraph("Salt Sw ver.1은 국내 시험기 현장에서 가장 널리 사용되는 <b>봉신(Bongshin) 로드셀</b>과 <b>P2020 / P2014 디지털 인디케이터</b>의 통신 규격에 완벽히 맞추어져 있습니다.", s_body))

    hw_flow = [
        [Paragraph("<b>[봉신 로드셀]</b><br/>시편 하중 감지<br/>(로드셀 케이블)", ParagraphStyle('HWB', fontName=FONT_NAME, fontSize=8, textColor=C_NAVY, alignment=1)),
         Paragraph("──▶", ParagraphStyle('ARR', fontName=FONT_NAME, fontSize=10, textColor=C_PRIMARY, alignment=1)),
         Paragraph("<b>[P2020 / P2014 인디케이터]</b><br/>24bit 고속 A/D 변환<br/>하중/변위 디지털 지시계", ParagraphStyle('HWB', fontName=FONT_NAME, fontSize=8, textColor=C_NAVY, alignment=1)),
         Paragraph("──▶<br/>RS-232<br/>115,200", ParagraphStyle('ARR', fontName=FONT_NAME, fontSize=8.5, textColor=C_PRIMARY, alignment=1)),
         Paragraph("<b>[운영 PC (Salt Sw)]</b><br/>실시간 데이터 스트리밍 수신<br/>그래프 플로팅 & 성적서 발행", ParagraphStyle('HWB', fontName=FONT_NAME, fontSize=8, textColor=C_NAVY, alignment=1))]
    ]
    t_hw = Table(hw_flow, colWidths=[120, 35, 150, 60, 150])
    t_hw.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,0), C_BLUE_TINT),
        ('BACKGROUND', (2,0), (2,0), C_BLUE_TINT),
        ('BACKGROUND', (4,0), (4,0), C_BLUE_TINT),
        ('BOX', (0,0), (0,0), 1, C_CARD_BORDER),
        ('BOX', (2,0), (2,0), 1, C_CARD_BORDER),
        ('BOX', (4,0), (4,0), 1, C_CARD_BORDER),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_hw)
    story.append(Spacer(1, 10))

    story.append(Paragraph("3.2 통신 파라미터 표준 사양", s_h2))
    serial_spec = [
        [Paragraph("<b>파라미터</b>", ParagraphStyle('TH', fontName=FONT_NAME, fontSize=8.5, textColor=C_NAVY)), Paragraph("<b>설정 값</b>", ParagraphStyle('TH', fontName=FONT_NAME, fontSize=8.5, textColor=C_NAVY)), Paragraph("<b>비고</b>", ParagraphStyle('TH', fontName=FONT_NAME, fontSize=8.5, textColor=C_NAVY))],
        [Paragraph("통신 방식", s_body), Paragraph("RS-232C (비동기 시리얼 통신)", s_body), Paragraph("9핀 D-Sub 또는 USB 시리얼 컨버터", s_body)],
        [Paragraph("통신 속도 (Baudrate)", s_body), Paragraph("<b>115,200 bps</b>", s_body), Paragraph("P2020 / P2014 고속 연속 전송 모드", s_body)],
        [Paragraph("데이터 비트", s_body), Paragraph("8 Bits", s_body), Paragraph("표준 8비트 데이터", s_body)],
        [Paragraph("패리티 (Parity)", s_body), Paragraph("None (없음)", s_body), Paragraph("오류 검출 비트 미사용", s_body)],
        [Paragraph("스톱 비트 (Stop Bit)", s_body), Paragraph("1 Stop Bit", s_body), Paragraph("표준 프레임 종료", s_body)],
        [Paragraph("흐름 제어 (Flow Control)", s_body), Paragraph("None", s_body), Paragraph("하드웨어/소프트웨어 핸드셰이크 없음", s_body)],
    ]
    t_serial = Table(serial_spec, colWidths=[130, 160, 225])
    t_serial.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_BLUE_TINT),
        ('BOX', (0,0), (-1,-1), 1, C_CARD_BORDER),
        ('INNERGRID', (0,0), (-1,-1), 0.5, C_CARD_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t_serial)
    story.append(Spacer(1, 8))

    story.append(Paragraph("3.3 화면에서의 연결 및 영점 세팅 순서", s_h2))
    story.append(Paragraph("1. 프로그램 좌측 상단의 <b>[계측 장비 연동]</b> 패널로 이동합니다.<br/>2. <b>동작 모드</b>를 <b>'RS-232 실장비 (봉신 P2020/P2014)'</b>로 선택합니다.<br/>3. <b>[새로고침]</b> 버튼을 눌러 PC에 인식된 COM 포트 목록을 갱신하고 인디케이터 포트(예: COM1)를 지정합니다.<br/>4. 통신 속도가 <b>115200</b>으로 되어 있는지 확인 후 <b>[장비 연결 (Connect)]</b> 버튼을 클릭합니다.<br/>5. 하단의 <b>수신 패킷</b> 창에 인디케이터가 보내오는 실시간 문자열(예: +0012.35, +0001.20)이 정상 표시되는지 확인합니다.<br/>6. 시편을 지그에 장착하기 전 <b>[하중 영점 (Tare)]</b>과 <b>[변위 영점 (Tare)]</b> 버튼을 눌러 초기 영점을 보정합니다.", s_body))

    story.append(PageBreak())

    # ==========================================
    # PAGE 5: 4장 재료 시험 진행 절차
    # ==========================================
    story.append(Paragraph("제 4 장. 재료 시험 진행 및 실시간 모니터링", s_h1))
    story.append(HRFlowable(width="100%", thickness=1.5, color=C_PRIMARY, spaceBefore=0, spaceAfter=8))

    story.append(Paragraph("4.1 시험 준비 및 시편 제원 입력", s_h2))
    story.append(Paragraph("정확한 응력(MPa) 및 변형률(%) 계산을 위해 시편의 초기 치수를 정확히 입력해야 합니다.", s_body))

    step_data = [
        [Paragraph("<b>단계</b>", ParagraphStyle('TH', fontName=FONT_NAME, fontSize=8.5, textColor=C_NAVY)),
         Paragraph("<b>화면 설정 항목</b>", ParagraphStyle('TH', fontName=FONT_NAME, fontSize=8.5, textColor=C_NAVY)),
         Paragraph("<b>상세 설명 및 권장값</b>", ParagraphStyle('TH', fontName=FONT_NAME, fontSize=8.5, textColor=C_NAVY))],
        [Paragraph("1단계", s_body), Paragraph("시험 모드 (Test Mode)", s_body), Paragraph("<b>인장 시험 (Tensile)</b> 또는 <b>압축 시험 (Compression)</b> 라디오 선택", s_body)],
        [Paragraph("2단계", s_body), Paragraph("시편 ID 및 재질", s_body), Paragraph("관리 번호(예: SP-2026-001) 및 시편 재질(예: SS400, Al6061) 입력", s_body)],
        [Paragraph("3단계", s_body), Paragraph("시편 형태 및 치수", s_body), Paragraph("<b>판재</b>: 폭(Width) 및 두께(Thick) 입력 (단면적 A0 자동 계산)<br/><b>봉재</b>: 직경(Diameter) 입력 (원형 단면적 자동 계산)", s_body)],
        [Paragraph("4단계", s_body), Paragraph("표점거리 (L0)", s_body), Paragraph("신율계 표점거리 또는 그립 간 거리 (표준 50.0 mm 등) 설정", s_body)],
        [Paragraph("5단계", s_body), Paragraph("시험 속도 (Speed)", s_body), Paragraph("크로스헤드 인장/압축 속도 (규격 권장: 1.0 ~ 5.0 mm/min)", s_body)],
        [Paragraph("6단계", s_body), Paragraph("파단 감지율 (Drop %)", s_body), Paragraph("피크 하중 대비 하중이 50% 이하로 급락 시 시험 자동 종료", s_body)],
    ]
    t_step = Table(step_data, colWidths=[50, 140, 325])
    t_step.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_BLUE_TINT),
        ('BOX', (0,0), (-1,-1), 1, C_CARD_BORDER),
        ('INNERGRID', (0,0), (-1,-1), 0.5, C_CARD_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 4.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4.5),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t_step)
    story.append(Spacer(1, 8))

    story.append(Paragraph("4.2 시험 실행 및 실시간 모니터링", s_h2))
    story.append(Paragraph("• <b>[시험 시작 (START)]</b> 버튼을 누르면 시험이 개시되며, 상단 4개 디지털 계측 타일에 하중(N), 변위(mm), 응력(MPa), 변형률(%)이 실시간으로 갱신됩니다.<br/>• 중앙 그래프 창에 실시간 S-S 곡선(Stress-Strain Curve) 또는 하중-변위 곡선이 부드럽게 그려집니다.<br/>• 위험 상황 또는 긴급 정지가 필요할 경우 오렌지색 <b>[비상 정지 (STOP)]</b> 버튼을 누르면 즉시 시험이 멈춥니다.<br/>• 시편이 파단되면 시스템이 자동으로 감지하여 시험을 안전하게 종료하고 결과 분석 팝업을 띄웁니다.", s_body))

    story.append(Paragraph("4.3 크로스헤드 원점 복귀", s_h2))
    story.append(Paragraph("시험이 끝난 후 파단된 시편을 제거하고 <b>[원점 복귀 (Origin)]</b> 버튼을 누르면 크로스헤드가 시험 전 초기 위치로 복귀합니다.", s_body))

    story.append(PageBreak())

    # ==========================================
    # PAGE 6: 5장 데이터 관리 및 공식 성적서 발행
    # ==========================================
    story.append(Paragraph("제 5 장. 데이터 관리 및 공식 성적서(엑셀·PDF) 출력", s_h1))
    story.append(HRFlowable(width="100%", thickness=1.5, color=C_PRIMARY, spaceBefore=0, spaceAfter=8))

    story.append(Paragraph("5.1 기계적 물성치 자동 분석 결과표", s_h2))
    story.append(Paragraph("시험이 완료되면 MaterialCalculator 모듈이 ASTM E8 및 KS B 0802 규격에 따라 다음 물성치를 자동 산출합니다:", s_body))

    res_spec = [
        [Paragraph("<b>물성 지표</b>", ParagraphStyle('TH', fontName=FONT_NAME, fontSize=8.5, textColor=C_NAVY)),
         Paragraph("<b>기호 / 단위</b>", ParagraphStyle('TH', fontName=FONT_NAME, fontSize=8.5, textColor=C_NAVY)),
         Paragraph("<b>물리학적 의미 및 산출 공식</b>", ParagraphStyle('TH', fontName=FONT_NAME, fontSize=8.5, textColor=C_NAVY))],
        [Paragraph("최대 하중 (Peak Load)", s_body), Paragraph("Pmax (N)", s_body), Paragraph("시험 중 계측된 최대 인장/압축 하중", s_body)],
        [Paragraph("인장/압축 강도 (Strength)", s_body), Paragraph("Rm (MPa)", s_body), Paragraph("최대 하중을 초기 단면적으로 나눈 값 (Rm = Pmax / A0)", s_body)],
        [Paragraph("항복 강도 (Yield Strength)", s_body), Paragraph("Rp0.2 (MPa)", s_body), Paragraph("0.2% 영구 변형률 오프셋 선과 곡선의 교점 응력", s_body)],
        [Paragraph("탄성 계수 (Young's Modulus)", s_body), Paragraph("E (GPa)", s_body), Paragraph("초기 선형 탄성 구간의 기울기 (E = dσ / dε)", s_body)],
        [Paragraph("파단 연신율 (Elongation)", s_body), Paragraph("A (%)", s_body), Paragraph("파단 시점의 총 변형률 백분율 (A = (dL_break / L0) × 100)", s_body)],
        [Paragraph("흡수 에너지 (Toughness)", s_body), Paragraph("U (Joule)", s_body), Paragraph("하중-변위 곡선의 하부 면적 적분값", s_body)],
    ]
    t_res = Table(res_spec, colWidths=[135, 95, 285])
    t_res.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_BLUE_TINT),
        ('BOX', (0,0), (-1,-1), 1, C_CARD_BORDER),
        ('INNERGRID', (0,0), (-1,-1), 0.5, C_CARD_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 4.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4.5),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t_res)
    story.append(Spacer(1, 8))

    story.append(Paragraph("5.2 엑셀 데이터 저장 (Excel Export)", s_h2))
    story.append(Paragraph("• <b>[엑셀 데이터 저장 (.xlsx)]</b> 버튼을 클릭하면 시험 결과 파일이 생성됩니다.<br/>• <b>Sheet 1 (요약 보고서)</b>: 시험 정보, 시편 제원, 산출 물성치, 시험 조건 요약 테이블<br/>• <b>Sheet 2 (원시 계측 데이터)</b>: 시간(s), 변위(mm), 하중(N), 응력(MPa), 변형률(%)의 전체 전수 계측 데이터 기록", s_body))

    story.append(Paragraph("5.3 공식 시험 성적서 PDF 출력 (PDF Certificate)", s_h2))
    story.append(Paragraph("• <b>[시험 성적서 PDF 출력 (.pdf)]</b> 버튼을 클릭하면 고객사 및 공인 시험 제출용 공식 성적서가 즉시 생성됩니다.<br/>• ReportLab 벡터 그래픽 엔진을 통해 생성된 <b>고해상도 S-S 곡선 그래프</b>와 <b>ASTM E8 표준 형식의 성적 표</b>본이 단일 문서로 완벽히 조판됩니다.<br/>• 기본 저장 위치: <code>output/salt_sw_certificate_*.pdf</code>", s_body))

    story.append(PageBreak())

    # ==========================================
    # PAGE 7: 6장 문제 해결 및 FAQ
    # ==========================================
    story.append(Paragraph("제 6 장. 문제 해결 및 FAQ (Troubleshooting)", s_h1))
    story.append(HRFlowable(width="100%", thickness=1.5, color=C_PRIMARY, spaceBefore=0, spaceAfter=8))

    faq_data = [
        [Paragraph("<b>증상 및 질문</b>", ParagraphStyle('TH', fontName=FONT_NAME, fontSize=8.5, textColor=C_NAVY)),
         Paragraph("<b>원인 및 조치 방법</b>", ParagraphStyle('TH', fontName=FONT_NAME, fontSize=8.5, textColor=C_NAVY))],
        [
            Paragraph("<b>Q1. COM 포트 목록에 장비 포트가 나타나지 않습니다.</b>", s_body),
            Paragraph("1) USB 시리얼 젠더 케이블이 PC 본체에 올바르게 삽입되었는지 확인하세요.<br/>2) 윈도우 장치 관리자 → '포트 (COM & LPT)'에서 드라이버(FTDI, CH340 등)가 정상 인식되었는지 확인하세요.<br/>3) 프로그램 화면에서 <b>[새로고침]</b> 버튼을 누르세요.", s_body)
        ],
        [
            Paragraph("<b>Q2. 장비 연결을 눌렀는데 '연결 실패' 팝업이 뜹니다.</b>", s_body),
            Paragraph("1) 다른 프로그램(시리얼 모니터 프로그램 등)이 해당 COM 포트를 점유하고 있는지 확인 후 종료하세요.<br/>2) COM 포트 번호가 일치하는지 다시 확인하세요.", s_body)
        ],
        [
            Paragraph("<b>Q3. 수신 패킷에 글자가 깨지거나 이상한 문자가 찍힙니다.</b>", s_body),
            Paragraph("1) 통신 속도(Baudrate)가 <b>115,200 bps</b>로 일치하는지 확인하세요.<br/>2) P2020 / P2014 인디케이터 본체 설정 메뉴에서 통신 속도가 115,200으로 설정되어 있는지 확인하세요.", s_body)
        ],
        [
            Paragraph("<b>Q4. 하중이나 변위 값이 실제와 다르게 측정됩니다.</b>", s_body),
            Paragraph("1) 시험 시작 전 반드시 <b>[하중 영점]</b>과 <b>[변위 영점]</b>을 눌러 Tare를 잡아주세요.<br/>2) 인디케이터의 출력 단위(N / kN / kgf)가 소프트웨어 설정과 맞는지 확인하세요.", s_body)
        ],
        [
            Paragraph("<b>Q5. run.bat 실행 시 검은 창이 떴다가 바로 꺼집니다.</b>", s_body),
            Paragraph("1) 파이썬이 설치되어 있는지 확인하세요.<br/>2) 파이썬 재설치 시 <b>'Add python.exe to PATH'</b>를 반드시 체크하세요.<br/>3) cmd 창을 열어 <code>python --version</code>을 입력하여 정상 동작을 확인하세요.", s_body)
        ],
    ]
    t_faq = Table(faq_data, colWidths=[175, 340])
    t_faq.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_BLUE_TINT),
        ('BOX', (0,0), (-1,-1), 1, C_CARD_BORDER),
        ('INNERGRID', (0,0), (-1,-1), 0.5, C_CARD_BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t_faq)
    story.append(Spacer(1, 14))

    support_box = [
        [Paragraph("<b>기술 지원 및 문의처 (Technical Support)</b><br/>Salt Sw ver.1 소프트웨어 추가 기능 개발, 사용자 정의 시험 규격 추가, 전용 인디케이터 커스텀 프로토콜 문의는 언제든지 피클 대화창으로 편하게 말씀해 주세요.", s_callout)]
    ]
    t_sup = Table(support_box, colWidths=[515])
    t_sup.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), C_BLUE_TINT),
        ('BOX', (0,0), (-1,-1), 1, C_PRIMARY),
        ('TOPPADDING', (0,0), (-1,-1), 7),
        ('BOTTOMPADDING', (0,0), (-1,-1), 7),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(t_sup)

    # PDF 빌드 실행
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"매뉴얼 PDF 재생성 완료: {output_path}")


if __name__ == "__main__":
    out = "/workspace/Salt_Sw_ver.1_사용자_매뉴얼.pdf"
    create_manual(out)
