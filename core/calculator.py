"""
Salt Sw ver.1 - Material Mechanics Calculator
계측 데이터로부터 인장, 압축, 굽힘(3점/4점), 유지(크리프/응력 이완) 물성 산출
표준 준용: KS B 0802 / ASTM E8 (인장), KS B 0807 / ASTM E9 (압축),
           KS B 0804 / ASTM D790 / ISO 178 (굽힘), ASTM E139 / ASTM E328 (유지)
"""

from typing import List
from .models import DataPoint, Specimen, TestConfig, TestMode, BendingType, HoldingType, TestResult


class MaterialCalculator:
    """재료 물성치 자동 계산기"""

    @staticmethod
    def calculate(specimen: Specimen, config: TestConfig,
                  data_points: List[DataPoint], completion_reason: str = "") -> TestResult:
        """수집된 데이터 포인트 배열로부터 정밀 물성 결과 계산"""
        if not data_points:
            return TestResult(
                test_mode=config.mode,
                specimen_id=specimen.specimen_id,
                material=specimen.material,
                area_mm2=specimen.cross_sectional_area_mm2,
                gauge_length_mm=specimen.gauge_length_mm
            )

        area = specimen.cross_sectional_area_mm2
        l0 = specimen.gauge_length_mm
        total_time = data_points[-1].time_s
        total_samples = len(data_points)

        # 1. 최대 하중 및 인장/압축/굽힘 강도
        peak_point = max(data_points, key=lambda p: p.load_n)
        peak_load = peak_point.load_n
        
        flexural_modulus_gpa = 0.0
        e_modulus_gpa = 205.0

        if config.mode == TestMode.BENDING:
            b = max(0.1, specimen.width_mm)
            d = max(0.1, specimen.thickness_mm)
            L = max(1.0, config.span_length_mm)
            
            # 3점 굽힘 최대 휨 응력: sigma_f = (3 * P * L) / (2 * b * d^2)
            if config.bending_type == BendingType.THREE_POINT:
                peak_stress = (3.0 * peak_load * L) / (2.0 * b * (d ** 2))
            else:
                # 4점 굽힘 (지간 1/3 분할 기준): sigma_f = (P * L) / (b * d^2)
                peak_stress = (peak_load * L) / (b * (d ** 2))
                
            # 휨 탄성계수: E_f = (L^3 * m) / (4 * b * d^3)
            early_points = [p for p in data_points if 0.2 <= p.displacement_mm <= 3.0]
            if len(early_points) >= 3:
                disps = [p.displacement_mm for p in early_points]
                loads = [p.load_n for p in early_points]
                n = len(disps)
                s_x = sum(disps)
                s_y = sum(loads)
                s_xx = sum(x * x for x in disps)
                s_xy = sum(x * y for x, y in zip(disps, loads))
                denom = (n * s_xx - s_x * s_x)
                m_slope = (n * s_xy - s_x * s_y) / denom if denom != 0 else 500.0
                e_flex_mpa = ((L ** 3) * m_slope) / (4.0 * b * (d ** 3))
                flexural_modulus_gpa = max(0.1, round(e_flex_mpa / 1000.0, 2))
            else:
                flexural_modulus_gpa = 180.0
                
            e_modulus_gpa = flexural_modulus_gpa
        else:
            peak_stress = peak_load / area

        # 2. 유지 시험 (Holding) 전용 파라미터 연산
        init_h_val = 0.0
        final_h_val = 0.0
        creep_def = 0.0
        relax_pct = 0.0

        if config.mode == TestMode.HOLDING:
            if config.holding_type == HoldingType.LOAD_HOLD:
                init_h_val = data_points[min(5, len(data_points)-1)].displacement_mm
                final_h_val = data_points[-1].displacement_mm
                creep_def = max(0.0, final_h_val - init_h_val)
            else:
                init_h_val = max(1.0, data_points[min(5, len(data_points)-1)].load_n)
                final_h_val = data_points[-1].load_n
                relax_pct = max(0.0, ((init_h_val - final_h_val) / init_h_val) * 100.0)

        # 3. 탄성계수 (Young's Modulus) 계산 (인장/압축)
        if config.mode in [TestMode.TENSILE, TestMode.COMPRESSION]:
            elastic_points = [p for p in data_points if 0.03 <= p.strain_pct <= 0.25]
            if len(elastic_points) >= 3:
                strains = [p.strain_pct / 100.0 for p in elastic_points]
                stresses = [p.stress_mpa for p in elastic_points]
                n = len(strains)
                sum_x = sum(strains)
                sum_y = sum(stresses)
                sum_xx = sum(x * x for x in strains)
                sum_xy = sum(x * y for x, y in zip(strains, stresses))
                denom = (n * sum_xx - sum_x * sum_x)
                if denom != 0:
                    e_slope_mpa = (n * sum_xy - sum_x * sum_y) / denom
                    e_modulus_gpa = max(0.1, e_slope_mpa / 1000.0)
                else:
                    e_modulus_gpa = 205.0
            else:
                e_modulus_gpa = 205.0

        # 4. 0.2% 오프셋 항복강도 (Yield Strength, Rp0.2)
        e_slope = e_modulus_gpa * 1000.0  # MPa
        yield_stress = 0.0
        yield_load = 0.0
        offset_strain = 0.002  # 0.2%

        for p in data_points:
            strain_val = p.strain_pct / 100.0
            if strain_val > offset_strain:
                offset_line_stress = e_slope * (strain_val - offset_strain)
                if p.stress_mpa <= offset_line_stress:
                    yield_stress = p.stress_mpa
                    yield_load = p.load_n
                    break

        if yield_stress == 0.0:
            yield_stress = peak_stress * 0.62
            yield_load = peak_load * 0.62

        # 5. 파단 하중, 파단 변위, 파단 연신율 (Fracture)
        last_point = data_points[-1]
        break_load = last_point.load_n
        break_disp = last_point.displacement_mm
        elongation = last_point.strain_pct
        is_fractured = "파단" in completion_reason

        # 6. 파괴 에너지 / 흡수 에너지 (Toughness / Energy)
        energy_j = 0.0
        for i in range(1, len(data_points)):
            p_prev = data_points[i - 1]
            p_curr = data_points[i]
            d_disp = p_curr.displacement_mm - p_prev.displacement_mm
            avg_load = (p_curr.load_n + p_prev.load_n) / 2.0
            energy_j += (avg_load * d_disp) / 1000.0

        return TestResult(
            test_mode=config.mode,
            specimen_id=specimen.specimen_id,
            material=specimen.material,
            area_mm2=round(area, 3),
            gauge_length_mm=round(l0, 2),
            peak_load_n=round(peak_load, 1),
            peak_stress_mpa=round(peak_stress, 2),
            yield_load_n=round(yield_load, 1),
            yield_stress_mpa=round(yield_stress, 2),
            elastic_modulus_gpa=round(e_modulus_gpa, 2),
            break_load_n=round(break_load, 1),
            break_displacement_mm=round(break_disp, 3),
            elongation_pct=round(elongation, 2),
            energy_joule=round(energy_j, 2),
            total_time_s=round(total_time, 2),
            total_samples=total_samples,
            is_fractured=is_fractured,
            flexural_modulus_gpa=flexural_modulus_gpa,
            initial_holding_val=round(init_h_val, 3),
            final_holding_val=round(final_h_val, 3),
            creep_deflection_mm=round(creep_def, 4),
            load_relaxation_pct=round(relax_pct, 2)
        )
