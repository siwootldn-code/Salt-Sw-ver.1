"""
Salt Sw ver.1 - 신율계(Extensometer) / 환경 설정 자동 검증 테스트

실행: python3 -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import time
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from core.models import (
    DataPoint, ExtensometerSettings, ExtensometerType, Specimen, SpecimenType,
    TestConfig, TestMode,
)
from core.calculator import MaterialCalculator
from core.preferences import AppPreferences, PreferencesManager
from core.serial_driver import SerialUTMDriver
from core.simulator import VirtualUTMSimulator
from exporters.excel_exporter import ExcelExporter
from exporters.pdf_exporter import PDFExporter


def _specimen() -> Specimen:
    return Specimen(
        specimen_id="TEST-SP-001",
        material="SS400",
        specimen_type=SpecimenType.FLAT,
        width_mm=12.5,
        thickness_mm=3.2,
        gauge_length_mm=50.0,
    )


def _run_simulation(ext: ExtensometerSettings, mode: TestMode = TestMode.TENSILE,
                    speed_mm_min: float = 120.0, sampling_hz: int = 300) -> tuple:
    """가상 시험을 빠르게 1회 수행하고 (설정, 데이터, 결과) 반환"""
    specimen = _specimen()
    config = TestConfig(
        mode=mode,
        test_speed_mm_min=speed_mm_min,
        fracture_drop_ratio=0.5,
        max_displacement_mm=40.0,
        sampling_rate_hz=sampling_hz,
        ext=ext,
    )
    sim = VirtualUTMSimulator()
    sim.connect()
    points = []
    state = {}

    sim.on_data_received = points.append
    sim.on_test_completed = lambda reason: state.setdefault("reason", reason)
    sim.start_test(specimen, config)

    deadline = time.time() + 90
    while "reason" not in state and time.time() < deadline:
        time.sleep(0.05)
    sim.stop_test()

    result = MaterialCalculator.calculate(specimen, config, points, state.get("reason", ""))
    return config, points, result


class TestExtensometerConversion(unittest.TestCase):
    """mV / 펄스 신호 환산식"""

    def test_mv_conversion_and_round_trip(self):
        ext = ExtensometerSettings(
            enabled=True, ext_type=ExtensometerType.MV.value,
            rated_output_mv_v=2.0, excitation_v=5.0, full_scale_mm=25.0,
            calib_factor=1.0, zero_offset_mv=0.0, gauge_length_mm=50.0,
        )
        self.assertAlmostEqual(ext.full_scale_signal_mv, 10.0, places=6)
        # 정격 신호(10 mV)는 정격 변위 25 mm
        self.assertAlmostEqual(ext.mv_to_mm(10.0), 25.0, places=6)
        self.assertAlmostEqual(ext.mv_to_mm(4.0), 10.0, places=6)
        # 영점 오프셋 반영
        ext2 = ExtensometerSettings(enabled=True, zero_offset_mv=1.0)
        self.assertAlmostEqual(ext2.mv_to_mm(1.0), 0.0, places=6)
        # 역산 왕복
        for mm in (0.0, 1.234, 12.5, 24.9):
            self.assertAlmostEqual(ext.mv_to_mm(ext.mm_to_mv(mm)), mm, places=6)
        # 교정 계수 반영
        ext3 = ExtensometerSettings(enabled=True, calib_factor=0.98)
        self.assertAlmostEqual(ext3.mv_to_mm(10.0), 25.0 * 0.98, places=6)
        # 변형률 환산
        self.assertAlmostEqual(ext.to_strain_pct(12.5), 25.0, places=6)

    def test_pulse_conversion_and_invert(self):
        ext = ExtensometerSettings(
            enabled=True, ext_type=ExtensometerType.PULSE.value,
            resolution_mm_per_pulse=0.001, direction_invert=False, gauge_length_mm=50.0,
        )
        self.assertAlmostEqual(ext.pulses_to_mm(1000), 1.0, places=6)
        self.assertAlmostEqual(ext.pulses_to_mm(12500), 12.5, places=6)
        self.assertAlmostEqual(ext.mm_to_pulses(12.5), 12500.0, places=3)

        inv = ExtensometerSettings(
            enabled=True, ext_type=ExtensometerType.PULSE.value,
            resolution_mm_per_pulse=0.001, direction_invert=True,
        )
        self.assertAlmostEqual(inv.pulses_to_mm(1000), -1.0, places=6)
        self.assertAlmostEqual(inv.mm_to_pulses(1.0), -1000.0, places=3)
        # 영점 카운트 반영
        zeroed = ExtensometerSettings(enabled=True, ext_type="PULSE", resolution_mm_per_pulse=0.001, zero_offset_pulse=500)
        self.assertAlmostEqual(zeroed.pulses_to_mm(1500), 1.0, places=6)

    def test_type_helpers(self):
        mv = ExtensometerSettings(enabled=True, ext_type="MV")
        pulse = ExtensometerSettings(enabled=True, ext_type="PULSE")
        self.assertTrue(mv.is_mv and not mv.is_pulse)
        self.assertTrue(pulse.is_pulse and not pulse.is_mv)
        self.assertFalse(ExtensometerSettings().enabled)
        self.assertEqual(mv.to_displacement(mv.to_raw(7.5)), 7.5)


class TestPreferences(unittest.TestCase):
    """환경 설정 저장/복원 및 하위 호환"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "preferences.json")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_defaults_when_missing(self):
        mgr = PreferencesManager(self.path)
        self.assertFalse(mgr.ext.enabled)
        self.assertEqual(mgr.ext.ext_type, "MV")
        self.assertEqual(mgr.ext.gauge_length_mm, 50.0)
        self.assertEqual(mgr.ext.rated_output_mv_v, 2.0)

    def test_save_and_reload(self):
        mgr = PreferencesManager(self.path)
        mgr.data.ext = ExtensometerSettings(
            enabled=True, ext_type="PULSE", gauge_length_mm=25.0,
            resolution_mm_per_pulse=0.0005, direction_invert=True, zero_offset_pulse=120,
        )
        self.assertTrue(mgr.save())
        self.assertTrue(os.path.exists(self.path))

        reloaded = PreferencesManager(self.path)
        self.assertTrue(reloaded.ext.enabled)
        self.assertEqual(reloaded.ext.ext_type, "PULSE")
        self.assertAlmostEqual(reloaded.ext.gauge_length_mm, 25.0)
        self.assertAlmostEqual(reloaded.ext.resolution_mm_per_pulse, 0.0005)
        self.assertTrue(reloaded.ext.direction_invert)
        self.assertAlmostEqual(reloaded.ext.zero_offset_pulse, 120)

    def test_backward_compatible_partial_file(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"extensometer": {"enabled": True}}, f)
        mgr = PreferencesManager(self.path)
        self.assertTrue(mgr.ext.enabled)
        self.assertEqual(mgr.ext.ext_type, "MV")
        self.assertEqual(mgr.ext.excitation_v, 5.0)

    def test_unknown_and_invalid_values_are_ignored(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({
                "version": 99,
                "extensometer": {
                    "enabled": "true", "ext_type": "weird", "gauge_length_mm": "abc",
                    "rated_output_mv_v": 0, "unknown_key": 5,
                },
                "future_section": {"x": 1},
            }, f)
        mgr = PreferencesManager(self.path)
        self.assertTrue(mgr.ext.enabled)
        self.assertEqual(mgr.ext.ext_type, "MV")           # 잘못된 값은 기본값
        self.assertEqual(mgr.ext.gauge_length_mm, 50.0)
        self.assertGreater(mgr.ext.rated_output_mv_v, 0)   # 0 방지

    def test_corrupt_json_falls_back_to_defaults(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ not valid json ")
        mgr = PreferencesManager(self.path)
        self.assertFalse(mgr.ext.enabled)

    def test_reset(self):
        mgr = PreferencesManager(self.path)
        mgr.data.ext = ExtensometerSettings(enabled=True, ext_type="PULSE")
        mgr.save()
        mgr.reset()
        self.assertFalse(mgr.ext.enabled)
        self.assertEqual(mgr.ext.ext_type, "MV")
        self.assertFalse(PreferencesManager(self.path).ext.enabled)


class TestSerialDriverExtensometer(unittest.TestCase):
    """RS-232 패킷의 선택 신율계 채널 파싱"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.driver = SerialUTMDriver()
        self.driver.calib_mgr.config_path = os.path.join(self.tmpdir.name, "calib.json")
        self.driver.calib_mgr.data.load_zero_offset = 0.0
        self.driver.calib_mgr.data.disp_zero_offset = 0.0
        self.driver.specimen = _specimen()
        self.driver.start_time = 0.0

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_standard_frame_without_ext_channel(self):
        self.driver.set_extensometer(ExtensometerSettings(enabled=True))
        dp = self.driver._parse_packet("ST,GS,+0012.35kg, +0001.20mm")
        self.assertIsNotNone(dp)
        self.assertFalse(dp.ext_valid)
        self.assertTrue(self.driver.ext_signal_lost)
        # 신율계 채널이 없으면 크로스헤드 변위로 변형률 계산 (1.20 / 50)
        self.assertAlmostEqual(dp.strain_pct, 2.4, places=3)

    def test_mv_channel(self):
        self.driver.set_extensometer(ExtensometerSettings(enabled=True, ext_type="MV"))
        dp = self.driver._parse_packet("ST,GS,+0012.35kg,+0001.20mm,+3.421mV")
        self.assertTrue(dp.ext_valid)
        self.assertAlmostEqual(dp.ext_raw, 3.421, places=4)
        self.assertAlmostEqual(dp.ext_disp_mm, 8.5525, places=4)   # 3.421/10*25
        self.assertAlmostEqual(dp.strain_pct, 17.105, places=3)    # 8.5525/50*100
        self.assertFalse(self.driver.ext_signal_lost)

    def test_pulse_channel(self):
        self.driver.set_extensometer(
            ExtensometerSettings(enabled=True, ext_type="PULSE", resolution_mm_per_pulse=0.001)
        )
        dp = self.driver._parse_packet("ST,GS,+0012.35kg,+0001.20mm,#12450")
        self.assertTrue(dp.ext_valid)
        self.assertAlmostEqual(dp.ext_disp_mm, 12.45, places=4)
        self.assertAlmostEqual(dp.strain_pct, 24.9, places=3)

    def test_third_plain_field_uses_selected_type(self):
        self.driver.set_extensometer(ExtensometerSettings(enabled=True, ext_type="MV"))
        dp = self.driver._parse_packet("+0012.35, +0001.20, +3.421")
        self.assertTrue(dp.ext_valid)
        self.assertAlmostEqual(dp.ext_disp_mm, 8.5525, places=4)

    def test_ext_disabled_ignores_extra_field(self):
        self.driver.set_extensometer(ExtensometerSettings(enabled=False))
        dp = self.driver._parse_packet("ST,GS,+0012.35kg,+0001.20mm,+3.421mV")
        self.assertFalse(dp.ext_valid)
        self.assertAlmostEqual(dp.strain_pct, 2.4, places=3)

    def test_tare_extensometer_sets_zero(self):
        self.driver.set_extensometer(ExtensometerSettings(enabled=True, ext_type="MV"))
        self.driver._parse_packet("+0012.35, +0001.20, +0.250")
        self.driver.tare_extensometer()
        self.assertAlmostEqual(self.driver.ext.zero_offset_mv, 0.25, places=4)
        dp = self.driver._parse_packet("+0012.35, +0001.20, +0.250")
        self.assertAlmostEqual(dp.ext_disp_mm, 0.0, places=4)

    def test_malformed_frames_do_not_crash(self):
        self.driver.set_extensometer(ExtensometerSettings(enabled=True))
        for frame in ("", "ST,GS", "\x02\x03", "NO DATA"):
            self.assertIsNone(self.driver._parse_packet(frame))


class TestExtensometerTestFlow(unittest.TestCase):
    """가상 시험 -> 물성 계산 -> 성적서 출력 전 과정"""

    @classmethod
    def setUpClass(cls):
        cls.off = _run_simulation(ExtensometerSettings(enabled=False))
        cls.mv = _run_simulation(ExtensometerSettings(enabled=True, ext_type="MV"))
        cls.pulse = _run_simulation(ExtensometerSettings(enabled=True, ext_type="PULSE"))
        cls.tmpdir = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_off_mode_uses_crosshead(self):
        _, points, result = self.off
        self.assertFalse(result.ext_enabled)
        self.assertEqual(result.strain_source, "Crosshead")
        self.assertEqual(result.ext_break_disp_mm, 0.0)
        self.assertTrue(all(not p.ext_valid for p in points))
        self.assertGreater(result.total_samples, 50)
        self.assertAlmostEqual(result.peak_stress_mpa, 450.0, delta=15.0)
        self.assertAlmostEqual(result.elastic_modulus_gpa, 205.0, delta=12.0)

    def test_mv_mode_uses_extensometer(self):
        config, points, result = self.mv
        self.assertTrue(result.ext_enabled)
        self.assertEqual(result.ext_type, "MV")
        self.assertEqual(result.strain_source, "Extensometer (mV)")
        self.assertEqual(result.ext_gauge_length_mm, 50.0)
        self.assertTrue(all(p.ext_valid for p in points))
        self.assertAlmostEqual(result.elastic_modulus_gpa, 205.0, delta=12.0)
        self.assertAlmostEqual(result.peak_stress_mpa, 450.0, delta=15.0)
        # 신율계 변위는 프레임/그립 변형이 빠진 만큼 크로스헤드 변위보다 작다
        self.assertLess(result.ext_break_disp_mm, result.break_displacement_mm)
        # 50 mm 표점거리 기준 24% 연신율 -> 약 12 mm
        self.assertAlmostEqual(result.ext_break_disp_mm, 12.0, delta=0.6)
        # 원시 신호가 실제 mV 범위 안에 있어야 함 (정격 10 mV = 25 mm)
        self.assertTrue(all(abs(p.ext_raw) <= 10.5 for p in points))

    def test_pulse_mode_uses_extensometer(self):
        _, points, result = self.pulse
        self.assertTrue(result.ext_enabled)
        self.assertEqual(result.ext_type, "PULSE")
        self.assertEqual(result.strain_source, "Extensometer (Pulse)")
        self.assertAlmostEqual(result.elastic_modulus_gpa, 205.0, delta=12.0)
        self.assertAlmostEqual(result.ext_break_disp_mm, 12.0, delta=0.6)
        # 펄스 카운트는 mm/pulse 0.001 기준 정수 카운트
        self.assertTrue(all(float(p.ext_raw).is_integer() for p in points))

    def test_extensometer_records_broader_consistency(self):
        _, _, off = self.off
        _, _, mv = self.mv
        _, _, pulse = self.pulse
        for res in (off, mv, pulse):
            self.assertGreater(res.peak_load_n, 17000.0)
            self.assertGreater(res.yield_stress_mpa, 200.0)
            self.assertGreater(res.elongation_pct, 18.0)

    def test_fallback_when_ext_signal_missing(self):
        import dataclasses
        config, points, _ = self.mv
        no_ext_points = [dataclasses.replace(p, ext_valid=False, ext_disp_mm=0.0, ext_strain_pct=0.0) for p in points]
        result = MaterialCalculator.calculate(_specimen(), config, no_ext_points, "시편 파단")
        self.assertFalse(result.strain_source.startswith("Extensometer"))
        self.assertEqual(result.strain_source, MaterialCalculator.SOURCE_CROSSHEAD_FALLBACK)
        self.assertAlmostEqual(result.elastic_modulus_gpa, 205.0, delta=12.0)

    def test_empty_data_points(self):
        result = MaterialCalculator.calculate(_specimen(), self.mv[0], [], "")
        self.assertEqual(result.total_samples, 0)
        self.assertTrue(result.ext_enabled)

    def test_excel_export_includes_extensometer(self):
        config, points, result = self.mv
        path = os.path.join(self.tmpdir.name, "ext_report.xlsx")
        ExcelExporter.export(path, _specimen(), config, result, points)
        self.assertTrue(os.path.exists(path))

        import openpyxl
        wb = openpyxl.load_workbook(path)
        summary_values = [
            str(cell.value) for row in wb["시험 성적 요약"].iter_rows() for cell in row if cell.value is not None
        ]
        self.assertTrue(any("신율계" in v for v in summary_values))
        self.assertTrue(any("Extensometer (mV)" in v for v in summary_values))
        raw_headers = [cell.value for cell in wb["계측 원시 데이터"][1]]
        self.assertIn("신율계 변위 (Ext, mm)", raw_headers)
        self.assertIn("신율계 원시값", raw_headers)

    def test_pdf_export_includes_extensometer(self):
        config, points, result = self.mv
        path = os.path.join(self.tmpdir.name, "ext_certificate.pdf")
        PDFExporter.export(path, _specimen(), config, result, points)
        self.assertTrue(os.path.exists(path))
        with open(path, "rb") as f:
            head = f.read(5)
        self.assertEqual(head, b"%PDF-")

    def test_export_without_extensometer(self):
        config, points, result = self.off
        path = os.path.join(self.tmpdir.name, "off_report.xlsx")
        ExcelExporter.export(path, _specimen(), config, result, points)
        import openpyxl
        wb = openpyxl.load_workbook(path)
        raw_headers = [cell.value for cell in wb["계측 원시 데이터"][1]]
        self.assertNotIn("신율계 변위 (Ext, mm)", raw_headers)


class TestOtherModesWithExtensometer(unittest.TestCase):
    """압축·유지 모드에서도 신율계가 동작하고 계산이 깨지지 않는지"""

    def test_compression_with_ext(self):
        _, points, result = _run_simulation(
            ExtensometerSettings(enabled=True, ext_type="MV"),
            mode=TestMode.COMPRESSION, speed_mm_min=60.0, sampling_hz=200,
        )
        self.assertTrue(result.ext_enabled)
        self.assertGreater(len(points), 10)
        self.assertEqual(result.strain_source, "Extensometer (mV)")

    def test_holding_with_ext(self):
        specimen = _specimen()
        config = TestConfig(
            mode=TestMode.HOLDING, test_speed_mm_min=120.0, sampling_rate_hz=200,
            target_holding_val=1000.0, holding_duration_s=1.0,
            ext=ExtensometerSettings(enabled=True, ext_type="PULSE"),
        )
        sim = VirtualUTMSimulator()
        sim.connect()
        points, state = [], {}
        sim.on_data_received = points.append
        sim.on_test_completed = lambda r: state.setdefault("reason", r)
        sim.start_test(specimen, config)
        deadline = time.time() + 60
        while "reason" not in state and time.time() < deadline:
            time.sleep(0.05)
        sim.stop_test()

        result = MaterialCalculator.calculate(specimen, config, points, state.get("reason", ""))
        self.assertTrue(result.ext_enabled)
        self.assertEqual(result.strain_source, "Extensometer (Pulse)")
        self.assertGreaterEqual(result.creep_deflection_mm, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
