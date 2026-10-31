"""
Salt Sw ver.1 - Material Mechanics Calculator
계측 데이터로부터 최대하중, 인장강도, 0.2% 오프셋 항복강도, 탄성계수, 연신율, 파괴에너지 산출
"""

from typing import List
from .models import DataPoint, Specimen, TestConfig, TestResult


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

        # 1. 최대 하중 및 인장/압축 강도 (Peak Load / UTS)
        peak_point = max(data_points, key=lambda p: p.load_n)
        peak_load = peak_point.load_n
        peak_stress = peak_load / area

        # 2. 탄성계수 (Young's Modulus) 계산
        # 변형률 0.05% ~ 0.2% 구간(선형 탄성 영역)에서의 기울기 d(Stress)/d(Strain)
        elastic_points = [p for p in data_points if 0.03 <= p.strain_pct <= 0.25]
        if len(elastic_points) >= 3:
            # 선형 회귀 (Least Squares)
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

        # 3. 0.2% 오프셋 항복강도 (Yield Strength, Rp0.2)
        # 탄성 기울기를 변형률 +0.2% (0.002)만큼 오프셋한 직선과 S-S 곡선의 교점
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
            # 교점을 명확히 찾지 못한 경우 통상 피크 응력의 60~65% 수준으로 추정
            yield_stress = peak_stress * 0.62
            yield_load = peak_load * 0.62

        # 4. 파단 하중, 파단 변위, 파단 연신율 (Fracture)
        last_point = data_points[-1]
        break_load = last_point.load_n
        break_disp = last_point.displacement_mm
        elongation = last_point.strain_pct
        is_fractured = "파단" in completion_reason

        # 5. 파괴 에너지 / 흡수 에너지 (Toughness / Energy)
        # 하중-변위 곡선의 사다리꼴 적분: Integral(P * d(delta)) [N*mm = mJ -> J]
        energy_j = 0.0
        for i in range(1, len(data_points)):
            p_prev = data_points[i - 1]
            p_curr = data_points[i]
            d_disp = p_curr.displacement_mm - p_prev.displacement_mm
            avg_load = (p_curr.load_n + p_prev.load_n) / 2.0
            energy_j += (avg_load * d_disp) / 1000.0  # N*mm to Joules (N*m)

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
            is_fractured=is_fractured
        )
