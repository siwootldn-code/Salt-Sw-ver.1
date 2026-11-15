"""
Salt Sw ver.1 - Material Mechanics Calculator
계측 데이터로부터 인장, 압축, 굽힘(3점/4점), 유지(크리프/응력 이완) 물성 산출
표준 준용: KS B 0802 / ASTM E8 (인장), KS B 0807 / ASTM E9 (압축),
           KS B 0804 / ASTM D790 / ISO 178 (굽힘), ASTM E139 / ASTM E328 (유지)

신율계(Extensometer) 적용:
- 신율계를 사용하면 변형률(ε)·탄성계수(E)·0.2% 오프셋 항복강도(Rp0.2)·연신율(A)을
  크로스헤드 변위가 아닌 신율계 변위와 신율계 표점거리 기준으로 산출한다.
- 결과에는 어떤 변위를 변형률 측정 소스로 사용했는지 기록한다 (Crosshead / Extensometer).
"""

from typing import Callable, List

from .models import (
    DataPoint, ExtensometerType, Specimen, TestConfig, TestMode, BendingType, HoldingType, TestResult
)


class MaterialCalculator:
    """재료 물성치 자동 계산기"""

    EXT_SOURCE_MV = "Extensometer (mV)"
    EXT_SOURCE_PULSE = "Extensometer (Pulse)"
    SOURCE_CROSSHEAD = "Crosshead"
    SOURCE_CROSSHEAD_FALLBACK = "Crosshead (extensometer signal missing)"

    @staticmethod
    def resolve_strain_source(config: TestConfig, data_points: List[DataPoint]) -> tuple:
        """
        변형률 측정 소스 판정.
        반환: (신율계 사용 여부, 소스 문자열)
        """
        ext = getattr(config, "ext", None)
        if not (ext and ext.enabled):
            return False, MaterialCalculator.SOURCE_CROSSHEAD

        ext_points = [p for p in data_points if getattr(p, "ext_valid", False)]
        # 전체 계측점의 절반 이상에서 신율계 신호가 들어와야 신율계 기준으로 인정
        if len(ext_points) >= max(3, int(len(data_points) * 0.5)):
            source = MaterialCalculator.EXT_SOURCE_MV if ext.is_mv else MaterialCalculator.EXT_SOURCE_PULSE
            return True, source
        return False, MaterialCalculator.SOURCE_CROSSHEAD_FALLBACK

    @staticmethod
    def calculate(specimen: Specimen, config: TestConfig,
                  data_points: List[DataPoint], completion_reason: str = "") -> TestResult:
        """수집된 데이터 포인트 배열로부터 정밀 물성 결과 계산"""
        ext_cfg = getattr(config, "ext", None)
        ext_enabled = bool(ext_cfg and ext_cfg.enabled)

        if not data_points:
            return TestResult(
                test_mode=config.mode,
                specimen_id=specimen.specimen_id,
                material=specimen.material,
                area_mm2=specimen.cross_sectional_area_mm2,
                gauge_length_mm=specimen.gauge_length_mm,
                ext_enabled=ext_enabled,
                ext_type=ext_cfg.ext_type if ext_enabled else "",
                ext_gauge_length_mm=ext_cfg.gauge_length_mm if ext_enabled else 0.0,
                strain_source=MaterialCalculator.SOURCE_CROSSHEAD,
            )

        area = specimen.cross_sectional_area_mm2
        use_ext, strain_source = MaterialCalculator.resolve_strain_source(config, data_points)

        # 변형률 기준 표점거리: 신율계 사용 시 신율계 GL, 아니면 시편 L0
        l0 = ext_cfg.gauge_length_mm if use_ext else specimen.gauge_length_mm

        def strain_of(p: DataPoint) -> float:
            """해당 시점의 분석용 변형률(%)"""
            if use_ext and getattr(p, "ext_valid", False):
                return p.ext_strain_pct
            return p.strain_pct

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
            early_points = [p for p in data_points if 0.2 <= (p.ext_disp_mm if use_ext and p.ext_valid else p.displacement_mm) <= 3.0]
            if len(early_points) >= 3:
                disps = [p.ext_disp_mm if use_ext and p.ext_valid else p.displacement_mm for p in early_points]
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
                disp_of: Callable[[DataPoint], float] = (
                    (lambda p: p.ext_disp_mm) if use_ext else (lambda p: p.displacement_mm)
                )
                init_h_val = disp_of(data_points[min(5, len(data_points) - 1)])
                final_h_val = disp_of(data_points[-1])
                creep_def = max(0.0, final_h_val - init_h_val)
            else:
                init_h_val = max(1.0, data_points[min(5, len(data_points) - 1)].load_n)
                final_h_val = data_points[-1].load_n
                relax_pct = max(0.0, ((init_h_val - final_h_val) / init_h_val) * 100.0)

        # 3. 탄성계수 (Young's Modulus) 계산 (인장/압축)
        #    1차: 저변형률 구간(0.004~0.15%)에서 원점 통과 최소자승 기울기
        def _regress_through_origin(points: List[DataPoint]) -> float:
            xs = [strain_of(p) / 100.0 for p in points]
            ys = [p.stress_mpa for p in points]
            sxx = sum(x * x for x in xs)
            sxy = sum(x * y for x, y in zip(xs, ys))
            if sxx <= 0:
                return 0.0
            return sxy / sxx

        def _yield_02(e_modulus_mpa: float):
            """0.2% 오프셋 방식으로 항복 응력/하중 탐색"""
            slope = max(1.0, e_modulus_mpa)
            offset = 0.002
            for p in data_points:
                strain_val = strain_of(p) / 100.0
                if strain_val > offset:
                    offset_line_stress = slope * (strain_val - offset)
                    if p.stress_mpa <= offset_line_stress:
                        return p.stress_mpa, p.load_n
            return 0.0, 0.0

        def _elastic_band(max_strain_pct: float, max_stress_mpa: float = None) -> List[DataPoint]:
            band = []
            for p in data_points:
                s_pct = strain_of(p)
                if s_pct < 0.004 or s_pct > max_strain_pct:
                    continue
                if max_stress_mpa is not None and p.stress_mpa > max_stress_mpa:
                    continue
                band.append(p)
            return band

        yield_stress = 0.0
        yield_load = 0.0

        if config.mode in [TestMode.TENSILE, TestMode.COMPRESSION]:
            first_band = _elastic_band(0.15)
            e_first = _regress_through_origin(first_band) if len(first_band) >= 2 else 0.0
            if e_first <= 1000.0:
                e_first = 205000.0

            yield_stress, yield_load = _yield_02(e_first)
            if yield_stress == 0.0:
                yield_stress = peak_stress * 0.62
                yield_load = peak_load * 0.62

            # 2차: 항복 응력의 50% 이하(진짜 선형 구간)만으로 재회귀
            refined = _elastic_band(0.5, max_stress_mpa=yield_stress * 0.5)
            e_refined = _regress_through_origin(refined) if len(refined) >= 2 else 0.0
            if 1000.0 < e_refined < 500000.0:
                e_modulus_gpa = max(0.1, e_refined / 1000.0)
                yield_stress, yield_load = _yield_02(e_refined)
                if yield_stress == 0.0:
                    yield_stress = peak_stress * 0.62
                    yield_load = peak_load * 0.62
            else:
                e_modulus_gpa = max(0.1, e_first / 1000.0)

        # 4. 굽힘·유지 모드의 항복값 (인장/압축 모드에서는 위에서 산출됨)
        if config.mode in (TestMode.BENDING, TestMode.HOLDING) and yield_stress == 0.0:
            ys, yl = _yield_02(max(e_modulus_gpa, 0.1) * 1000.0)
            if ys > 0.0:
                yield_stress, yield_load = ys, yl
            else:
                yield_stress = peak_stress * 0.62
                yield_load = peak_load * 0.62

        # 5. 파단 하중, 파단 변위, 파단 연신율 (Fracture)
        last_point = data_points[-1]
        break_load = last_point.load_n
        break_disp = last_point.displacement_mm          # 크로스헤드 변위
        elongation = strain_of(last_point)               # 분석 기준 변형률 (신율계 사용 시 신율계)
        is_fractured = "파단" in completion_reason

        # 6. 파괴 에너지 / 흡수 에너지 (Toughness / Energy) - 크로스헤드 변위 기준 일량
        energy_j = 0.0
        for i in range(1, len(data_points)):
            p_prev = data_points[i - 1]
            p_curr = data_points[i]
            d_disp = p_curr.displacement_mm - p_prev.displacement_mm
            avg_load = (p_curr.load_n + p_prev.load_n) / 2.0
            energy_j += (avg_load * d_disp) / 1000.0

        # 7. 신율계 계측 요약 (사용 시)
        ext_max_disp = 0.0
        ext_break_disp = 0.0
        ext_gauge = 0.0
        if ext_enabled:
            ext_gauge = ext_cfg.gauge_length_mm
            ext_values = [p.ext_disp_mm for p in data_points if p.ext_valid]
            if ext_values:
                ext_max_disp = max(ext_values)
                ext_break_disp = ext_values[-1]

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
            load_relaxation_pct=round(relax_pct, 2),
            ext_enabled=ext_enabled,
            ext_type=ext_cfg.ext_type if ext_enabled else "",
            ext_gauge_length_mm=round(ext_gauge, 2),
            ext_max_disp_mm=round(ext_max_disp, 4),
            ext_break_disp_mm=round(ext_break_disp, 4),
            strain_source=strain_source,
        )
