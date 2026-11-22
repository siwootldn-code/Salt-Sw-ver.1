"""
Salt Sw ver.1 - 소프트 PID 하중·응력 속도 제어 검증
- PID 프로필 저장/불러오기, 강성 피드포워드 추정
- SoftPIDController 단위 거동 (포화 · Anti-Windup · 속도 변화율 제한 · 하중 유지)
- 20~50 Hz 통신 지연 조건의 3종 재질(고무 · 필름 · 금속) 시뮬레이션 통합 검증
- 화면(제어 방식 · PID 모드 · 게인 저장) 연동

실행: python3 -m unittest discover -s tests -v
"""

import json
import os
import random
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from core.models import Specimen, SpecimenType, TestConfig, TestMode
from core.pid_controller import (
    ControlMode, DEFAULT_PROFILES, PIDProfile, PIDProfileManager, SoftPIDController,
    StiffnessFeedForward, TrackingSample, build_controller, estimate_stiffness,
    evaluate_tracking, material_modulus_mpa,
)
from core.simulator import VirtualUTMSimulator, resolve_material_profile


def flat_specimen(material: str, width: float, thickness: float, gauge: float = 50.0) -> Specimen:
    return Specimen(specimen_id="PID-SP", material=material, specimen_type=SpecimenType.FLAT,
                    width_mm=width, thickness_mm=thickness, gauge_length_mm=gauge)


class FirstOrderPlant:
    """검증용 단순 플랜트: 속도 명령 -> 변위 -> 하중 (1차 지연)"""

    def __init__(self, stiffness_n_per_mm: float, tau_s: float = 0.0):
        self.k = stiffness_n_per_mm
        self.tau = tau_s
        self.v_mm_s = 0.0
        self.disp_mm = 0.0
        self.load_n = 0.0

    def step(self, speed_mm_min: float, dt: float):
        target = speed_mm_min / 60.0
        if self.tau > 0:
            self.v_mm_s += (target - self.v_mm_s) * min(1.0, dt / self.tau)
        else:
            self.v_mm_s = target
        self.disp_mm += self.v_mm_s * dt
        self.load_n = self.k * self.disp_mm
        return self.load_n, self.disp_mm


class TestPIDProfile(unittest.TestCase):
    def test_default_presets(self):
        ids = [DEFAULT_PROFILES[key].id for key in ("elastomer", "film", "metal")]
        self.assertEqual(ids, ["elastomer", "film", "metal"])
        # 금속은 가장 느린 상한과 가장 낮은 최소 속도를 가진다 (고강성 시편)
        metal = DEFAULT_PROFILES["metal"]
        elastomer = DEFAULT_PROFILES["elastomer"]
        self.assertLess(metal.max_speed_mm_min, elastomer.max_speed_mm_min)
        self.assertLess(metal.min_speed_mm_min, elastomer.min_speed_mm_min)
        for profile in DEFAULT_PROFILES.values():
            self.assertIn("PID", profile.name_ko)
            self.assertTrue(profile.name_en)

    def test_clamp_speed(self):
        profile = PIDProfile("t", "테스트", "Test", kp=1.0, ki=0.0, kd=0.0,
                             max_speed_mm_min=10.0, min_speed_mm_min=1.0)
        self.assertEqual(profile.clamp_speed(20.0), 10.0)
        self.assertEqual(profile.clamp_speed(-20.0), -10.0)
        self.assertEqual(profile.clamp_speed(0.5), 0.0)   # 최소 속도 미만은 정지
        self.assertEqual(profile.clamp_speed(3.0), 3.0)

    def test_dict_roundtrip(self):
        profile = DEFAULT_PROFILES["film"].copy()
        restored = PIDProfile.from_dict(profile.to_dict(), DEFAULT_PROFILES["metal"])
        self.assertEqual(restored.to_dict(), profile.to_dict())
        # 깨진 입력은 기본값으로 대체
        broken = PIDProfile.from_dict({"kp": "abc", "max_speed_mm_min": -5}, DEFAULT_PROFILES["film"])
        self.assertEqual(broken.kp, DEFAULT_PROFILES["film"].kp)
        self.assertGreater(broken.max_speed_mm_min, 0)


class TestPIDProfileManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "pid_profiles.json")
        self.mgr = PIDProfileManager(self.path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_defaults_without_file(self):
        self.assertEqual(len(self.mgr.list()), 3)
        self.assertFalse(os.path.exists(self.path))
        self.assertTrue(self.mgr.is_default("metal"))

    def test_save_and_reload(self):
        self.mgr.update("metal", kp=2.25, ki=1.5, kd=0.11)
        self.assertTrue(os.path.exists(self.path))
        reloaded = PIDProfileManager(self.path)
        profile = reloaded.get("metal")
        self.assertAlmostEqual(profile.kp, 2.25)
        self.assertAlmostEqual(profile.ki, 1.5)
        self.assertAlmostEqual(profile.kd, 0.11)
        self.assertFalse(reloaded.is_default("metal"))
        # 다른 프리셋은 그대로 유지
        self.assertTrue(reloaded.is_default("film"))

    def test_reset_defaults(self):
        self.mgr.update("elastomer", kp=9.0)
        self.mgr.reset_defaults()
        self.assertAlmostEqual(self.mgr.get("elastomer").kp, DEFAULT_PROFILES["elastomer"].kp)
        self.assertTrue(self.mgr.is_default("elastomer"))

    def test_corrupt_file_falls_back(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ broken json")
        mgr = PIDProfileManager(self.path)
        self.assertAlmostEqual(mgr.get("metal").kp, DEFAULT_PROFILES["metal"].kp)

    def test_unknown_profile_id(self):
        profile = self.mgr.get("unknown")
        self.assertEqual(profile.id, "metal")

    def test_unknown_keys_ignored(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"profiles": {"metal": {"kp": 1.1, "weird_key": 5}}}, f)
        mgr = PIDProfileManager(self.path)
        self.assertAlmostEqual(mgr.get("metal").kp, 1.1)
        self.assertEqual(mgr.get("metal").max_speed_mm_min, DEFAULT_PROFILES["metal"].max_speed_mm_min)


class TestStiffnessFeedForward(unittest.TestCase):
    def test_prior_used_before_measurement(self):
        ff = StiffnessFeedForward(prior_n_per_mm=150.0)
        self.assertAlmostEqual(ff.stiffness, 150.0)
        self.assertEqual(ff.source, "prior")
        # 150 N/mm 에서 60 N/s -> 0.4 mm/s = 24 mm/min
        self.assertAlmostEqual(ff.speed_mm_min_for(60.0), 24.0, places=6)

    def test_measurement_overrides_prior(self):
        ff = StiffnessFeedForward(prior_n_per_mm=10.0)
        # 실제 강성 200 N/mm 로 하중이 오르는 표본
        for i in range(60):
            disp = i * 0.001          # 0.001 mm 씩
            ff.update(disp * 200.0, disp)
        self.assertEqual(ff.source, "measure")
        self.assertAlmostEqual(ff.stiffness, 200.0, delta=2.0)

    def test_no_estimate_without_load_change(self):
        ff = StiffnessFeedForward()
        for i in range(40):
            ff.update(0.0, i * 0.001)
        self.assertEqual(ff.source, "none")
        self.assertEqual(ff.speed_mm_min_for(10.0), 0.0)

    def test_estimate_from_modulus(self):
        self.assertAlmostEqual(estimate_stiffness(205000.0, 40.0, 50.0), 164000.0)
        self.assertEqual(estimate_stiffness(0.0, 40.0, 50.0), 0.0)

    def test_material_modulus_longest_match(self):
        # 'PET' 를 'PE' 로 잘못 읽지 않는다
        self.assertAlmostEqual(material_modulus_mpa("PET 필름"), 3000.0)
        self.assertAlmostEqual(material_modulus_mpa("PE 필름"), 900.0)
        self.assertAlmostEqual(material_modulus_mpa("SS400"), 205000.0)
        self.assertAlmostEqual(material_modulus_mpa("NBR 고무"), 5.0)


class TestSoftPIDController(unittest.TestCase):
    def make_controller(self, stiffness_prior=100.0, rate=50.0, target=0.0,
                         profile=None, **kwargs):
        profile = profile or PIDProfile("test", "테스트", "Test", kp=1.5, ki=1.5, kd=0.04,
                                        max_speed_mm_min=500.0, min_speed_mm_min=0.01)
        return SoftPIDController(profile=profile, mode=ControlMode.LOAD_RATE
                                 if target <= 0 else ControlMode.LOAD_HOLD,
                                 target_rate_n_s=rate, target_load_n=target,
                                 stiffness_prior_n_per_mm=stiffness_prior, **kwargs)

    def test_feedforward_tracks_rate(self):
        ctrl = self.make_controller(stiffness_prior=100.0, rate=50.0)
        plant = FirstOrderPlant(100.0, tau_s=0.0)
        dt = 0.04
        for _ in range(50):   # 2초
            speed = ctrl.update(dt, plant.load_n, plant.disp_mm)
            plant.step(speed, dt)
        # 50 N/s * 2 s = 100 N 근처 (피드포워드가 거의 맞춘다)
        self.assertAlmostEqual(plant.load_n, 100.0, delta=8.0)

    def test_output_within_profile_limits(self):
        profile = PIDProfile("test", "테스트", "Test", kp=8.0, ki=0.0, kd=0.0,
                             max_speed_mm_min=5.0, min_speed_mm_min=0.0)
        ctrl = SoftPIDController(profile=profile, mode=ControlMode.LOAD_RATE,
                                 target_rate_n_s=1000.0, stiffness_prior_n_per_mm=100.0)
        plant = FirstOrderPlant(100.0)
        for _ in range(100):
            speed = ctrl.update(0.04, plant.load_n, plant.disp_mm)
            self.assertLessEqual(abs(speed), 5.0 + 1e-9)
            plant.step(speed, 0.04)

    def test_slew_rate_limits_change(self):
        profile = DEFAULT_PROFILES["metal"]
        ctrl = SoftPIDController(profile=profile, mode=ControlMode.LOAD_RATE,
                                 target_rate_n_s=500.0, stiffness_prior_n_per_mm=100000.0)
        plant = FirstOrderPlant(100000.0)
        prev = 0.0
        max_step = ctrl.slew_mm_min_per_s * 0.04
        for i in range(30):
            speed = ctrl.update(0.04, plant.load_n, plant.disp_mm)
            if i > 0:
                self.assertLessEqual(abs(speed - prev), max_step + 1e-6)
            prev = speed
            plant.step(speed, 0.04)

    def test_anti_windup_caps_integral(self):
        profile = PIDProfile("test", "테스트", "Test", kp=0.0, ki=5.0, kd=0.0,
                             max_speed_mm_min=1.0, min_speed_mm_min=0.0,
                             anti_windup_limit=0.2)
        ctrl = SoftPIDController(profile=profile, mode=ControlMode.LOAD_HOLD,
                                 target_rate_n_s=50.0, target_load_n=1000.0,
                                 stiffness_prior_n_per_mm=100.0)
        plant = FirstOrderPlant(100.0)
        for _ in range(200):
            speed = ctrl.update(0.04, plant.load_n, plant.disp_mm)
            plant.step(speed, 0.04)
        cap = profile.anti_windup_limit * profile.max_speed_mm_min / 60.0
        self.assertLessEqual(abs(ctrl.integral * profile.ki), cap + 1e-9)

    def test_hold_reaches_target_without_large_overshoot(self):
        ctrl = self.make_controller(stiffness_prior=200.0, rate=100.0, target=150.0,
                                    hold_duration_s=4.0)
        plant = FirstOrderPlant(200.0, tau_s=0.05)
        dt = 0.04
        peak = 0.0
        for _ in range(300):   # 12초
            speed = ctrl.update(dt, plant.load_n, plant.disp_mm)
            plant.step(speed, dt)
            peak = max(peak, plant.load_n)
            if ctrl.is_finished:
                break
        self.assertAlmostEqual(plant.load_n, 150.0, delta=4.0)
        self.assertLess((peak - 150.0) / 150.0 * 100.0, 6.0)
        self.assertTrue(ctrl.is_finished)

    def test_status_fields(self):
        ctrl = self.make_controller(stiffness_prior=100.0, rate=50.0)
        plant = FirstOrderPlant(100.0)
        for _ in range(10):
            speed = ctrl.update(0.04, plant.load_n, plant.disp_mm)
            plant.step(speed, 0.04)
        status = ctrl.status()
        self.assertGreater(status.setpoint_load_n, 0.0)
        self.assertGreater(status.stiffness_n_per_mm, 0.0)
        self.assertIn("강성", ctrl.status_text("KO"))
        self.assertIn("Stiffness", ctrl.status_text("EN"))


class TestBuildController(unittest.TestCase):
    def test_disp_mode_has_no_controller(self):
        config = TestConfig(mode=TestMode.TENSILE)
        controller = build_controller(config, flat_specimen("SS400", 12.5, 3.2))
        self.assertIsNone(controller)

    def test_load_rate_conversion(self):
        config = TestConfig(mode=TestMode.TENSILE, control_mode="LOAD_RATE",
                            target_rate=6000.0)   # N/min
        controller = build_controller(config, flat_specimen("SS400", 12.5, 3.2))
        self.assertIsNotNone(controller)
        self.assertAlmostEqual(controller.target_rate_n_s, 100.0)

    def test_stress_rate_conversion_uses_area(self):
        specimen = flat_specimen("SS400", 12.5, 3.2)     # 40 mm²
        config = TestConfig(mode=TestMode.TENSILE, control_mode="STRESS_RATE",
                            target_rate=2.5)            # MPa/s
        controller = build_controller(config, specimen)
        self.assertAlmostEqual(controller.target_rate_n_s, 2.5 * 40.0)

    def test_hold_mode_uses_target_load(self):
        config = TestConfig(mode=TestMode.HOLDING, control_mode="LOAD_HOLD",
                            target_rate=1800.0, target_holding_val=120.0,
                            holding_duration_s=5.0, pid_profile_id="elastomer")
        controller = build_controller(config, flat_specimen("NBR", 12.5, 3.2))
        self.assertAlmostEqual(controller.target_load_n, 120.0)
        self.assertAlmostEqual(controller.hold_duration_s, 5.0)
        self.assertEqual(controller.profile.id, "elastomer")
        # 초기 강성 추정치가 재질에서 계산된다 (NBR 5 MPa · 40 mm² / 50 mm = 4 N/mm)
        self.assertAlmostEqual(controller.stiffness_n_per_mm, 4.0)

    def test_gain_override(self):
        config = TestConfig(mode=TestMode.TENSILE, control_mode="LOAD_RATE",
                            target_rate=1000.0, pid_gains={"kp": 3.3, "ki": 0.7})
        controller = build_controller(config, flat_specimen("SS400", 12.5, 3.2))
        self.assertAlmostEqual(controller.profile.kp, 3.3)
        self.assertAlmostEqual(controller.profile.ki, 0.7)


class TestEvaluateTracking(unittest.TestCase):
    def test_known_overshoot_and_errors(self):
        samples = []
        for i in range(25):        # 0~1초: 100 N/s 로 0 -> 100 N
            t = i * 0.04
            samples.append(TrackingSample(time_s=t, setpoint_n=min(100.0, t * 100.0),
                                          load_n=min(100.0, t * 100.0)))
        for i in range(1, 26):     # 1~2초: 목표 100 N 유지, 110 N 까지 오버슈트
            t = 1.0 + i * 0.04
            samples.append(TrackingSample(time_s=t, setpoint_n=100.0,
                                          load_n=110.0 if i <= 5 else 100.0))
        metrics = evaluate_tracking(samples, target_rate_n_s=100.0, target_load_n=100.0)
        self.assertAlmostEqual(metrics["overshoot_pct"], 10.0, delta=0.2)
        self.assertLess(metrics["follow_error_pct"], 1.0)
        self.assertGreaterEqual(metrics["settle_s"], 0.0)

    def test_empty_samples(self):
        metrics = evaluate_tracking([], target_rate_n_s=10.0, target_load_n=5.0)
        self.assertEqual(metrics["overshoot_pct"], 0.0)


class TestControlledSimulation(unittest.TestCase):
    """20~50 Hz 통신 지연에서의 재질별 하중 속도 · 하중 유지 시뮬레이션"""

    CASES = [
        # 재질, 폭, 두께, 목표 하중 속도(N/min), 목표 하중(N), PID 모드
        ("NBR", 12.5, 3.2, 1800.0, 120.0, "elastomer"),
        ("PET", 20.0, 0.1, 4800.0, 100.0, "film"),
        ("SS400", 12.5, 3.2, 96000.0, 2000.0, "metal"),
    ]

    def run_case(self, case, live=True, delay_ms=40.0, hz=25.0, time_scale=10.0, seed=5):
        material, width, thick, rate, target, profile = case
        random.seed(seed)
        specimen = flat_specimen(material, width, thick)
        config = TestConfig(
            mode=TestMode.HOLDING, control_mode="LOAD_HOLD", target_rate=rate,
            target_holding_val=target, holding_duration_s=3.0, pid_profile_id=profile,
            comm_delay_ms=delay_ms, control_rate_hz=hz, live_speed_control=live,
            sampling_rate_hz=200, max_displacement_mm=60.0,
        )
        sim = VirtualUTMSimulator()
        sim.time_scale = time_scale
        sim.connect()
        state = {}
        points = []
        sim.on_data_received = points.append
        sim.on_test_completed = lambda reason: state.setdefault("reason", reason)
        sim.start_test(specimen, config)
        deadline = time.time() + 30.0
        while "reason" not in state and time.time() < deadline:
            time.sleep(0.01)
        sim.stop_test()
        metrics = evaluate_tracking(list(sim.control_trace),
                                    target_rate_n_s=rate / 60.0, target_load_n=target)
        return state.get("reason", ""), metrics, sim, points

    def test_all_materials_reach_target(self):
        for case in self.CASES:
            reason, metrics, sim, points = self.run_case(case)
            self.assertIn("목표 하중 유지 완료", reason, f"{case[0]} 종료 사유: {reason}")
            self.assertGreater(len(points), 100)
            self.assertEqual(sim.controller.ff.source, "measure")
            self.assertAlmostEqual(metrics["peak_load_n"], case[4], delta=case[4] * 0.08)
            self.assertLess(metrics["hold_error_pct"], 3.0)
            self.assertLess(metrics["follow_error_pct"], 8.0)

    def test_overshoot_better_than_fixed_speed(self):
        """실시간 보정(Soft-PID)이 고정 속도(폐쇄 없음)보다 오버슈트가 작다"""
        for case in self.CASES:
            _, pid_metrics, _, _ = self.run_case(case, live=True)
            _, fixed_metrics, _, _ = self.run_case(case, live=False)
            self.assertLess(pid_metrics["overshoot_pct"], fixed_metrics["overshoot_pct"],
                            f"{case[0]}: PID {pid_metrics['overshoot_pct']:.2f}% vs "
                            f"고정 {fixed_metrics['overshoot_pct']:.2f}%")
            self.assertLess(pid_metrics["overshoot_pct"], 6.0)

    def test_stable_at_20hz_50ms_and_50hz_20ms(self):
        for case in self.CASES:
            reason, metrics, _, _ = self.run_case(case, delay_ms=50.0, hz=20.0)
            self.assertIn("목표 하중 유지 완료", reason, f"{case[0]} 20Hz/50ms: {reason}")
            self.assertLess(metrics["overshoot_pct"], 8.0)
            reason, metrics, _, _ = self.run_case(case, delay_ms=20.0, hz=50.0)
            self.assertIn("목표 하중 유지 완료", reason, f"{case[0]} 50Hz/20ms: {reason}")
            self.assertLess(metrics["overshoot_pct"], 8.0)

    def test_stress_rate_control_runs(self):
        random.seed(3)
        specimen = flat_specimen("SS400", 12.5, 3.2)
        config = TestConfig(mode=TestMode.TENSILE, control_mode="STRESS_RATE",
                            target_rate=10.0, pid_profile_id="metal",
                            comm_delay_ms=35.0, control_rate_hz=25.0,
                            sampling_rate_hz=200, max_displacement_mm=5.0)
        sim = VirtualUTMSimulator()
        sim.time_scale = 10.0
        sim.connect()
        state = {}
        sim.on_test_completed = lambda reason: state.setdefault("reason", reason)
        sim.start_test(specimen, config)
        deadline = time.time() + 20.0
        while "reason" not in state and time.time() < deadline:
            time.sleep(0.01)
        sim.stop_test()
        self.assertTrue(state)
        trace = list(sim.control_trace)
        self.assertGreater(len(trace), 20)
        # 10 MPa/s = 400 N/s (40 mm²)
        self.assertAlmostEqual(sim.controller.target_rate_n_s, 400.0)
        self.assertGreater(trace[-1].load_n, 100.0)

    def test_live_speed_change_in_displacement_mode(self):
        """변위 속도 제어 중 set_speed() 가 다음 스텝부터 반영된다"""
        random.seed(7)
        specimen = flat_specimen("SS400", 12.5, 3.2)
        config = TestConfig(mode=TestMode.TENSILE, test_speed_mm_min=30.0,
                            sampling_rate_hz=100, max_displacement_mm=60.0)
        sim = VirtualUTMSimulator()
        sim.time_scale = 20.0
        sim.connect()
        points = []
        state = {}
        sim.on_data_received = points.append
        sim.on_test_completed = lambda reason: state.setdefault("reason", reason)
        sim.start_test(specimen, config)
        deadline = time.time() + 10.0
        while len(points) < 60 and time.time() < deadline:      # 0.6초 진행
            time.sleep(0.005)
        sim.set_speed(90.0)      # 3배로 변경
        while len(points) < 160 and time.time() < deadline:     # 1.6초까지
            time.sleep(0.005)
        sim.stop_test()

        early = [p for p in points if 0.2 <= p.time_s <= 0.55]
        late = [p for p in points if 0.8 <= p.time_s <= 1.5]
        self.assertTrue(early and late)
        rate_early = (early[-1].displacement_mm - early[0].displacement_mm) / \
                     (early[-1].time_s - early[0].time_s)
        rate_late = (late[-1].displacement_mm - late[0].displacement_mm) / \
                    (late[-1].time_s - late[0].time_s)
        self.assertAlmostEqual(rate_early, 0.5, delta=0.05)     # 30 mm/min = 0.5 mm/s
        self.assertAlmostEqual(rate_late, 1.5, delta=0.10)      # 90 mm/min = 1.5 mm/s

    def test_bending_ignores_pid_control(self):
        random.seed(1)
        specimen = flat_specimen("SS400", 12.5, 3.2)
        config = TestConfig(mode=TestMode.BENDING, control_mode="LOAD_RATE",
                            target_rate=1000.0, test_speed_mm_min=60.0,
                            sampling_rate_hz=60, max_displacement_mm=6.0)
        sim = VirtualUTMSimulator()
        sim.time_scale = 20.0
        sim.connect()
        state = {}
        sim.on_test_completed = lambda reason: state.setdefault("reason", reason)
        sim.start_test(specimen, config)
        deadline = time.time() + 15.0
        while "reason" not in state and time.time() < deadline:
            time.sleep(0.01)
        sim.stop_test()
        self.assertIsNone(sim.controller)
        self.assertEqual(sim.control_trace, [])


class TestControllerWithoutDisplacementChannel(unittest.TestCase):
    """변위 채널이 없는 단일 하중 스트림에서는 실측 강성 대신 초기 추정값을 쓴다"""

    def test_prior_kept_when_displacement_invalid(self):
        ctrl = SoftPIDController(profile=DEFAULT_PROFILES["metal"], mode=ControlMode.LOAD_RATE,
                                 target_rate_n_s=100.0, stiffness_prior_n_per_mm=160000.0)
        plant = FirstOrderPlant(160000.0)
        for i in range(40):
            # 변위 신호가 없으므로 disp 는 신뢰할 수 없는 값이라고 알린다
            speed = ctrl.update(0.04, plant.load_n, float(i), disp_valid=False)
            plant.step(speed, 0.04)
        self.assertEqual(ctrl.ff.source, "prior")
        self.assertAlmostEqual(ctrl.stiffness_n_per_mm, 160000.0)


class TestSerialDriverControl(unittest.TestCase):
    """실장비 드라이버의 고정 속도 폴백 · 실시간 속도 명령 동작 (시리얼 없이 검증)"""

    def make_driver(self, live: bool, mode: str = "LOAD_RATE"):
        from core.serial_driver import SerialUTMDriver
        driver = SerialUTMDriver()
        driver.supports_live_speed_control = live
        sent = []
        driver.send_command = lambda cmd: sent.append(cmd.strip())   # 실제 전송 대체
        specimen = flat_specimen("SS400", 12.5, 3.2)
        config = TestConfig(mode=TestMode.TENSILE, control_mode=mode, target_rate=6000.0,
                            comm_delay_ms=40.0, control_rate_hz=25.0, pid_profile_id="metal")
        driver.specimen = specimen
        driver.config = config
        driver.is_running = True
        driver.start_time = 0.0
        driver.set_extensometer(config.ext)
        driver.controller = build_controller(config, specimen, driver.pid_manager)
        driver.control_trace = []
        return driver, sent

    def feed(self, driver, seconds: float, load_rate_n_s: float, k: float, dt: float = 0.01):
        """하중이 일정 속도로 오르는 패킷을 공급"""
        t = 0.0
        while t < seconds:
            t += dt
            driver._ctrl_last_t = 0.0
            load = load_rate_n_s * t
            dp = _make_point(t, load, load / k)
            driver._control_tick(dp)

    def test_fixed_speed_fallback_sends_single_spd(self):
        driver, sent = self.make_driver(live=False)
        self.feed(driver, 1.0, load_rate_n_s=100.0, k=164000.0)
        spd = [c for c in sent if c.startswith("SPD")]
        self.assertEqual(len(spd), 1, f"전송 명령: {sent}")
        self.assertIn("RUN", sent)
        # 초기 강성(164,000 N/mm)으로 환산한 속도: 100 N/s -> 0.0366 mm/min
        self.assertAlmostEqual(float(spd[0].split()[1]), 0.0366, delta=0.0002)

    def test_live_mode_updates_speed(self):
        driver, sent = self.make_driver(live=True)
        self.feed(driver, 1.0, load_rate_n_s=100.0, k=164000.0)
        spd = [c for c in sent if c.startswith("SPD")]
        self.assertGreater(len(spd), 3, f"전송 명령: {sent}")
        self.assertTrue(driver.control_trace)

    def test_sequence_tick_does_not_crash(self):
        from core.sequence import SequenceProgram
        driver, sent = self.make_driver(live=False)
        driver.config = TestConfig(mode=TestMode.SEQUENCE, sequence=SequenceProgram.standard())
        driver.sequence_ctl = None
        self.assertIsNone(driver._sequence_tick(_make_point(0.1, 10.0, 0.01)))


def _make_point(t: float, load: float, disp: float):
    from core.models import DataPoint
    return DataPoint(time_s=t, displacement_mm=disp, load_n=load,
                     stress_mpa=load / 40.0, strain_pct=disp / 50.0 * 100.0)


class TestHistoryControlFields(unittest.TestCase):
    """시험 이력에 제어 방식·PID 설정이 함께 저장되는지"""

    def test_config_roundtrip(self):
        from core.history import config_from_dict, config_to_dict
        config = TestConfig(
            mode=TestMode.HOLDING, control_mode="LOAD_HOLD", target_rate=1800.0,
            target_load_n=120.0, pid_profile_id="elastomer",
            pid_gains={"kp": 1.7, "ki": 2.1, "kd": 0.02},
            comm_delay_ms=45.0, control_rate_hz=20.0, live_speed_control=False,
        )
        restored = config_from_dict(config_to_dict(config))
        self.assertEqual(restored.control_mode, "LOAD_HOLD")
        self.assertAlmostEqual(restored.target_rate, 1800.0)
        self.assertAlmostEqual(restored.target_load_n, 120.0)
        self.assertEqual(restored.pid_profile_id, "elastomer")
        self.assertAlmostEqual(restored.pid_gains["kp"], 1.7)
        self.assertAlmostEqual(restored.comm_delay_ms, 45.0)
        self.assertAlmostEqual(restored.control_rate_hz, 20.0)
        self.assertFalse(restored.live_speed_control)

    def test_old_record_without_control_fields(self):
        from core.history import config_from_dict
        restored = config_from_dict({"mode": "TENSILE", "test_speed_mm_min": 5.0})
        self.assertEqual(restored.control_mode, "DISP")
        self.assertFalse(restored.uses_pid_control)
        self.assertEqual(restored.pid_gains, {})


class TestControlUI(unittest.TestCase):
    """제어 방식 선택 · PID 게인 저장 화면 검증"""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        from ui.main_window import MainWindow
        self.tmpdir = tempfile.TemporaryDirectory()
        self.win = MainWindow()
        self.win.pid_manager.config_path = os.path.join(self.tmpdir.name, "pid_profiles.json")
        self.win.pid_manager.reset_defaults()
        self.win.simulator.pid_manager = self.win.pid_manager
        self.win.serial_driver.pid_manager = self.win.pid_manager

    def tearDown(self):
        self.win.close()
        self.tmpdir.cleanup()

    def test_pid_widgets_hidden_for_displacement_control(self):
        self.assertTrue(self.win.spin_kp.isHidden())
        self.win.combo_control_mode.setCurrentIndex(1)     # 하중 속도
        self.assertFalse(self.win.spin_kp.isHidden())
        self.assertTrue(self.win.spin_speed.isHidden())
        self.win.combo_control_mode.setCurrentIndex(0)     # 변위 속도
        self.assertTrue(self.win.spin_kp.isHidden())
        self.assertFalse(self.win.spin_speed.isHidden())

    def test_config_reflects_control_selection(self):
        self.win.combo_control_mode.setCurrentIndex(1)
        self.win.spin_target_rate.setValue(3000.0)
        self.win.combo_pid_mode.setCurrentIndex(self.win.combo_pid_mode.findData("film"))
        self.win.spin_ctl_delay.setValue(40.0)
        self.win.spin_ctl_hz.setValue(20.0)
        config = self.win._get_current_config()
        self.assertEqual(config.control_mode, "LOAD_RATE")
        self.assertAlmostEqual(config.target_rate, 3000.0)
        self.assertEqual(config.pid_profile_id, "film")
        self.assertAlmostEqual(config.comm_delay_ms, 40.0)
        self.assertAlmostEqual(config.control_rate_hz, 20.0)
        self.assertTrue(config.uses_pid_control)
        self.assertEqual(config.sampling_rate_hz, 200)

    def test_displacement_config_keeps_pid_off(self):
        config = self.win._get_current_config()
        self.assertEqual(config.control_mode, "DISP")
        self.assertFalse(config.uses_pid_control)

    def test_save_gains_writes_profile_file(self):
        self.win.combo_pid_mode.setCurrentIndex(self.win.combo_pid_mode.findData("metal"))
        self.win.spin_kp.setValue(2.25)
        self.win.spin_ki.setValue(1.15)
        self.win.spin_kd.setValue(0.09)
        self.win._save_pid_gains()
        with open(self.win.pid_manager.config_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertAlmostEqual(saved["profiles"]["metal"]["kp"], 2.25)
        self.assertAlmostEqual(saved["profiles"]["metal"]["ki"], 1.15)
        self.assertIn("저장", self.win.lbl_pid_state.text())

    def test_selecting_profile_loads_gains(self):
        index = self.win.combo_pid_mode.findData("elastomer")
        self.win.combo_pid_mode.setCurrentIndex(index)
        self.assertAlmostEqual(self.win.spin_kp.value(), DEFAULT_PROFILES["elastomer"].kp)
        self.assertAlmostEqual(self.win.spin_ki.value(), DEFAULT_PROFILES["elastomer"].ki)

    def test_bending_disables_pid_control(self):
        self.win.combo_control_mode.setCurrentIndex(1)
        self.win.rb_bending.setChecked(True)
        self.assertFalse(self.win.combo_control_mode.isEnabled())
        self.assertEqual(self.win.combo_control_mode.currentIndex(), 0)

    def test_hold_mode_switches_to_holding_test(self):
        self.win.rb_tensile.setChecked(True)
        self.win.combo_control_mode.setCurrentIndex(3)
        self.assertTrue(self.win.rb_holding.isChecked())
        config = self.win._get_current_config()
        self.assertEqual(config.control_mode, "LOAD_HOLD")
        self.assertAlmostEqual(config.target_load_n, self.win.spin_hold_val.value())


if __name__ == "__main__":
    unittest.main()
