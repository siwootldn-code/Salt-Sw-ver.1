"""
Salt Sw ver.1 - Excel Report Exporter
openpyxl을 활용하여 시험 요약 성적 및 전체 원시 계측 데이터를 스타일이 적용된 엑셀 파일로 출력
"""

from datetime import datetime
from typing import List
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from core.models import DataPoint, Specimen, TestConfig, TestResult


class ExcelExporter:
    """엑셀(.xlsx) 성적서 및 원시 데이터 내보내기 클래스"""

    @staticmethod
    def export(filepath: str, specimen: Specimen, config: TestConfig,
               result: TestResult, data_points: List[DataPoint]) -> str:
        """엑셀 통합 문서 생성 및 저장"""
        wb = openpyxl.Workbook()
        
        # 1. 스타일 정의
        header_font = Font(name="맑은 고딕", size=14, bold=True, color="FFFFFF")
        section_font = Font(name="맑은 고딕", size=11, bold=True, color="1F2937")
        col_header_font = Font(name="맑은 고딕", size=10, bold=True, color="FFFFFF")
        regular_font = Font(name="맑은 고딕", size=10)
        bold_font = Font(name="맑은 고딕", size=10, bold=True)
        
        primary_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")  # Navy
        header_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")   # Blue
        accent_fill = PatternFill(start_color="DBEAFE", end_color="DBEAFE", fill_type="solid")   # Light Blue
        gray_fill = PatternFill(start_color="F3F4F6", end_color="F3F4F6", fill_type="solid")
        
        thin_border = Border(
            left=Side(style='thin', color='D1D5DB'),
            right=Side(style='thin', color='D1D5DB'),
            top=Side(style='thin', color='D1D5DB'),
            bottom=Side(style='thin', color='D1D5DB')
        )
        
        center_align = Alignment(horizontal="center", vertical="center")
        right_align = Alignment(horizontal="right", vertical="center")
        left_align = Alignment(horizontal="left", vertical="center")

        # ==========================================
        # Sheet 1: 시험 결과 요약 (Test Summary)
        # ==========================================
        ws_summary = wb.active
        ws_summary.title = "시험 성적 요약"
        ws_summary.views.sheetView[0].showGridLines = True

        # 메인 타이틀
        ws_summary.merge_cells("A1:F2")
        title_cell = ws_summary["A1"]
        title_cell.value = "SALT SW VER.1 — 만능재료시험기(UTM) 시험 성적서"
        title_cell.font = header_font
        title_cell.fill = primary_fill
        title_cell.alignment = center_align

        # 기본 정보 섹션
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        info_data = [
            ("시험 일시", current_time_str, "시험 모드", config.mode.value),
            ("시편 ID", specimen.specimen_id, "시험 속도", f"{config.test_speed_mm_min} mm/min"),
            ("시편 재질", specimen.material, "시편 형태", specimen.specimen_type.value),
            ("초기 표점거리 (L0)", f"{specimen.gauge_length_mm} mm", "초기 단면적 (A0)", f"{result.area_mm2:.3f} mm²"),
            ("총 시험 시간", f"{result.total_time_s:.2f} 초", "수집 샘플 수", f"{result.total_samples:,} 개")
        ]

        row_idx = 4
        ws_summary.cell(row=row_idx, column=1, value="[ 1. 시험 기본 정보 및 시편 제원 ]").font = section_font
        row_idx += 1

        for label1, val1, label2, val2 in info_data:
            ws_summary.cell(row=row_idx, column=1, value=label1).font = bold_font
            ws_summary.cell(row=row_idx, column=1).fill = gray_fill
            ws_summary.cell(row=row_idx, column=1).alignment = left_align
            ws_summary.cell(row=row_idx, column=1).border = thin_border

            ws_summary.cell(row=row_idx, column=2, value=val1).font = regular_font
            ws_summary.cell(row=row_idx, column=2).alignment = left_align
            ws_summary.cell(row=row_idx, column=2).border = thin_border

            ws_summary.cell(row=row_idx, column=4, value=label2).font = bold_font
            ws_summary.cell(row=row_idx, column=4).fill = gray_fill
            ws_summary.cell(row=row_idx, column=4).alignment = left_align
            ws_summary.cell(row=row_idx, column=4).border = thin_border

            ws_summary.cell(row=row_idx, column=5, value=val2).font = regular_font
            ws_summary.cell(row=row_idx, column=5).alignment = left_align
            ws_summary.cell(row=row_idx, column=5).border = thin_border
            row_idx += 1

        row_idx += 1
        # 물성 분석 결과 테이블
        ws_summary.cell(row=row_idx, column=1, value="[ 2. 주요 기계적 물성 분석 결과 ]").font = section_font
        row_idx += 1

        table_headers = ["항목 (Property)", "기호 (Symbol)", "측정값 (Value)", "단위 (Unit)", "비고 (Notes)"]
        for col_idx, h_text in enumerate(table_headers, start=1):
            cell = ws_summary.cell(row=row_idx, column=col_idx, value=h_text)
            cell.font = col_header_font
            cell.fill = header_fill
            cell.alignment = center_align
            cell.border = thin_border
        row_idx += 1

        prop_results = [
            ("최대 하중 (Peak Load)", "Pmax", result.peak_load_n, "N", "최대 감지 하중"),
            ("인장/압축 강도 (Peak Stress)", "Rm", result.peak_stress_mpa, "MPa", "최대 응력"),
            ("0.2% 오프셋 항복강도 (Yield Strength)", "Rp0.2", result.yield_stress_mpa, "MPa", "항복 기준"),
            ("항복 하중 (Yield Load)", "Py", result.yield_load_n, "N", "항복 시점 하중"),
            ("탄성 계수 (Young's Modulus)", "E", result.elastic_modulus_gpa, "GPa", "초기 선형 기울기"),
            ("파단 연신율 (Elongation at Break)", "A", result.elongation_pct, "%", "파단 시점 변형률"),
            ("파단 변위 (Break Displacement)", "dL", result.break_displacement_mm, "mm", "최종 이동 거리"),
            ("흡수 에너지 / 인성 (Toughness)", "U", result.energy_joule, "J", "하중-변위 곡선 면적")
        ]

        for prop_name, symbol, val, unit, note in prop_results:
            ws_summary.cell(row=row_idx, column=1, value=prop_name).font = regular_font
            ws_summary.cell(row=row_idx, column=1).border = thin_border
            
            ws_summary.cell(row=row_idx, column=2, value=symbol).font = regular_font
            ws_summary.cell(row=row_idx, column=2).alignment = center_align
            ws_summary.cell(row=row_idx, column=2).border = thin_border

            val_cell = ws_summary.cell(row=row_idx, column=3, value=val)
            val_cell.font = bold_font
            val_cell.alignment = right_align
            val_cell.border = thin_border
            if isinstance(val, float):
                val_cell.number_format = '#,##0.00'

            ws_summary.cell(row=row_idx, column=4, value=unit).font = regular_font
            ws_summary.cell(row=row_idx, column=4).alignment = center_align
            ws_summary.cell(row=row_idx, column=4).border = thin_border

            ws_summary.cell(row=row_idx, column=5, value=note).font = regular_font
            ws_summary.cell(row=row_idx, column=5).border = thin_border
            row_idx += 1

        # 열 너비 자동 조정
        for col in ws_summary.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws_summary.column_dimensions[col_letter].width = max(max_len + 4, 15)

        # ==========================================
        # Sheet 2: 전체 원시 데이터 (Raw Data)
        # ==========================================
        ws_raw = wb.create_sheet(title="계측 원시 데이터")
        ws_raw.views.sheetView[0].showGridLines = True

        raw_headers = ["시간 (Time, s)", "변위 (Disp, mm)", "하중 (Load, N)", "응력 (Stress, MPa)", "변형률 (Strain, %)"]
        for c_idx, r_text in enumerate(raw_headers, start=1):
            cell = ws_raw.cell(row=1, column=c_idx, value=r_text)
            cell.font = col_header_font
            cell.fill = header_fill
            cell.alignment = center_align
            cell.border = thin_border

        for r_idx, dp in enumerate(data_points, start=2):
            c1 = ws_raw.cell(row=r_idx, column=1, value=dp.time_s)
            c2 = ws_raw.cell(row=r_idx, column=2, value=dp.displacement_mm)
            c3 = ws_raw.cell(row=r_idx, column=3, value=dp.load_n)
            c4 = ws_raw.cell(row=r_idx, column=4, value=dp.stress_mpa)
            c5 = ws_raw.cell(row=r_idx, column=5, value=dp.strain_pct)

            c1.number_format = '0.000'
            c2.number_format = '0.0000'
            c3.number_format = '#,##0.00'
            c4.number_format = '#,##0.00'
            c5.number_format = '0.00'

            for c in (c1, c2, c3, c4, c5):
                c.font = regular_font
                c.alignment = right_align

        for col in ws_raw.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws_raw.column_dimensions[col_letter].width = max(max_len + 3, 16)

        wb.save(filepath)
        return filepath
