"""
Salt Sw ver.1 - PDF Test Certificate Exporter
ReportLab을 활용하여 고품질 벡터 S-S 곡선 그래프와 시험 성적표가 포함된 공식 시험 성적서 PDF 생성
(ASTM E8 / ISO 6892 표준 규격 스타일 리포트)
"""

from datetime import datetime
import math
import os
import re
from typing import List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.graphics.shapes import Drawing, Rect, Line, PolyLine, String

from core.models import DataPoint, Specimen, SpecimenType, TestConfig, TestMode, TestResult
from core.session import MetricStat, SessionRecord
from core.i18n import metric_label


def _sanitize_pdf_text(text: str) -> str:
    """PDF 기본 폰트(Helvetica)에서 깨지지 않도록 ASCII/Latin 기반 표준 텍스트로 정제"""
    # 괄호 안의 한국어 설명 제거 또는 대체 (예: '인장 시험 (Tensile)' -> 'Tensile Test')
    if "시퀀스" in text or "Sequence" in text:
        return "Multi-step Sequence"
    if "인장" in text or "Tensile" in text:
        return "Tensile Test"
    elif "압축" in text or "Compression" in text:
        return "Compression Test"
    elif "판재" in text or "Flat" in text:
        return "Flat Specimen"
    elif "봉재" in text or "Round" in text:
        return "Round Bar Specimen"
    elif "관형" in text or "Tube" in text:
        return "Tube Specimen"
    
    # 한국어 괄호 제거 (예: 'SS400 (일반구조용 압연강재)' -> 'SS400 (Structural Steel)')
    if "SS400" in text:
        return "SS400 Structural Steel"
    
    # 비-ASCII 문자 제거
    sanitized = re.sub(r'[^\x00-\x7F]+', '', text).strip()
    return sanitized if sanitized else "N/A"




def _nice_step(max_value: float, target: int = 5) -> float:
    """축 눈금 간격을 보기 좋은 값(1 / 2 / 2.5 / 5 x 10^n)으로 만든다"""
    if max_value <= 0:
        return 1.0
    raw = max_value / max(1, target)
    magnitude = 10 ** math.floor(math.log10(raw))
    for multiplier in (1.0, 2.0, 2.5, 5.0, 10.0):
        if raw <= multiplier * magnitude:
            return multiplier * magnitude
    return 10.0 * magnitude


def _nice_axis(max_value: float, target: int = 5):
    """(축 최대값, 눈금 목록) - 축 최대값은 눈금 간격의 배수로 올림한다"""
    if max_value <= 0:
        return 1.0, [0.0]
    step = _nice_step(max_value, target)
    top = math.ceil(max_value / step) * step
    count = max(1, int(round(top / step)))
    return top, [step * i for i in range(1, count + 1)]


