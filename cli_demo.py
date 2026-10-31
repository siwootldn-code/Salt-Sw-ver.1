"""
Salt Sw ver.1 - CLI Headless Demonstration & Validation Script
GUI 없이 터미널에서 전체 가상 시험, 물성 연산, 엑셀/PDF 리포트 생성을 즉시 검증하는 스크립트
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.models import Specimen, SpecimenType, TestConfig, TestMode, DataPoint
from core.simulator import VirtualUTMSimulator
from core.calculator import MaterialCalculator
from exporters.excel_exporter import ExcelExporter
from exporters.pdf_exporter import PDFExporter


def run_demo():
    print("=" * 65)
    print("      SALT SW VER.1 — 만능재료시험기(UTM) 시뮬레이션 데모")
    print("=" * 65)

    # 1. 시편 정의 (SS400 표준 인장 시편)
    specimen = Specimen(
        specimen_id="SALT-DEMO-SS400",
        material="SS400 (일반구조용 압연강재)",
        specimen_type=SpecimenType.FLAT,
        width_mm=12.5,
        thickness_mm=3.2,
        gauge_length_mm=50.0
    )
    print(f"[시편 정보]")
    print(f" - 시편 ID      : {specimen.specimen_id}")
    print(f" - 재질         : {specimen.material} ({specimen.specimen_type.value})")
    print(f" - 치수         : 폭 {specimen.width_mm} mm x 두께 {specimen.thickness_mm} mm")
    print(f" - 초기 단면적  : {specimen.cross_sectional_area_mm2:.3f} mm²")
    print(f" - 표점거리(L0) : {specimen.gauge_length_mm:.1f} mm\n")

    # 2. 시험 조건 정의 (속도 60 mm/min, 고속 시뮬레이션용)
    config = TestConfig(
        mode=TestMode.TENSILE,
        test_speed_mm_min=45.0,
        fracture_drop_ratio=0.5,
        max_displacement_mm=30.0,
        sampling_rate_hz=50
    )
    print(f"[시험 조건]")
    print(f" - 모드         : {config.mode.value}")
    print(f" - 시험 속도    : {config.test_speed_mm_min} mm/min")
    print(f" - 파단 감지    : 피크 하중 대비 {int(config.fracture_drop_ratio * 100)}% 드롭\n")

    # 3. 실시간 시험 진행
    print("[시험 진행 중...]")
    data_points = []
    completed_event = False
    completion_reason = ""

    simulator = VirtualUTMSimulator()

    def on_data(dp: DataPoint):
        data_points.append(dp)
        if len(data_points) % 15 == 0:
            print(f"  시간: {dp.time_s:5.2f}s | 변위: {dp.displacement_mm:6.3f}mm | 하중: {dp.load_n:8.1f}N | 응력: {dp.stress_mpa:6.1f}MPa | 변형률: {dp.strain_pct:5.2f}%")

    def on_done(reason: str):
        nonlocal completed_event, completion_reason
        completion_reason = reason
        completed_event = True

    simulator.on_data_received = on_data
    simulator.on_test_completed = on_done

    simulator.start_test(specimen, config)

    # 시험 완료 대기
    while not completed_event:
        time.sleep(0.05)

    print(f"\n>> 시험 종료: {completion_reason}")
    print(f">> 총 수집 데이터 포인트: {len(data_points):,} 개\n")

    # 4. 물성치 계산
    result = MaterialCalculator.calculate(specimen, config, data_points, completion_reason)

    print("=" * 65)
    print("                  주요 기계적 물성 시험 결과")
    print("=" * 65)
    print(f" 1. 최대 하중 (Peak Load, Pmax)       : {result.peak_load_n:10,f} N")
    print(f" 2. 인장 강도 (Tensile Strength, Rm)   : {result.peak_stress_mpa:10.2f} MPa")
    print(f" 3. 항복 강도 (Yield Strength, Rp0.2)  : {result.yield_stress_mpa:10.2f} MPa")
    print(f" 4. 탄성 계수 (Young's Modulus, E)     : {result.elastic_modulus_gpa:10.2f} GPa")
    print(f" 5. 파단 연신율 (Elongation at Break, A): {result.elongation_pct:10.2f} %")
    print(f" 6. 파단 변위 (Break Displacement)     : {result.break_displacement_mm:10.3f} mm")
    print(f" 7. 흡수 에너지 (Absorbed Energy, U)   : {result.energy_joule:10.2f} J")
    print("=" * 65 + "\n")

    # 5. 엑셀 및 PDF 파일 저장
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)

    excel_path = os.path.join(output_dir, "Salt_UTM_Demo_Report.xlsx")
    pdf_path = os.path.join(output_dir, "Salt_UTM_Demo_Certificate.pdf")

    print("[리포트 파일 생성]")
    ExcelExporter.export(excel_path, specimen, config, result, data_points)
    print(f" [OK] 엑셀 성적서 저장 완료: {excel_path}")

    PDFExporter.export(pdf_path, specimen, config, result, data_points)
    print(f" [OK] PDF 공식 성적서 저장 완료: {pdf_path}\n")

    print("모든 시험 및 내보내기 검증이 성공적으로 완료되었습니다!")


if __name__ == "__main__":
    run_demo()
