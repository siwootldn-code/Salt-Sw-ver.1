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
from core.session import BATCH_METRICS, MetricStat, SessionRecord
from core.i18n import metric_label, tr


BATCH_LABELS = {
    "KO": {
        "title": "SALT SW VER.1 — 배치 시험 요약 성적서",
        "subtitle": "다중 시편 오버레이 및 배치 통계",
        "summary_sheet": "배치 요약",
        "stats_sheet": "배치 통계",
        "raw_sheet": "오버레이 원시 데이터",
        "sec_info": "[ 1. 배치 기본 정보 ]",
        "sec_specimens": "[ 2. 시편별 시험 결과 ]",
        "sec_stats": "[ 3. 배치 통계 (선택 시편 기준) ]",
        "created": "생성 일시",
        "count": "시편 수",
        "selected": "선택(오버레이) 시편",
        "mode": "시험 모드",
        "no": "No.",
        "session": "세션",
        "specimen": "시편 ID",
        "material": "재질",
        "pmax": "최대 하중 (N)",
        "rm": "인장강도 Rm (MPa)",
        "rp02": "항복강도 Rp0.2 (MPa)",
        "e": "탄성계수 E (GPa)",
        "a": "연신율 A (%)",
        "dl": "파단 변위 (mm)",
        "u": "흡수에너지 (J)",
        "status": "시험 상태",
        "completed": "완료 시각",
        "history_id": "이력 ID",
        "metric": "물성",
        "mean": "평균",
        "std": "표준편차",
        "cv": "변동계수 CV (%)",
        "min": "최소",
        "max": "최대",
        "n": "시편 수",
        "note": "표준편차는 표본표준편차(n-1), CV = 표준편차/평균 x 100 입니다.",
    },
    "EN": {
        "title": "SALT SW VER.1 — BATCH TEST SUMMARY",
        "subtitle": "Multi-specimen overlay and batch statistics",
        "summary_sheet": "Batch Summary",
        "stats_sheet": "Batch Statistics",
        "raw_sheet": "Overlay Raw Data",
        "sec_info": "[ 1. Batch Information ]",
        "sec_specimens": "[ 2. Specimen Results ]",
        "sec_stats": "[ 3. Batch Statistics (selected specimens) ]",
        "created": "Generated",
        "count": "Specimens",
        "selected": "Selected (overlay)",
        "mode": "Test Mode",
        "no": "No.",
        "session": "Session",
        "specimen": "Specimen ID",
        "material": "Material",
        "pmax": "Peak Load (N)",
        "rm": "Tensile Strength Rm (MPa)",
        "rp02": "Yield Strength Rp0.2 (MPa)",
        "e": "Young's Modulus E (GPa)",
        "a": "Elongation A (%)",
        "dl": "Break Disp (mm)",
        "u": "Absorbed Energy (J)",
        "status": "Status",
        "completed": "Completed",
        "history_id": "History ID",
        "metric": "Property",
        "mean": "Mean",
        "std": "Std Dev",
        "cv": "CV (%)",
        "min": "Min",
        "max": "Max",
        "n": "n",
        "note": "Standard deviation is the sample standard deviation (n-1); CV = std / mean x 100.",
    },
}


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
        if result.ext_enabled:
            ext_type_label = "mV 타입 (아날로그 mV/V)" if result.ext_type == "MV" else "펄스 타입 (엔코더 Pulse)"
            ext_gl_str = f"{result.ext_gauge_length_mm:.1f} mm"
        else:
            ext_type_label = "미사용 (크로스헤드 변위 기준)"
            ext_gl_str = "-"

        info_data = [
            ("시험 일시", current_time_str, "시험 모드", config.mode.value),
            ("시편 ID", specimen.specimen_id, "시험 속도", f"{config.test_speed_mm_min} mm/min"),
            ("시편 재질", specimen.material, "시편 형태", specimen.specimen_type.value),
            ("초기 표점거리 (L0)", f"{specimen.gauge_length_mm} mm", "초기 단면적 (A0)", f"{result.area_mm2:.3f} mm²"),
            ("총 시험 시간", f"{result.total_time_s:.2f} 초", "수집 샘플 수", f"{result.total_samples:,} 개"),
            ("신율계", ext_type_label, "신율계 표점거리 (GL)", ext_gl_str),
            ("변형률 측정 소스", result.strain_source, "신율계 최대 변위", f"{result.ext_max_disp_mm:.3f} mm" if result.ext_enabled else "-")
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
            ("파단 연신율 (Elongation at Break)", "A", result.elongation_pct, "%", "파단 시점 변형률 (" + ("신율계 기준" if result.ext_enabled else "크로스헤드 기준") + ")"),
            ("파단 변위 (Break Displacement)", "dL", result.break_displacement_mm, "mm", "최종 이동 거리 (크로스헤드)"),
            ("흡수 에너지 / 인성 (Toughness)", "U", result.energy_joule, "J", "하중-변위 곡선 면적")
        ]
        if result.ext_enabled:
            prop_results.append(
                ("신율계 파단 변위 (Extensometer at Break)", "dL_ext", result.ext_break_disp_mm, "mm", "신율계 측정값")
            )

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

        # 시퀀스 단계 기록 (다단계 시험인 경우)
        steps = result.sequence_steps or []
        if steps:
            row_idx += 1
            ws_summary.cell(row=row_idx, column=1,
                            value=f"[ 3. 시퀀스 단계 기록 · {result.sequence_name or 'Sequence'} ]").font = section_font
            row_idx += 1
            step_headers = ["단계", "동작", "목표", "속도 (mm/min)", "시작 (s)", "종료 (s)",
                            "종료 하중 (N)", "결과"]
            for c_idx, h_text in enumerate(step_headers, start=1):
                cell = ws_summary.cell(row=row_idx, column=c_idx, value=h_text)
                cell.font = col_header_font
                cell.fill = header_fill
                cell.alignment = center_align
                cell.border = thin_border
            row_idx += 1
            for ev in steps:
                uses_target = str(ev.get("action", "")) in ("RAMP_LOAD", "RAMP_DISP")
                values = [
                    ev.get("index", 0) + 1,
                    ev.get("action", ""),
                    ev.get("target", 0) if uses_target else "-",
                    ev.get("speed_mm_min", 0),
                    ev.get("started_at", 0),
                    ev.get("ended_at", 0),
                    ev.get("end_load_n", 0),
                    ev.get("outcome", ""),
                ]
                for c_idx, value in enumerate(values, start=1):
                    cell = ws_summary.cell(row=row_idx, column=c_idx, value=value)
                    cell.font = regular_font
                    cell.border = thin_border
                    cell.alignment = center_align if c_idx != 8 else left_align
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

        raw_headers = ["시간 (Time, s)", "크로스헤드 변위 (Disp, mm)", "하중 (Load, N)", "응력 (Stress, MPa)", "변형률 (Strain, %)"]
        if result.ext_enabled:
            raw_headers += ["신율계 변위 (Ext, mm)", "신율계 변형률 (Ext Strain, %)", "신율계 원시값"]
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

            cells = [c1, c2, c3, c4, c5]
            if result.ext_enabled:
                c6 = ws_raw.cell(row=r_idx, column=6, value=dp.ext_disp_mm)
                c7 = ws_raw.cell(row=r_idx, column=7, value=dp.ext_strain_pct)
                c8 = ws_raw.cell(row=r_idx, column=8, value=dp.ext_raw)
                c6.number_format = '0.0000'
                c7.number_format = '0.00'
                c8.number_format = '#,##0.0000'
                cells += [c6, c7, c8]

            for c in cells:
                c.font = regular_font
                c.alignment = right_align

        for col in ws_raw.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws_raw.column_dimensions[col_letter].width = max(max_len + 3, 16)

        wb.save(filepath)
        return filepath

    # ======================================================================
    # 배치(다중 시편) 요약 성적서
    # ======================================================================
    @staticmethod
    def export_batch(filepath: str, records: List[SessionRecord],
                     stats: List[MetricStat], lang: str = "KO") -> str:
        """
        여러 시편의 시험 결과와 배치 통계를 한 문서로 출력한다.
        - 시트 1: 시편별 결과 표 + 배치 통계 표 (선택 시편 기준)
        - 시트 2: 오버레이에 사용한 전체 원시 데이터 (세션별)
        """
        L = BATCH_LABELS.get(lang, BATCH_LABELS["KO"])

        title_font = Font(name="맑은 고딕", size=14, bold=True, color="FFFFFF")
        section_font = Font(name="맑은 고딕", size=11, bold=True, color="1F2937")
        col_header_font = Font(name="맑은 고딕", size=9.5, bold=True, color="FFFFFF")
        regular_font = Font(name="맑은 고딕", size=9.5)
        bold_font = Font(name="맑은 고딕", size=9.5, bold=True)
        note_font = Font(name="맑은 고딕", size=8.5, italic=True, color="64748B")

        primary_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        header_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
        stat_fill = PatternFill(start_color="EFF6FF", end_color="EFF6FF", fill_type="solid")
        gray_fill = PatternFill(start_color="F3F4F6", end_color="F3F4F6", fill_type="solid")
        thin = Side(style="thin", color="D1D5DB")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        center = Alignment(horizontal="center", vertical="center")
        right = Alignment(horizontal="right", vertical="center")
        left = Alignment(horizontal="left", vertical="center")

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = L["summary_sheet"]

        n_cols = 15
        ws.merge_cells(start_row=1, start_column=1, end_row=2, end_column=n_cols)
        cell = ws.cell(row=1, column=1, value=L["title"])
        cell.font = title_font
        cell.fill = primary_fill
        cell.alignment = center

        ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=n_cols)
        sub = ws.cell(row=3, column=1, value=L["subtitle"])
        sub.font = Font(name="맑은 고딕", size=9, color="FFFFFF")
        sub.fill = PatternFill(start_color="3B82F6", end_color="3B82F6", fill_type="solid")
        sub.alignment = center

        visible = [r for r in records if r.visible]
        modes = sorted({r.result.test_mode.value for r in records})
        row = 5
        ws.cell(row=row, column=1, value=L["sec_info"]).font = section_font
        row += 1
        info = [
            (L["created"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            (L["count"], f"{len(records)}"),
            (L["selected"], f"{len(visible)}"),
            (L["mode"], ", ".join(modes)),
        ]
        for label, value in info:
            c1 = ws.cell(row=row, column=1, value=label)
            c1.font = bold_font
            c1.fill = gray_fill
            c1.border = border
            c2 = ws.cell(row=row, column=2, value=value)
            c2.font = regular_font
            c2.border = border
            c2.alignment = left
            row += 1

        row += 1
        ws.cell(row=row, column=1, value=L["sec_specimens"]).font = section_font
        row += 1

        headers = [
            L["no"], L["session"], L["specimen"], L["material"], L["mode"],
            L["pmax"], L["rm"], L["rp02"], L["e"], L["a"], L["dl"], L["u"],
            L["status"], L["completed"], L["history_id"],
        ]
        for c_idx, h_text in enumerate(headers, start=1):
            cell = ws.cell(row=row, column=c_idx, value=h_text)
            cell.font = col_header_font
            cell.fill = header_fill
            cell.alignment = center
            cell.border = border
        header_row = row
        row += 1

        for rec in records:
            res = rec.result
            values = [
                rec.seq, rec.session_label, rec.specimen_id,
                rec.specimen.material if rec.specimen else "",
                res.test_mode.value if res.test_mode else "",
                res.peak_load_n, res.peak_stress_mpa, res.yield_stress_mpa,
                res.elastic_modulus_gpa, res.elongation_pct,
                res.break_displacement_mm, res.energy_joule,
                rec.completion_reason, rec.completed_at, rec.history_id,
            ]
            for c_idx, value in enumerate(values, start=1):
                cell = ws.cell(row=row, column=c_idx, value=value)
                cell.font = regular_font
                cell.border = border
                if c_idx in (6, 7, 8, 9, 10, 11, 12):
                    cell.alignment = right
                    cell.number_format = "#,##0.00"
                elif c_idx in (1, 2):
                    cell.alignment = center
                else:
                    cell.alignment = left
                if not rec.visible:
                    cell.font = Font(name="맑은 고딕", size=9.5, color="94A3B8")
            row += 1

        row += 1
        ws.cell(row=row, column=1, value=L["sec_stats"]).font = section_font
        row += 1
        stat_headers = [L["metric"], L["n"], L["mean"], L["std"], L["cv"], L["min"], L["max"]]
        for c_idx, h_text in enumerate(stat_headers, start=1):
            cell = ws.cell(row=row, column=c_idx, value=h_text)
            cell.font = col_header_font
            cell.fill = header_fill
            cell.alignment = center
            cell.border = border
        row += 1
        for stat in stats:
            values = [
                metric_label(stat.key, lang), stat.n,
                stat.mean if stat.has_data else "-",
                stat.std if stat.has_data else "-",
                stat.cv_pct if stat.has_data else "-",
                stat.minimum if stat.has_data else "-",
                stat.maximum if stat.has_data else "-",
            ]
            for c_idx, value in enumerate(values, start=1):
                cell = ws.cell(row=row, column=c_idx, value=value)
                cell.font = bold_font if c_idx == 1 else regular_font
                cell.fill = stat_fill
                cell.border = border
                if c_idx == 1:
                    cell.alignment = left
                else:
                    cell.alignment = right
                    if isinstance(value, float):
                        cell.number_format = "#,##0.00"
            row += 1

        row += 1
        ws.cell(row=row, column=1, value=L["note"]).font = note_font

        for c_idx in range(1, n_cols + 1):
            letter = get_column_letter(c_idx)
            longest = max(
                (len(str(ws.cell(row=r, column=c_idx).value or ""))
                 for r in range(1, row + 1)),
                default=8,
            )
            ws.column_dimensions[letter].width = max(9, min(30, longest + 3))
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1)

        # ---------------- 시트 2: 오버레이 원시 데이터 ----------------
        ws_raw = wb.create_sheet(title=L["raw_sheet"])
        raw_headers = [L["session"], L["specimen"], L["material"],
                       "Time (s)", "Disp (mm)", "Load (N)", "Stress (MPa)", "Strain (%)"]
        for c_idx, h_text in enumerate(raw_headers, start=1):
            cell = ws_raw.cell(row=1, column=c_idx, value=h_text)
            cell.font = col_header_font
            cell.fill = header_fill
            cell.alignment = center
            cell.border = border

        r = 2
        for rec in records:
            for p in rec.points:
                values = [rec.session_label, rec.specimen_id,
                          rec.specimen.material if rec.specimen else "",
                          p.time_s, p.displacement_mm, p.load_n, p.stress_mpa, p.strain_pct]
                for c_idx, value in enumerate(values, start=1):
                    cell = ws_raw.cell(row=r, column=c_idx, value=value)
                    cell.font = regular_font
                    if c_idx >= 4:
                        cell.alignment = right
                        cell.number_format = "0.0000" if c_idx in (4, 5) else "#,##0.00"
                r += 1

        for c_idx in range(1, len(raw_headers) + 1):
            letter = get_column_letter(c_idx)
            ws_raw.column_dimensions[letter].width = 14 if c_idx <= 3 else 13
        ws_raw.freeze_panes = "A2"

        wb.save(filepath)
        return filepath