class PDFExporter:
    """PDF 시험 성적서 내보내기 클래스"""

    @staticmethod
    def export(filepath: str, specimen: Specimen, config: TestConfig,
               result: TestResult, data_points: List[DataPoint]) -> str:
        """A4 규격 공식 시험 성적서 PDF 생성"""
        doc = SimpleDocTemplate(
            filepath,
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'DocTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=18,
            leading=22,
            textColor=colors.HexColor('#1E3A8A'),
            alignment=1  # Center
        )
        subtitle_style = ParagraphStyle(
            'DocSubTitle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=10,
            leading=14,
            textColor=colors.HexColor('#4B5563'),
            alignment=1
        )
        section_style = ParagraphStyle(
            'SectionHeader',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=11,
            leading=15,
            textColor=colors.HexColor('#1F2937')
        )
        body_style = ParagraphStyle(
            'TableBody',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=12
        )
        body_bold = ParagraphStyle(
            'TableBodyBold',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=12
        )

        elements = []

        # 1. 헤더 타이틀
        elements.append(Paragraph("SALT SW VER.1 — MATERIAL TEST REPORT", title_style))
        elements.append(Paragraph("Universal Testing Machine (UTM) Inspection Certificate", subtitle_style))
        elements.append(Spacer(1, 12))

        # 2. 시험 기본 정보 및 시편 제원 테이블
        elements.append(Paragraph("1. Test & Specimen Specifications", section_style))
        elements.append(Spacer(1, 4))

        test_date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        mode_str = _sanitize_pdf_text(config.mode.value)
        shape_str = _sanitize_pdf_text(specimen.specimen_type.value)
        mat_str = _sanitize_pdf_text(specimen.material)
        spec_id_str = _sanitize_pdf_text(specimen.specimen_id)

        if result.ext_enabled:
            ext_type_label = "mV type (analog mV/V)" if result.ext_type == "MV" else "Pulse type (encoder)"
        else:
            ext_type_label = "Not used (crosshead displacement)"

        info_table_data = [
            [
                Paragraph("<b>Test Date</b>", body_style), Paragraph(test_date_str, body_style),
                Paragraph("<b>Test Mode</b>", body_style), Paragraph(mode_str, body_style)
            ],
            [
                Paragraph("<b>Specimen ID</b>", body_style), Paragraph(spec_id_str, body_style),
                Paragraph("<b>Material</b>", body_style), Paragraph(mat_str, body_style)
            ],
            [
                Paragraph("<b>Specimen Shape</b>", body_style), Paragraph(shape_str, body_style),
                Paragraph("<b>Gauge Length (L0)</b>", body_style), Paragraph(f"{specimen.gauge_length_mm:.1f} mm", body_style)
            ],
            [
                Paragraph("<b>Cross-section (A0)</b>", body_style), Paragraph(f"{result.area_mm2:.3f} mm²", body_style),
                Paragraph("<b>Test Speed</b>", body_style), Paragraph(f"{config.test_speed_mm_min} mm/min", body_style)
            ],
            [
                Paragraph("<b>Extensometer</b>", body_style), Paragraph(ext_type_label, body_style),
                Paragraph("<b>Strain Source</b>", body_style), Paragraph(result.strain_source, body_style)
            ]
        ]
        if result.ext_enabled:
            info_table_data.append([
                Paragraph("<b>Extensometer GL</b>", body_style), Paragraph(f"{result.ext_gauge_length_mm:.1f} mm", body_style),
                Paragraph("<b>Ext. Max Travel</b>", body_style), Paragraph(f"{result.ext_max_disp_mm:.3f} mm", body_style)
            ])

        info_table = Table(info_table_data, colWidths=[38 * mm, 52 * mm, 38 * mm, 52 * mm])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F9FAFB')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 14))

        # 3. 주요 시험 결과 수치 테이블
        elements.append(Paragraph("2. Mechanical Properties Results", section_style))
        elements.append(Spacer(1, 4))

        results_data = [
            [
                Paragraph("<b>Mechanical Property</b>", body_bold),
                Paragraph("<b>Symbol</b>", body_bold),
                Paragraph("<b>Measured Value</b>", body_bold),
                Paragraph("<b>Unit</b>", body_bold),
                Paragraph("<b>Evaluation / Notes</b>", body_bold)
            ],
            [
                Paragraph("Peak Load (Max Force)", body_style), Paragraph("Pmax", body_style),
                Paragraph(f"{result.peak_load_n:,.1f}", body_bold), Paragraph("N", body_style),
                Paragraph("Maximum Load Detected", body_style)
            ],
            [
                Paragraph("Tensile / Compressive Strength", body_style), Paragraph("Rm", body_style),
                Paragraph(f"{result.peak_stress_mpa:.2f}", body_bold), Paragraph("MPa", body_style),
                Paragraph("Ultimate Stress", body_style)
            ],
            [
                Paragraph("0.2% Offset Yield Strength", body_style), Paragraph("Rp0.2", body_style),
                Paragraph(f"{result.yield_stress_mpa:.2f}", body_bold), Paragraph("MPa", body_style),
                Paragraph("Elastic-Plastic Limit", body_style)
            ],
            [
                Paragraph("Elastic Modulus (Young's)", body_style), Paragraph("E", body_style),
                Paragraph(f"{result.elastic_modulus_gpa:.2f}", body_bold), Paragraph("GPa", body_style),
                Paragraph("Linear Elastic Slope", body_style)
            ],
            [
                Paragraph("Elongation at Break", body_style), Paragraph("A", body_style),
                Paragraph(f"{result.elongation_pct:.2f}", body_bold), Paragraph("%", body_style),
                Paragraph("Ductility at Failure", body_style)
            ],
            [
                Paragraph("Displacement at Break", body_style), Paragraph("dL", body_style),
                Paragraph(f"{result.break_displacement_mm:.3f}", body_bold), Paragraph("mm", body_style),
                Paragraph("Crosshead Travel", body_style)
            ],
            [
                Paragraph("Absorbed Energy (Toughness)", body_style), Paragraph("U", body_style),
                Paragraph(f"{result.energy_joule:.2f}", body_bold), Paragraph("J", body_style),
                Paragraph("Integrated Area Under Curve", body_style)
            ]
        ]

        if result.ext_enabled:
            results_data.insert(7, [
                Paragraph("Extensometer Travel at Break", body_style), Paragraph("dL_ext", body_style),
                Paragraph(f"{result.ext_break_disp_mm:.3f}", body_bold), Paragraph("mm", body_style),
                Paragraph("Extensometer Measurement", body_style)
            ])

        res_table = Table(results_data, colWidths=[55 * mm, 20 * mm, 32 * mm, 18 * mm, 55 * mm])
        res_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563EB')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 1), (3, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D1D5DB')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(res_table)
        elements.append(Spacer(1, 14))

        # 4. 실시간 S-S Curve 그래프 (ReportLab Vector Drawing)
        elements.append(Paragraph("3. Stress - Strain Curve (S-S Curve)", section_style))
        elements.append(Spacer(1, 4))

        graph_points = PDFExporter._curve_points_without_return(data_points, result)
        graph_drawing = PDFExporter._create_vector_curve_drawing(graph_points, result)
        elements.append(graph_drawing)
        elements.append(Spacer(1, 12))

        # 4-1. 다단계 시퀀스 단계 기록 (시퀀스 시험인 경우)
        steps = result.sequence_steps or []
        if steps:
            elements.append(Paragraph("4. Sequence Steps", section_style))
            elements.append(Spacer(1, 4))
            step_rows = [[
                Paragraph("<b>Step</b>", body_bold), Paragraph("<b>Action</b>", body_bold),
                Paragraph("<b>Target</b>", body_bold), Paragraph("<b>Speed (mm/min)</b>", body_bold),
                Paragraph("<b>Start (s)</b>", body_bold), Paragraph("<b>End (s)</b>", body_bold),
                Paragraph("<b>End Load (N)</b>", body_bold),
            ]]
            for ev in steps:
                step_rows.append([
                    Paragraph(str(ev.get("index", 0) + 1), body_style),
                    Paragraph(_sanitize_pdf_text(str(ev.get("action", ""))), body_style),
                    Paragraph(
                        f"{ev.get('target', 0):,.2f}"
                        if str(ev.get("action", "")) in ("RAMP_LOAD", "RAMP_DISP") else "-",
                        body_style,
                    ),
                    Paragraph(f"{ev.get('speed_mm_min', 0):.1f}", body_style),
                    Paragraph(f"{ev.get('started_at', 0):.2f}", body_style),
                    Paragraph(f"{ev.get('ended_at', 0):.2f}", body_style),
                    Paragraph(f"{ev.get('end_load_n', 0):,.1f}", body_style),
                ])
            step_table = Table(step_rows, colWidths=[15 * mm, 42 * mm, 24 * mm, 28 * mm, 22 * mm, 22 * mm, 27 * mm])
            step_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563EB')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D1D5DB')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            elements.append(step_table)
            elements.append(Spacer(1, 12))

        # 5. 승인 및 서명란
        sign_table_data = [
            [
                Paragraph("<b>Tested By:</b> ________________", body_style),
                Paragraph("<b>Reviewed By:</b> ________________", body_style),
                Paragraph("<b>Approved By:</b> ________________", body_style)
            ]
        ]
        sign_table = Table(sign_table_data, colWidths=[60 * mm, 60 * mm, 60 * mm])
        sign_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ]))
        elements.append(sign_table)

        doc.build(elements)
        return filepath


    @staticmethod
    def _curve_points_without_return(data_points: List[DataPoint], result: TestResult) -> List[DataPoint]:
        """시퀀스 복귀(RETURN) 구간은 재료 응답이 아니므로 곡선에서 제외한다"""
        windows = []
        for event in (result.sequence_steps or []):
            if str(event.get("action", "")) == "RETURN":
                try:
                    windows.append((float(event.get("started_at", 0.0)),
                                    float(event.get("ended_at", 0.0))))
                except (TypeError, ValueError):
                    continue
        if not windows:
            return list(data_points)
        filtered = [p for p in data_points
                    if not any(start <= p.time_s <= end for start, end in windows)]
        return filtered or list(data_points)

    @staticmethod
    def _create_vector_curve_drawing(data_points: List[DataPoint], result: TestResult) -> Drawing:
        """ReportLab 벡터 기반 선명한 S-S 곡선 그래프 생성"""
        width_pt = 180 * mm
        height_pt = 72 * mm
        d = Drawing(width_pt, height_pt)

        margin_left = 38
        margin_bottom = 22
        plot_w = width_pt - margin_left - 15
        plot_h = height_pt - margin_bottom - 12

        d.add(Rect(margin_left, margin_bottom, plot_w, plot_h,
                   fillColor=colors.HexColor('#FAFAFA'),
                   strokeColor=colors.HexColor('#D1D5DB'),
                   strokeWidth=1))

        if not data_points:
            d.add(String(width_pt / 2, height_pt / 2, "No Data Points Available",
                         textAnchor='middle', fontSize=10, fillColor=colors.gray))
            return d

        raw_x = max(max(p.strain_pct for p in data_points), 1.0)
        raw_y = max(max(p.stress_mpa for p in data_points), 10.0)
        max_x, x_ticks = _nice_axis(raw_x)
        max_y, y_ticks = _nice_axis(raw_y * 1.05)

        # 격자선 그리기 (Grid Lines)
        for tick in x_ticks:
            gx = margin_left + (tick / max_x) * plot_w
            d.add(Line(gx, margin_bottom, gx, margin_bottom + plot_h,
                       strokeColor=colors.HexColor('#E5E7EB'), strokeWidth=0.5))
            d.add(String(gx, margin_bottom - 10, f"{tick:g}",
                         textAnchor='middle', fontSize=7, fillColor=colors.HexColor('#6B7280')))

        for tick in y_ticks:
            gy = margin_bottom + (tick / max_y) * plot_h
            d.add(Line(margin_left, gy, margin_left + plot_w, gy,
                       strokeColor=colors.HexColor('#E5E7EB'), strokeWidth=0.5))
            d.add(String(margin_left - 4, gy - 3, f"{tick:,.0f}",
                         textAnchor='end', fontSize=7, fillColor=colors.HexColor('#6B7280')))

        # 축 레이블 (Axis Labels)
        d.add(String(margin_left + plot_w / 2, margin_bottom - 18,
                     "Strain / Elongation (%)", textAnchor='middle',
                     fontName='Helvetica-Bold', fontSize=8, fillColor=colors.HexColor('#374151')))
        d.add(String(margin_left - 26, margin_bottom + plot_h / 2,
                     "Stress (MPa)", textAnchor='middle',
                     fontName='Helvetica-Bold', fontSize=8, fillColor=colors.HexColor('#374151')))

        # 데이터 포인트 벡터 라인 (PolyLine)
        step = max(1, len(data_points) // 300)
        sampled = data_points[::step]
        if data_points[-1] not in sampled:
            sampled.append(data_points[-1])

        line_coords = []
        for p in sampled:
            px = margin_left + (p.strain_pct / max_x) * plot_w
            py = margin_bottom + (p.stress_mpa / max_y) * plot_h
            line_coords.extend([px, py])

        if len(line_coords) >= 4:
            d.add(PolyLine(line_coords,
                           strokeColor=colors.HexColor('#2563EB'),  # Royal Blue
                           strokeWidth=1.8,
                           strokeLineJoin=1))

        # Peak Point 마커 및 텍스트 표시
        peak_p = max(data_points, key=lambda p: p.load_n)
        peak_x = margin_left + (peak_p.strain_pct / max_x) * plot_w
        peak_y = margin_bottom + (peak_p.stress_mpa / max_y) * plot_h
        d.add(Rect(peak_x - 3, peak_y - 3, 6, 6,
                   fillColor=colors.HexColor('#DC2626'),  # Red
                   strokeColor=colors.white, strokeWidth=1))
        d.add(String(peak_x + 5, min(margin_bottom + plot_h - 10, peak_y + 2),
                     f"UTS: {peak_p.stress_mpa:.1f} MPa ({peak_p.load_n:,.0f} N)",
                     fontSize=7, fontName='Helvetica-Bold', fillColor=colors.HexColor('#DC2626')))

        return d

    # ======================================================================
    # 배치(다중 시편) 요약 성적서
    # ======================================================================
    @staticmethod
    def export_batch(filepath: str, records: List[SessionRecord],
                     stats: List[MetricStat], lang: str = "KO") -> str:
        """
        여러 시편의 결과 표 + 배치 통계 + 오버레이 곡선을 A4 한 장으로 출력한다.
        (PDF 기본 폰트는 라틴 문자만 지원하므로 표기는 영문 표준 용어를 사용한다)
        """
        doc = SimpleDocTemplate(
            filepath, pagesize=A4,
            leftMargin=15 * mm, rightMargin=15 * mm,
            topMargin=14 * mm, bottomMargin=14 * mm,
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'BatchTitle', parent=styles['Normal'], fontName='Helvetica-Bold',
            fontSize=17, leading=21, textColor=colors.HexColor('#1E3A8A'), alignment=1,
        )
        subtitle_style = ParagraphStyle(
            'BatchSub', parent=styles['Normal'], fontName='Helvetica',
            fontSize=9.5, leading=13, textColor=colors.HexColor('#4B5563'), alignment=1,
        )
        section_style = ParagraphStyle(
            'BatchSection', parent=styles['Normal'], fontName='Helvetica-Bold',
            fontSize=10.5, leading=14, textColor=colors.HexColor('#1F2937'),
        )
        body = ParagraphStyle('BatchBody', parent=styles['Normal'], fontName='Helvetica',
                              fontSize=8.2, leading=10.5)
        body_bold = ParagraphStyle('BatchBodyBold', parent=styles['Normal'], fontName='Helvetica-Bold',
                                   fontSize=8.2, leading=10.5)

        elements = [
            Paragraph("SALT SW VER.1 — BATCH TEST SUMMARY", title_style),
            Paragraph("Multi-specimen overlay and batch statistics (Universal Testing Machine)", subtitle_style),
            Spacer(1, 10),
        ]

        visible = [r for r in records if r.visible]
        modes = sorted({r.result.test_mode.value for r in records})
        elements.append(Paragraph("1. Batch Information", section_style))
        elements.append(Spacer(1, 4))
        info_rows = [
            [Paragraph("<b>Generated</b>", body), Paragraph(datetime.now().strftime("%Y-%m-%d %H:%M"), body),
             Paragraph("<b>Specimens</b>", body), Paragraph(str(len(records)), body)],
            [Paragraph("<b>Selected (overlay)</b>", body), Paragraph(str(len(visible)), body),
             Paragraph("<b>Test Mode</b>", body),
             Paragraph(", ".join(_sanitize_pdf_text(m) for m in modes), body)],
            [Paragraph("<b>Material</b>", body),
             Paragraph(", ".join(sorted({_sanitize_pdf_text(r.specimen.material) for r in records if r.specimen})), body),
             Paragraph("<b>Statistics</b>", body),
             Paragraph("Mean / Std Dev (n-1) / CV% / Min / Max", body)],
        ]
        info_table = Table(info_rows, colWidths=[38 * mm, 52 * mm, 30 * mm, 60 * mm])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F9FAFB')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 12))

        # 2. 시편별 결과
        elements.append(Paragraph("2. Specimen Results", section_style))
        elements.append(Spacer(1, 4))
        headers = ["No.", "Session", "Specimen ID", "Peak Load (N)", "Rm (MPa)",
                   "Rp0.2 (MPa)", "E (GPa)", "A (%)"]
        rows = [[Paragraph(f"<b>{h}</b>", body_bold) for h in headers]]
        for rec in records:
            res = rec.result
            rows.append([
                Paragraph(str(rec.seq), body),
                Paragraph(rec.session_label, body_bold),
                Paragraph(_sanitize_pdf_text(rec.specimen_id), body),
                Paragraph(f"{res.peak_load_n:,.1f}", body),
                Paragraph(f"{res.peak_stress_mpa:.2f}", body),
                Paragraph(f"{res.yield_stress_mpa:.2f}", body),
                Paragraph(f"{res.elastic_modulus_gpa:.2f}", body),
                Paragraph(f"{res.elongation_pct:.2f}", body),
            ])
        spec_table = Table(rows, colWidths=[12 * mm, 22 * mm, 46 * mm, 26 * mm, 24 * mm, 24 * mm, 20 * mm, 16 * mm])
        spec_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563EB')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D1D5DB')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(spec_table)
        elements.append(Spacer(1, 12))

        # 3. 배치 통계
        elements.append(Paragraph("3. Batch Statistics (selected specimens)", section_style))
        elements.append(Spacer(1, 4))
        stat_headers = ["Property", "n", "Mean", "Std Dev", "CV (%)", "Min", "Max"]
        stat_rows = [[Paragraph(f"<b>{h}</b>", body_bold) for h in stat_headers]]
        for stat in stats:
            stat_rows.append([
                Paragraph(metric_label(stat.key, "EN"), body),
                Paragraph(str(stat.n), body),
                Paragraph(stat.formatted("mean"), body),
                Paragraph(stat.formatted("std"), body),
                Paragraph(stat.formatted("cv_pct"), body),
                Paragraph(stat.formatted("min"), body),
                Paragraph(stat.formatted("max"), body),
            ])
        stat_table = Table(stat_rows, colWidths=[58 * mm, 12 * mm, 26 * mm, 24 * mm, 20 * mm, 20 * mm, 20 * mm])
        stat_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D1D5DB')),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#EFF6FF')),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(stat_table)
        elements.append(Spacer(1, 12))

        # 4. 오버레이 곡선
        elements.append(Paragraph("4. Overlay Stress - Strain Curves", section_style))
        elements.append(Spacer(1, 4))
        elements.append(PDFExporter._create_overlay_drawing(visible or records))
        elements.append(Spacer(1, 8))
        elements.append(Paragraph(
            "Curves are drawn from the stored measurement data. Statistics use the selected specimens only.",
            ParagraphStyle('BatchNote', parent=styles['Normal'], fontName='Helvetica-Oblique',
                           fontSize=7.5, textColor=colors.HexColor('#6B7280')),
        ))
        doc.build(elements)
        return filepath

    @staticmethod
    def _create_overlay_drawing(records: List[SessionRecord]) -> Drawing:
        """여러 시편의 응력-변형률 곡선을 색상별로 겹쳐 그리는 벡터 도형"""
        width_pt = 180 * mm
        height_pt = 86 * mm
        d = Drawing(width_pt, height_pt)

        legend_rows = 1 if len(records) <= 4 else 2
        legend_h = 9 * legend_rows + 4
        margin_left = 40
        margin_bottom = 24
        plot_w = width_pt - margin_left - 16
        plot_bottom = margin_bottom
        plot_h = height_pt - legend_h - margin_bottom - 8

        d.add(Rect(margin_left, plot_bottom, plot_w, plot_h,
                   fillColor=colors.HexColor('#FAFAFA'),
                   strokeColor=colors.HexColor('#D1D5DB'), strokeWidth=1))

        if not records:
            d.add(String(width_pt / 2, height_pt / 2, "No specimens",
                         textAnchor='middle', fontSize=10, fillColor=colors.gray))
            return d

        raw_x = max((max((p.strain_pct for p in r.points), default=0.0) for r in records), default=1.0) or 1.0
        raw_y = max((max((p.stress_mpa for p in r.points), default=0.0) for r in records), default=10.0)
        max_x, x_ticks = _nice_axis(raw_x)
        max_y, y_ticks = _nice_axis(raw_y * 1.05)

        # 격자 및 축 값
        for tick in x_ticks:
            gx = margin_left + (tick / max_x) * plot_w
            d.add(Line(gx, plot_bottom, gx, plot_bottom + plot_h,
                       strokeColor=colors.HexColor('#E5E7EB'), strokeWidth=0.5))
            d.add(String(gx, plot_bottom - 9, f"{tick:g}",
                         textAnchor='middle', fontSize=6.5, fillColor=colors.HexColor('#6B7280')))
        for tick in y_ticks:
            gy = plot_bottom + (tick / max_y) * plot_h
            d.add(Line(margin_left, gy, margin_left + plot_w, gy,
                       strokeColor=colors.HexColor('#E5E7EB'), strokeWidth=0.5))
            d.add(String(margin_left - 4, gy - 2.5, f"{tick:,.0f}",
                         textAnchor='end', fontSize=6.5, fillColor=colors.HexColor('#6B7280')))

        d.add(String(margin_left + plot_w / 2, plot_bottom - 18, "Strain (%)",
                     textAnchor='middle', fontName='Helvetica-Bold', fontSize=7.5,
                     fillColor=colors.HexColor('#374151')))
        d.add(String(margin_left - 30, plot_bottom + plot_h / 2, "Stress (MPa)",
                     textAnchor='middle', fontName='Helvetica-Bold', fontSize=7.5,
                     fillColor=colors.HexColor('#374151')))

        # 곡선
        for idx, rec in enumerate(records):
            points = rec.points
            if not points:
                continue
            step = max(1, len(points) // 260)
            sampled = points[::step]
            if sampled[-1] is not points[-1]:
                sampled.append(points[-1])
            coords: List[float] = []
            for p in sampled:
                px = margin_left + (max(0.0, p.strain_pct) / max_x) * plot_w
                py = plot_bottom + (max(0.0, p.stress_mpa) / max_y) * plot_h
                coords.extend([px, py])
            if len(coords) >= 4:
                d.add(PolyLine(coords, strokeColor=colors.HexColor(rec.color), strokeWidth=1.5))

            # 범례 (그래프 위쪽, 2줄까지)
            per_row = 4
            row = idx // per_row
            col = idx % per_row
            lx = margin_left + col * (plot_w / per_row)
            ly = plot_bottom + plot_h + 6 + (legend_rows - 1 - row) * 9
            d.add(Line(lx, ly, lx + 12, ly, strokeColor=colors.HexColor(rec.color), strokeWidth=2))
            d.add(String(lx + 15, ly - 2.5,
                         f"{rec.session_label}  {_sanitize_pdf_text(rec.specimen_id)[:16]}",
                         fontName='Helvetica', fontSize=6.5, fillColor=colors.HexColor('#374151')))
        return d
