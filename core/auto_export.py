"""
Salt Sw ver.1 - 시험 완료 자동/지정 출력 (로우데이터 Excel + 성적서 PDF)

시험이 끝나면 지정한 기본 폴더 아래에 폴더 분류 규칙(지정 폴더 그대로 /
날짜별 / 시험종류별 / 시편명별 / 날짜+시험종류별)에 따라 폴더를 만들고
로우데이터(.xlsx)와 성적서(.pdf)를 저장한다.

파일 이름: {YYYYMMDD_HHMMSS}_{시험명}_{시편}.xlsx / .pdf
- 시험명은 파일 탐색기에서 바로 구분되도록 짧은 이름을 쓴다 (인장 / 압축 / 3점굽힘 / 유지 ...).
- 시편 번호에 들어갈 수 없는 문자(\\ / : * ? " < > |)는 지우고 공백은 밑줄로 바꾼다.
"""

import os
import re
from datetime import datetime
from typing import List, Optional, Tuple

from .models import BendingType, DataPoint, Specimen, TestConfig, TestMode, TestResult

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTO_REPORT_DIR = os.path.join(BASE_DIR, "output", "auto_reports")

FOLDER_RULES = ("flat", "date", "mode", "specimen", "date_mode")

MODE_FILE_LABELS = {
    "KO": {
        TestMode.TENSILE: "인장",
        TestMode.COMPRESSION: "압축",
        TestMode.BENDING: "굽힘",
        TestMode.HOLDING: "유지",
        TestMode.SEQUENCE: "시퀀스",
    },
    "EN": {
        TestMode.TENSILE: "Tensile",
        TestMode.COMPRESSION: "Compression",
        TestMode.BENDING: "Bending",
        TestMode.HOLDING: "Holding",
        TestMode.SEQUENCE: "Sequence",
    },
}


def mode_file_label(config: TestConfig, lang: str = "KO") -> str:
    """파일 이름·폴더 이름에 쓰는 짧은 시험명"""
    labels = MODE_FILE_LABELS.get(str(lang).upper(), MODE_FILE_LABELS["KO"])
    mode = getattr(config, "mode", TestMode.TENSILE)
    if mode is TestMode.BENDING:
        four_point = getattr(config, "bending_type", BendingType.THREE_POINT) is BendingType.FOUR_POINT
        if str(lang).upper() == "EN":
            return "Bending-4P" if four_point else "Bending-3P"
        return "4점굽힘" if four_point else "3점굽힘"
    return labels.get(mode, labels[TestMode.TENSILE])


def safe_token(text: str) -> str:
    """파일·폴더 이름에 쓸 수 없는 문자 제거"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", str(text or "")).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned or "SPECIMEN"


def normalize_folder_rule(rule: Optional[str]) -> str:
    value = str(rule or "date").strip().lower()
    return value if value in FOLDER_RULES else "date"


def resolve_report_dir(
    out_dir: Optional[str],
    config: TestConfig,
    specimen: Specimen,
    folder_rule: str = "flat",
    lang: str = "KO",
    when: Optional[datetime] = None,
) -> str:
    """기본 폴더와 분류 규칙에 따라 실제 저장될 폴더 경로를 계산한다"""
    root = str(out_dir or "").strip() or AUTO_REPORT_DIR
    rule = normalize_folder_rule(folder_rule)
    dt = when or datetime.now()

    if rule == "flat":
        return root
    if rule == "date":
        return os.path.join(root, dt.strftime("%Y-%m-%d"))
    if rule == "mode":
        return os.path.join(root, safe_token(mode_file_label(config, lang)))
    if rule == "specimen":
        return os.path.join(root, safe_token(getattr(specimen, "specimen_id", "")))
    if rule == "date_mode":
        return os.path.join(root, dt.strftime("%Y-%m-%d"), safe_token(mode_file_label(config, lang)))
    return root


def build_report_paths(
    specimen: Specimen,
    config: TestConfig,
    lang: str = "KO",
    out_dir: Optional[str] = None,
    when: Optional[datetime] = None,
    folder_rule: str = "flat",
) -> Tuple[str, str]:
    """자동 저장될 (엑셀 경로, PDF 경로)"""
    dt = when or datetime.now()
    folder = resolve_report_dir(out_dir, config, specimen, folder_rule=folder_rule, lang=lang, when=dt)
    stamp = dt.strftime("%Y%m%d_%H%M%S")
    base = f"{stamp}_{mode_file_label(config, lang)}_{safe_token(specimen.specimen_id)}"
    return os.path.join(folder, base + ".xlsx"), os.path.join(folder, base + ".pdf")


def export_auto_reports(
    specimen: Specimen,
    config: TestConfig,
    result: TestResult,
    data_points: List[DataPoint],
    lang: str = "KO",
    out_dir: Optional[str] = None,
    when: Optional[datetime] = None,
    folder_rule: str = "flat",
    export_excel: bool = True,
    export_pdf: bool = True,
) -> dict:
    """로우데이터(Excel)와 성적서(PDF)를 선택 저장하고 실제 경로를 돌려준다"""
    excel_path, pdf_path = build_report_paths(
        specimen, config, lang, out_dir=out_dir, when=when, folder_rule=folder_rule
    )
    os.makedirs(os.path.dirname(excel_path), exist_ok=True)

    # 순환 참조를 피하려고 함수 안에서 불러온다 (exporters 는 core.models 만 참조)
    from exporters.excel_exporter import ExcelExporter
    from exporters.pdf_exporter import PDFExporter

    paths: dict = {}
    if export_excel:
        ExcelExporter.export(excel_path, specimen, config, result, list(data_points))
        paths["excel"] = excel_path
    if export_pdf:
        PDFExporter.export(pdf_path, specimen, config, result, list(data_points))
        paths["pdf"] = pdf_path
    return paths


def display_path(path: str) -> str:
    """화면에 보여줄 경로 (프로젝트 안이면 상대 경로)"""
    try:
        relative = os.path.relpath(path, BASE_DIR)
        if not relative.startswith(".."):
            return relative.replace(os.sep, "/")
    except (ValueError, TypeError):
        pass
    return str(path)
