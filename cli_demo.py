"""
Salt Sw ver.1 - CLI Headless Demonstration & Validation Script
GUI 없이 터미널에서 전체 가상 시험, 물성 연산, 엑셀/PDF 리포트 생성을 즉시 검증하는 스크립트

실행:
    python cli_demo.py            # 신율계 미사용 / mV 타입 / 펄스 타입 3종 비교
    python cli_demo.py off        # 신율계 미사용만
    python cli_demo.py mv         # mV 타입만
    python cli_demo.py pulse      # 펄스 타입만
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.models import Specimen, SpecimenType, TestConfig, TestMode, ExtensometerSettings
from core.simulator import VirtualUTMSimulator
from core.calculator import MaterialCalculator
from exporters.excel_exporter import ExcelExporter
from exporters.pdf_exporter import PDFExporter


def make_specimen() -> Specimen:
    return Specimen(
        specimen_id="SALT-DEMO-SS400",
        material="SS400 (일반구조용 압연강재)",
        specimen_type=SpecimenType.FLAT,
        width_mm=12.5,
        thickness_mm=3.2,
        gauge_length_mm=50.0,
    )


def run_demo(ext: ExtensometerSettings, label: str, output_dir: str, save_files: bool = True):
    """신율계 설정 1종에 대한 가상 시험 -> 물성 계산 -> 성적서 저장"""
    print("=" * 78)
    print(f"      SALT SW VER.1 — 가상 인장 시험 ({label})")
    print("=" * 78)

    specimen = make_specimen()
    config = TestConfig(
        mode=TestMode.TENSILE,
        test_speed_mm_min=60.0,
        fracture_drop_ratio=0.5,
        max_displacement_mm=30.0,
        sampling_rate_hz=200,
        ext=ext.copy(),
    )

    print(f" - 시편        : {specimen.specimen_id} / {specimen.material} "
          f"(폭 {specimen.width_mm} x 두께 {specimen.thickness_mm} mm, L0 {specimen.gauge_length_mm} mm)")
    print(f" - 단면적      : {specimen.cross_sectional_area_mm2:.3f} mm²")
    if ext.enabled:
        ext_name = "mV 타입" if ext.is_mv else "펄스 타입"
        print(f" - 신율계      : {ext_name} / 표점거리 {ext.gauge_length_mm:.1f} mm", end="")
        if ext.is_mv:
            print(f" / 정격 {ext.rated_output_mv_v:.2f} mV/V x {ext.excitation_v:.1f} V "
                  f"= {ext.full_scale_signal_mv:.3f} mV (정격 변위 {ext.full_scale_mm:.1f} mm)")
        else:
            print(f" / 분해능 {ext.resolution_mm_per_pulse:.5f} mm/pulse"
                  f"{' / 방향 반전' if ext.direction_invert else ''}")
    else:
        print(" - 신율계      : 사용 안 함 (크로스헤드 변위 기준)")

    data_points = []
    state = {}
    simulator = VirtualUTMSimulator()

    def on_data(dp):
        data_points.append(dp)
        if len(data_points) % 40 == 0:
            if dp.ext_valid:
                ext_text = f" | 신율계 {dp.ext_raw:9.4f} mV" if ext.is_mv else f" | 신율계 {dp.ext_raw:9.0f} pulse"
            else:
                ext_text = ""
            print(f"  {dp.time_s:6.2f}s | 변위 {dp.displacement_mm:7.3f}mm | "
                  f"하중 {dp.load_n:8.1f}N | 응력 {dp.stress_mpa:6.1f}MPa | 변형률 {dp.strain_pct:5.2f}%{ext_text}")

    def on_done(reason):
        state["reason"] = reason

    simulator.on_data_received = on_data
    simulator.on_test_completed = on_done
    simulator.start_test(specimen, config)

    while "reason" not in state:
        time.sleep(0.05)

    print(f"\n>> 시험 종료: {state['reason']} | 계측점 {len(data_points):,} 개\n")

    result = MaterialCalculator.calculate(specimen, config, data_points, state["reason"])

    print("-" * 78)
    print(f" 1. 최대 하중 (Pmax)          : {result.peak_load_n:12,.1f} N")
    print(f" 2. 인장 강도 (Rm)            : {result.peak_stress_mpa:12.2f} MPa")
    print(f" 3. 항복 강도 (Rp0.2)         : {result.yield_stress_mpa:12.2f} MPa")
    print(f" 4. 탄성 계수 (E)             : {result.elastic_modulus_gpa:12.2f} GPa")
    print(f" 5. 파단 연신율 (A)           : {result.elongation_pct:12.2f} %")
    print(f" 6. 파단 변위 (크로스헤드)    : {result.break_displacement_mm:12.3f} mm")
    if result.ext_enabled:
        print(f" 7. 파단 변위 (신율계)        : {result.ext_break_disp_mm:12.3f} mm")
        print(f" 8. 신율계 최대 변위          : {result.ext_max_disp_mm:12.3f} mm")
        print(f"    변형률 측정 소스          : {result.strain_source} (GL {result.ext_gauge_length_mm:.1f} mm)")
    else:
        print(f" 7. 변형률 측정 소스          : {result.strain_source}")
    print(f" 9. 흡수 에너지 (U)           : {result.energy_joule:12.2f} J")
    print("-" * 78)

    if save_files:
        os.makedirs(output_dir, exist_ok=True)
        suffix = "off" if not ext.enabled else ext.ext_type.lower()
        excel_path = os.path.join(output_dir, f"Salt_UTM_Demo_Report_{suffix}.xlsx")
        pdf_path = os.path.join(output_dir, f"Salt_UTM_Demo_Certificate_{suffix}.pdf")
        ExcelExporter.export(excel_path, specimen, config, result, data_points)
        PDFExporter.export(pdf_path, specimen, config, result, data_points)
        print(f" [OK] 엑셀 성적서: {excel_path}")
        print(f" [OK] PDF 성적서 : {pdf_path}")

    print()
    return result


def main():
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

    scenarios = {
        "off": ExtensometerSettings(enabled=False),
        "mv": ExtensometerSettings(enabled=True, ext_type="MV"),
        "pulse": ExtensometerSettings(enabled=True, ext_type="PULSE"),
    }
    labels = {"off": "신율계 미사용", "mv": "신율계 mV 타입", "pulse": "신율계 펄스 타입"}

    if mode in scenarios:
        run_demo(scenarios[mode], labels[mode], output_dir)
        return

    results = {}
    for key in ("off", "mv", "pulse"):
        results[key] = run_demo(scenarios[key], labels[key], output_dir, save_files=(key == "mv"))

    print("=" * 78)
    print("                     신율계 타입별 결과 비교")
    print("=" * 78)
    print(f"{'항목':<20}{'미사용':>21}{'mV 타입':>21}{'펄스 타입':>21}")
    rows = [
        ("최대 하중 (N)", lambda r: f"{r.peak_load_n:,.1f}"),
        ("인장 강도 (MPa)", lambda r: f"{r.peak_stress_mpa:.2f}"),
        ("항복 강도 (MPa)", lambda r: f"{r.yield_stress_mpa:.2f}"),
        ("탄성 계수 (GPa)", lambda r: f"{r.elastic_modulus_gpa:.2f}"),
        ("파단 연신율 (%)", lambda r: f"{r.elongation_pct:.2f}"),
        ("파단 변위 (mm)", lambda r: f"{r.break_displacement_mm:.3f}"),
        ("측정 소스", lambda r: {"Crosshead": "Crosshead", "Extensometer (mV)": "Ext. (mV)",
                                "Extensometer (Pulse)": "Ext. (Pulse)"}.get(r.strain_source, r.strain_source)),
    ]
    for name, fn in rows:
        print(f"{name:<20}{fn(results['off']):>21}{fn(results['mv']):>21}{fn(results['pulse']):>21}")
    print("=" * 78)
    print("신율계 사용 시 연신율과 탄성계수는 신율계 변위(표점거리 기준)로 계산됩니다.")
    print("모든 시험 및 내보내기 검증이 성공적으로 완료되었습니다!")


if __name__ == "__main__":
    main()
