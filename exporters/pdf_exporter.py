"""
Salt Sw ver.1 - PDF Test Certificate Exporter
ReportLab을 활용하여 고품질 벡터 S-S 곡선 그래프와 시험 성적표가 포함된 공식 시험 성적서 PDF 생성
(ASTM E8 / ISO 6892 표준 규격 스타일 리포트)
"""

from datetime import datetime
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


def _sanitize_pdf_text(text: str) -> str:
    """PDF 기본 폰트(Helvetica)에서 깨지지 않도록 ASCII/Latin 기반 표준 텍스트로 정제"""
    # 괄호 안의 한국어 설명 제거 또는 대체 (예: '인장 시험 (Tensile)' -> 'Tensile Test')
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
            ]
        ]

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

        graph_drawing = PDFExporter._create_vector_curve_drawing(data_points, result)
        elements.append(graph_drawing)
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

        max_x = max(max(p.strain_pct for p in data_points), 1.0)
        max_y = max(max(p.stress_mpa for p in data_points), 10.0) * 1.1

        # 격자선 그리기 (Grid Lines)
        num_grids_x = 5
        num_grids_y = 5

        for i in range(1, num_grids_x):
            gx = margin_left + (i / num_grids_x) * plot_w
            d.add(Line(gx, margin_bottom, gx, margin_bottom + plot_h,
                       strokeColor=colors.HexColor('#E5E7EB'), strokeWidth=0.5))
            val_x = (i / num_grids_x) * max_x
            d.add(String(gx, margin_bottom - 10, f"{val_x:.1f}%",
                         textAnchor='middle', fontSize=7, fillColor=colors.HexColor('#6B7280')))

        for j in range(1, num_grids_y):
            gy = margin_bottom + (j / num_grids_y) * plot_h
            d.add(Line(margin_left, gy, margin_left + plot_w, gy,
                       strokeColor=colors.HexColor('#E5E7EB'), strokeWidth=0.5))
            val_y = (j / num_grids_y) * max_y
            d.add(String(margin_left - 4, gy - 3, f"{val_y:.0f}",
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
