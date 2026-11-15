"""
Salt Sw ver.1 - 다중 시편 오버레이 · 배치 통계 · 시험 이력 · 다단계 시퀀스 검증

실행: python3 -m unittest discover -s tests -v
"""

import json
import math
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from core.calculator import MaterialCalculator
from core.history import (
    HISTORY_SCHEMA, TestHistoryStore, compute_digest, points_to_list,
)
from core.models import (
    DataPoint, ExtensometerSettings, Specimen, SpecimenType, TestConfig, TestMode, TestResult,
)
from core.sequence import (
    SequenceController, SequenceProgram, SequenceStep, StepAction,
    format_sequence_command, SequenceCommand,
)
from core.session import (
    BATCH_METRICS, SpecimenSession, compute_stat, metric_value, OVERLAY_COLORS,
)
from core.simulator import VirtualUTMSimulator, resolve_material_profile


# ----------------------------------------------------------------------
# 공용 도우미
# ----------------------------------------------------------------------
def make_specimen(specimen_id: str = "TEST-SP-001", thickness: float = 3.2,
                  material: str = "SS400") -> Specimen:
    return Specimen(
        specimen_id=specimen_id,
        material=material,
        specimen_type=SpecimenType.FLAT,
        width_mm=12.5,
        thickness_mm=thickness,
        gauge_length_mm=50.0,
    )


def fake_points(count: int = 20) -> list:
    points = []
    for i in range(count):
        strain = i * 0.5
        stress = 200.0 * strain
        points.append(DataPoint(
            time_s=round(i * 0.05, 3),
            displacement_mm=round(i * 0.05, 4),
            load_n=200.0 * strain,
            stress_mpa=stress,
            strain_pct=strain,
        ))
    return points


def fake_result(peak_load=10000.0, peak_stress=400.0, yield_stress=250.0,
                modulus=200.0, elongation=25.0) -> TestResult:
    return TestResult(
        test_mode=TestMode.TENSILE,
        specimen_id="TEST-SP-001",
        material="SS400",
        area_mm2=40.0,
        gauge_length_mm=50.0,
        peak_load_n=peak_load,
        peak_stress_mpa=peak_stress,
        yield_stress_mpa=yield_stress,
        elastic_modulus_gpa=modulus,
        elongation_pct=elongation,
    )


def run_simulation(specimen=None, config=None, timeout: float = 90.0):
    """가상 시험 1회 수행 -> (points, result, reason, simulator)"""
    specimen = specimen or make_specimen()
    config = config or TestConfig(
        mode=TestMode.TENSILE, test_speed_mm_min=300.0,
        sampling_rate_hz=300, max_displacement_mm=40.0,
    )
    sim = VirtualUTMSimulator()
    sim.connect()
    points, state = [], {}
    sim.on_data_received = points.append
    sim.on_test_completed = lambda reason: state.setdefault("reason", reason)
    sim.start_test(specimen, config)
    deadline = time.time() + timeout
    while "reason" not in state and time.time() < deadline:
        time.sleep(0.02)
    sim.stop_test()
    result = MaterialCalculator.calculate(
        specimen, config, points, state.get("reason", ""), sequence_steps=sim.step_events
    )
    return points, result, state.get("reason", ""), sim


# ----------------------------------------------------------------------
# 1. 배치 통계
# ----------------------------------------------------------------------
class TestBatchStatistics(unittest.TestCase):
    def test_compute_stat_known_values(self):
        stat = compute_stat([10.0, 12.0, 14.0], "peak_load_n")
        self.assertEqual(stat.n, 3)
        self.assertAlmostEqual(stat.mean, 12.0)
        self.assertAlmostEqual(stat.std, 2.0)          # 표본표준편차(n-1)
        self.assertAlmostEqual(stat.cv_pct, 2.0 / 12.0 * 100.0, places=6)
        self.assertAlmostEqual(stat.minimum, 10.0)
        self.assertAlmostEqual(stat.maximum, 14.0)

    def test_single_value_has_zero_spread(self):
        stat = compute_stat([7.5], "peak_stress_mpa")
        self.assertEqual(stat.n, 1)
        self.assertAlmostEqual(stat.mean, 7.5)
        self.assertEqual(stat.std, 0.0)
        self.assertEqual(stat.cv_pct, 0.0)
        self.assertEqual(stat.formatted("mean"), "7.50")
        self.assertEqual(stat.formatted("n"), "1")

    def test_empty_values(self):
        stat = compute_stat([], "peak_load_n")
        self.assertFalse(stat.has_data)
        self.assertEqual(stat.formatted("mean"), "-")
        self.assertEqual(stat.formatted("n"), "0")

    def test_cv_guards_zero_mean(self):
        stat = compute_stat([0.0, 0.0], "elongation_pct")
        self.assertEqual(stat.cv_pct, 0.0)

    def test_session_statistics_over_visible_only(self):
        session = SpecimenSession()
        for i, load in enumerate((100.0, 200.0, 300.0)):
            session.add(make_specimen(f"SP-{i + 1}"), TestConfig(), fake_result(peak_load=load))
        stat = session.statistics_for("peak_load_n")
        self.assertEqual(stat.n, 3)
        self.assertAlmostEqual(stat.mean, 200.0)

        session.set_visible(2, False)          # SP-002(200 N) 숨김
        stat = session.statistics_for("peak_load_n")
        self.assertEqual(stat.n, 2)
        self.assertAlmostEqual(stat.mean, 200.0)
        self.assertAlmostEqual(stat.maximum, 300.0)
        self.assertAlmostEqual(stat.minimum, 100.0)

        session.set_all_visible(False)
        stat = session.statistics_for("peak_load_n")
        self.assertFalse(stat.has_data)

    def test_all_metrics_present(self):
        session = SpecimenSession()
        session.add(make_specimen(), TestConfig(), fake_result())
        stats = session.statistics()
        self.assertEqual(len(stats), len(BATCH_METRICS))
        self.assertEqual([s.key for s in stats], [key for key, _u, _d in BATCH_METRICS])
        for stat in stats:
            self.assertTrue(stat.has_data)
            self.assertGreater(stat.mean, 0)

    def test_metric_value_handles_missing(self):
        self.assertIsNone(metric_value(None, "peak_load_n"))
        self.assertIsNone(metric_value(fake_result(), "does_not_exist"))


# ----------------------------------------------------------------------
# 2. 세션 / 오버레이
# ----------------------------------------------------------------------
class TestSpecimenSession(unittest.TestCase):
    def test_sequence_labels_and_distinct_colors(self):
        session = SpecimenSession()
        records = [session.add(make_specimen(f"S{i}"), TestConfig(), fake_result()) for i in range(4)]
        self.assertEqual([r.session_label for r in records], ["SP-001", "SP-002", "SP-003", "SP-004"])
        colors = [r.color for r in records]
        self.assertEqual(len(set(colors)), 4)
        self.assertTrue(all(c in OVERLAY_COLORS for c in colors))

    def test_color_cycles_after_palette_size(self):
        session = SpecimenSession()
        records = [session.add(make_specimen(f"S{i}"), TestConfig(), fake_result())
                   for i in range(len(OVERLAY_COLORS) + 1)]
        self.assertEqual(records[-1].color, records[0].color)
        self.assertEqual(records[-1].seq, len(OVERLAY_COLORS) + 1)

    def test_remove_and_clear(self):
        session = SpecimenSession()
        session.add(make_specimen("A"), TestConfig(), fake_result())
        session.add(make_specimen("B"), TestConfig(), fake_result())
        self.assertTrue(session.remove(1))
        self.assertFalse(session.remove(99))
        self.assertEqual(len(session), 1)
        self.assertEqual(session.records[0].seq, 2)
        session.clear()
        self.assertEqual(len(session), 0)

    def test_curve_coordinates(self):
        session = SpecimenSession()
        points = fake_points(5)
        record = session.add(make_specimen(), TestConfig(), fake_result(), points)
        xs, ys = record.curve("ss")
        self.assertEqual(len(xs), 5)
        self.assertAlmostEqual(xs[1], 0.5)
        self.assertAlmostEqual(ys[1], 100.0)
        xs_ld, ys_ld = record.curve("ld")
        self.assertAlmostEqual(xs_ld[1], 0.05)
        self.assertAlmostEqual(ys_ld[1], 100.0)

    def test_return_step_excluded_from_overlay_curve(self):
        """시퀀스 복귀 구간은 재료 응답이 아니므로 곡선에서 제외된다"""
        session = SpecimenSession()
        points = fake_points(10)   # t = 0 .. 0.45
        step_events = [
            {"index": 0, "action": "RAMP_TO_BREAK", "started_at": 0.0, "ended_at": 0.2},
            {"index": 1, "action": "RETURN", "started_at": 0.2, "ended_at": 0.45},
        ]
        record = session.add(make_specimen(), TestConfig(), fake_result(), points,
                             step_events=step_events)
        self.assertEqual(len(record.points), 10)
        self.assertEqual(len(record.curve_points()), 4)   # t <= 0.2 인 점만
        self.assertTrue(all(p.time_s <= 0.2 for p in record.curve_points()))

    def test_has_history_record(self):
        session = SpecimenSession()
        session.add(make_specimen(), TestConfig(), fake_result(), history_id="rec-1")
        self.assertTrue(session.has_history_record("rec-1"))
        self.assertFalse(session.has_history_record("rec-2"))

    def test_summary_rows(self):
        session = SpecimenSession()
        session.add(make_specimen("X"), TestConfig(), fake_result(), fake_points(3))
        rows = session.summary_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["session_label"], "SP-001")
        self.assertEqual(rows[0]["specimen_id"], "X")
        self.assertEqual(rows[0]["samples"], 3)


# ----------------------------------------------------------------------
# 3. 시험 이력 / 무결성
# ----------------------------------------------------------------------
class TestTestHistory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = TestHistoryStore(os.path.join(self.tmpdir.name, "history"))
        self.specimen = make_specimen()
        self.config = TestConfig(mode=TestMode.TENSILE, test_speed_mm_min=5.0)
        self.points = fake_points(12)
        self.result = fake_result()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _save(self, offset_seconds: int = 0, specimen_id: str = "TEST-SP-001"):
        return self.store.save(
            make_specimen(specimen_id), self.config, self.result, self.points,
            completion_reason="시편 파단",
            created_at=datetime(2026, 11, 15, 13, 0, 0) + timedelta(seconds=offset_seconds),
        )

    def test_save_creates_json_with_digest(self):
        summary = self._save()
        self.assertIsNotNone(summary)
        self.assertTrue(os.path.exists(summary.path))
        with open(summary.path, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["schema"], HISTORY_SCHEMA)
        self.assertEqual(len(doc["integrity"]["digest"]), 64)
        self.assertEqual(doc["integrity"]["algorithm"], "sha256")
        self.assertEqual(doc["integrity"]["digest"], compute_digest(doc["payload"]))
        self.assertEqual(doc["payload"]["point_count"], len(self.points))
        self.assertEqual(len(doc["payload"]["points"]), len(self.points))
        meta = doc["meta"]
        self.assertEqual(meta["specimen_id"], "TEST-SP-001")
        self.assertAlmostEqual(meta["peak_load_n"], self.result.peak_load_n)

    def test_load_round_trip(self):
        summary = self._save()
        record = self.store.load(summary.record_id)
        self.assertIsNotNone(record)
        self.assertTrue(record.integrity.ok)
        self.assertEqual(record.specimen.specimen_id, "TEST-SP-001")
        self.assertEqual(len(record.points), len(self.points))
        self.assertAlmostEqual(record.result.peak_load_n, self.result.peak_load_n)
        self.assertAlmostEqual(record.points[3].displacement_mm, self.points[3].displacement_mm, places=4)
        self.assertEqual(record.result.test_mode, TestMode.TENSILE)
        self.assertEqual(record.summary.completion_reason, "시편 파단")

    def test_load_unknown_returns_none(self):
        self.assertIsNone(self.store.load("nope"))

    def test_tampering_is_detected(self):
        summary = self._save()
        self.assertTrue(self.store.verify(summary.record_id).ok)

        with open(summary.path, encoding="utf-8") as f:
            doc = json.load(f)
        doc["payload"]["result"]["peak_load_n"] = 99999.9      # 값 위조
        with open(summary.path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

        result = self.store.verify(summary.record_id)
        self.assertFalse(result.ok)
        self.assertIn("변경", result.note)
        self.assertFalse(self.store.load(summary.record_id).integrity.ok)

    def test_tampering_raw_points_is_detected(self):
        summary = self._save()
        with open(summary.path, encoding="utf-8") as f:
            doc = json.load(f)
        doc["payload"]["points"][2][2] = 12345.6
        with open(summary.path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        self.assertFalse(self.store.verify(summary.record_id).ok)

    def test_chain_links_records(self):
        first = self._save(0, "SP-A")
        second = self._save(1, "SP-B")
        third = self._save(2, "SP-C")
        self.assertEqual(first.prev_digest, "")
        self.assertEqual(second.prev_digest, first.digest)
        self.assertEqual(third.prev_digest, second.digest)

        chain = self.store.verify_chain()
        self.assertTrue(chain.ok)
        self.assertEqual(chain.total, 3)
        self.assertEqual(chain.ok_count, 3)

    def test_chain_breaks_when_earlier_record_modified(self):
        first = self._save(0, "SP-A")
        second = self._save(1, "SP-B")
        with open(first.path, encoding="utf-8") as f:
            doc = json.load(f)
        doc["payload"]["specimen"]["material"] = "OTHER"
        with open(first.path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)

        chain = self.store.verify_chain()
        self.assertFalse(chain.ok)
        joined = " ".join(chain.problems)
        self.assertIn(first.record_id, joined)

    def test_list_is_newest_first(self):
        self._save(0, "OLD")
        self._save(10, "NEW")
        summaries = self.store.list()
        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0].specimen_id, "NEW")
        self.assertEqual(self.store.count(), 2)

    def test_corrupt_file_is_ignored(self):
        self._save()
        with open(os.path.join(self.store.base_dir, "broken.json"), "w", encoding="utf-8") as f:
            f.write("{ not json")
        self.assertEqual(len(self.store.list()), 1)

    def test_sequence_steps_are_stored(self):
        steps = [{"index": 0, "action": "RAMP_LOAD", "started_at": 0.0, "ended_at": 1.0,
                  "end_load_n": 800.0, "outcome": "목표 하중 도달"}]
        summary = self.store.save(
            self.specimen, TestConfig(mode=TestMode.SEQUENCE), self.result, self.points,
            sequence_events=steps,
        )
        record = self.store.load(summary.record_id)
        self.assertEqual(len(record.result.sequence_steps), 1)
        self.assertEqual(record.summary.sequence_steps, 1)

    def test_record_to_session_input(self):
        summary = self._save()
        record = self.store.load(summary.record_id)
        kwargs = self.store.record_to_session_input(record)
        session = SpecimenSession()
        session.add(**kwargs)
        self.assertEqual(len(session), 1)
        self.assertEqual(session.records[0].history_id, summary.record_id)
        self.assertEqual(len(session.records[0].points), len(self.points))

    def test_empty_store(self):
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.store.verify_chain().total, 0)
        self.assertEqual(self.store.last_digest(), "")


# ----------------------------------------------------------------------
# 4. 시퀀스 컨트롤러
# ----------------------------------------------------------------------
class TestSequenceController(unittest.TestCase):
    def test_default_programs_are_valid(self):
        self.assertTrue(SequenceProgram.standard().is_valid())
        self.assertTrue(SequenceProgram.displacement().is_valid())
        self.assertEqual(len(SequenceProgram.standard().steps), 4)

    def test_validation_rules(self):
        bad = SequenceProgram(name="bad", steps=[SequenceStep(StepAction.RAMP_LOAD, target=0.0)])
        self.assertFalse(bad.is_valid())
        self.assertIn("1:target", bad.validate())
        hold_bad = SequenceProgram(steps=[SequenceStep(StepAction.HOLD, hold_s=0.0)])
        self.assertIn("1:hold", hold_bad.validate())
        speed_bad = SequenceProgram(steps=[SequenceStep(StepAction.RAMP_DISP, target=1.0, speed_mm_min=0.0)])
        self.assertIn("1:speed", speed_bad.validate())
        self.assertEqual(SequenceProgram(steps=[]).validate(), ["empty"])

    def test_program_dict_round_trip(self):
        program = SequenceProgram.standard()
        restored = SequenceProgram.from_dict(program.to_dict())
        self.assertEqual(restored.name, program.name)
        self.assertEqual(len(restored.steps), len(program.steps))
        self.assertEqual(restored.steps[0].action, StepAction.RAMP_LOAD)
        self.assertAlmostEqual(restored.steps[0].target, program.steps[0].target)
        self.assertEqual(SequenceProgram.from_dict({}).steps[0].action, StepAction.RAMP_LOAD)

    def test_step_describe_both_languages(self):
        step = SequenceStep(StepAction.RAMP_LOAD, target=500.0, speed_mm_min=5.0)
        self.assertIn("목표 하중 가압", step.describe("KO"))
        self.assertIn("500", step.describe("KO"))
        self.assertIn("Ramp to load", step.describe("EN"))

    def test_controller_advances_through_steps(self):
        program = SequenceProgram(name="t", steps=[
            SequenceStep(StepAction.RAMP_LOAD, target=100.0, speed_mm_min=10.0),
            SequenceStep(StepAction.HOLD, hold_s=1.0),
            SequenceStep(StepAction.RAMP_TO_BREAK, speed_mm_min=10.0),
            SequenceStep(StepAction.RETURN, speed_mm_min=20.0),
        ])
        ctl = SequenceController(program)
        transitions = ctl.start(0.0, 0.0, 0.0)
        self.assertEqual(ctl.current_index, 0)
        self.assertEqual(ctl.speed_mm_min, 10.0)
        self.assertTrue(any(SequenceCommand.RUN in t.commands for t in transitions))

        # 목표 하중 도달 전에는 단계가 유지된다
        ctl.update(0.5, 50.0, 0.05)
        self.assertEqual(ctl.current_index, 0)

        # 목표 도달 -> HOLD 로 전환
        transitions = ctl.update(1.0, 120.0, 0.12)
        self.assertEqual(ctl.current_index, 1)
        self.assertEqual(ctl.speed_mm_min, 0.0)
        self.assertEqual(ctl.direction, 0)
        self.assertEqual(ctl.events[0].outcome, "목표 하중 도달")
        self.assertTrue(any(SequenceCommand.HOLD in t.commands for t in transitions))

        # 유지 시간 경과 -> RAMP_TO_BREAK
        ctl.update(2.5, 120.0, 0.12)
        self.assertEqual(ctl.current_index, 2)
        self.assertEqual(ctl.direction, 1)

        # 파단 -> RETURN
        ctl.update(3.0, 0.0, 0.12, fractured=True)
        self.assertEqual(ctl.current_index, 3)
        self.assertEqual(ctl.direction, -1)

        # 원점 복귀 -> 종료
        transitions = ctl.update(4.0, 0.0, 0.0)
        self.assertTrue(ctl.is_finished)
        self.assertTrue(any(t.finished and SequenceCommand.COMPLETE in t.commands
                            for t in transitions))
        self.assertEqual(len(ctl.events), 4)
        self.assertEqual(ctl.events[-1].outcome, "원점 복귀 완료")

    def test_abort_closes_current_step(self):
        ctl = SequenceController(SequenceProgram.standard())
        ctl.start(0.0, 0.0, 0.0)
        ctl.update(0.5, 10.0, 0.01)
        transitions = ctl.abort(0.6, 10.0, 0.01, "중단")
        self.assertTrue(ctl.is_finished)
        self.assertEqual(ctl.events[0].outcome, "중단")
        self.assertTrue(any(SequenceCommand.STOP in t.commands for t in transitions))
        self.assertTrue(transitions[-1].finished)

    def test_command_lines(self):
        step = SequenceStep(StepAction.RAMP_DISP, target=5.0, speed_mm_min=12.5)
        ctl = SequenceController(SequenceProgram(name="x", steps=[step]))
        transitions = ctl.start(0.0, 0.0, 0.0)
        lines = transitions[0].command_lines()
        self.assertEqual(lines[0], "SPD 12.50\r\n")
        self.assertEqual(lines[1], "RUN\r\n")
        self.assertEqual(format_sequence_command(SequenceCommand.RETURN), "ORG\r\n")

    def test_progress_text(self):
        ctl = SequenceController(SequenceProgram.standard())
        ctl.start(0.0, 0.0, 0.0)
        self.assertIn("1", ctl.progress_text("KO"))
        self.assertIn("4", ctl.progress_text("KO"))
        ctl.abort(0.1, 0.0, 0.0)
        self.assertTrue(ctl.progress_text("KO"))


# ----------------------------------------------------------------------
# 5. 시뮬레이터의 시퀀스 실행
# ----------------------------------------------------------------------
class TestSimulatorSequence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program = SequenceProgram(name="시험용 4단계", steps=[
            SequenceStep(StepAction.RAMP_LOAD, target=800.0, speed_mm_min=5.0),
            SequenceStep(StepAction.HOLD, hold_s=1.0),
            SequenceStep(StepAction.RAMP_TO_BREAK, speed_mm_min=300.0),
            SequenceStep(StepAction.RETURN, speed_mm_min=300.0),
        ])
        cls.config = TestConfig(
            mode=TestMode.SEQUENCE, test_speed_mm_min=200.0,
            sampling_rate_hz=300, max_displacement_mm=40.0, sequence=cls.program,
        )
        cls.points, cls.result, cls.reason, cls.sim = run_simulation(
            make_specimen("SEQ-001"), cls.config, timeout=120,
        )

    def test_all_steps_executed_in_order(self):
        steps = self.result.sequence_steps
        self.assertEqual(len(steps), 4)
        self.assertEqual([s["action"] for s in steps],
                         ["RAMP_LOAD", "HOLD", "RAMP_TO_BREAK", "RETURN"])
        self.assertEqual(steps[0]["outcome"], "목표 하중 도달")
        self.assertEqual(steps[1]["outcome"], "유지 시간 완료")
        self.assertEqual(steps[2]["outcome"], "파단 감지")
        self.assertEqual(steps[3]["outcome"], "원점 복귀 완료")

    def test_step_times_and_loads_are_monotonic(self):
        steps = self.result.sequence_steps
        starts = [s["started_at"] for s in steps]
        self.assertEqual(starts, sorted(starts))
        for prev, curr in zip(steps, steps[1:]):
            self.assertGreaterEqual(curr["started_at"], prev["ended_at"] - 0.01)
        self.assertGreater(steps[2]["end_disp_mm"], steps[2]["start_disp_mm"])   # 가압 중 이동
        self.assertGreater(steps[3]["start_disp_mm"], steps[3]["end_disp_mm"])   # 복귀 중 감소

    def test_hold_keeps_displacement(self):
        hold = self.result.sequence_steps[1]
        self.assertAlmostEqual(hold["start_disp_mm"], hold["end_disp_mm"], delta=0.02)
        self.assertGreaterEqual(hold["duration_s"], 0.9)
        self.assertLessEqual(hold["duration_s"], 2.0)

    def test_sequence_result_properties(self):
        result = self.result
        self.assertIn("파단", self.reason)
        self.assertTrue(result.is_fractured)
        self.assertEqual(result.sequence_name, "시험용 4단계")
        self.assertGreater(result.peak_load_n, 17000.0)
        self.assertAlmostEqual(result.peak_stress_mpa, 450.0, delta=20.0)
        self.assertAlmostEqual(result.elastic_modulus_gpa, 205.0, delta=20.0)
        self.assertGreater(result.elongation_pct, 18.0)     # 복귀 후에도 파단 연신율 유지
        self.assertEqual(result.test_mode, TestMode.SEQUENCE)

    def test_return_does_not_break_elongation_or_modulus(self):
        """복귀 구간(하중 0)이 탄성계수·연신율 계산을 망가뜨리지 않아야 한다"""
        self.assertGreater(self.result.elastic_modulus_gpa, 150.0)
        self.assertGreater(self.result.elongation_pct, 20.0)
        # 마지막 점은 원점 근처이지만 파단 변위는 파단 시점 값이어야 한다
        self.assertGreater(self.result.break_displacement_mm, 8.0)

    def test_simulator_exposes_events(self):
        self.assertEqual(len(self.sim.step_events), 4)
        self.assertEqual(self.sim.sequence_name, "시험용 4단계")

    def test_result_survives_history_round_trip(self):
        tmpdir = tempfile.TemporaryDirectory()
        try:
            store = TestHistoryStore(tmpdir.name)
            summary = store.save(make_specimen("SEQ-001"), self.config, self.result,
                                 self.points, sequence_events=self.result.sequence_steps)
            record = store.load(summary.record_id)
            self.assertEqual(record.config.mode, TestMode.SEQUENCE)
            self.assertEqual(record.config.sequence.name, "시험용 4단계")
            self.assertEqual(len(record.result.sequence_steps), 4)
            self.assertTrue(record.integrity.ok)
        finally:
            tmpdir.cleanup()


# ----------------------------------------------------------------------
# 6. 재질 프로필 / 시편 편차
# ----------------------------------------------------------------------
class TestMaterialProfiles(unittest.TestCase):
    def test_known_grades(self):
        self.assertAlmostEqual(resolve_material_profile("SS400 (일반구조용강)")["su"], 450.0)
        self.assertAlmostEqual(resolve_material_profile("SUS304")["su"], 620.0)
        self.assertAlmostEqual(resolve_material_profile("AL6061-T6")["e"], 69000.0)

    def test_unknown_falls_back_to_ss400(self):
        self.assertAlmostEqual(resolve_material_profile("UNKNOWN-X")["su"],
                               resolve_material_profile("SS400")["su"])

    def test_specimen_scatter_stays_within_tolerance(self):
        config = TestConfig(mode=TestMode.TENSILE, test_speed_mm_min=300.0,
                            sampling_rate_hz=300, max_displacement_mm=40.0)
        results = []
        for i in range(2):
            _, result, _, _ = run_simulation(make_specimen(f"SC-{i}"), config, timeout=60)
            results.append(result)
        for result in results:
            self.assertAlmostEqual(result.peak_stress_mpa, 450.0, delta=20.0)
            self.assertAlmostEqual(result.elastic_modulus_gpa, 205.0, delta=12.0)


# ----------------------------------------------------------------------
# 7. 배치 내보내기
# ----------------------------------------------------------------------
class TestBatchExport(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.session = SpecimenSession()
        for i, (thickness, load) in enumerate(((3.2, 18000.0), (3.0, 16900.0), (3.4, 19200.0))):
            self.session.add(
                make_specimen(f"SALT-SP-{i + 1:03d}", thickness),
                TestConfig(mode=TestMode.TENSILE),
                fake_result(peak_load=load, peak_stress=load / (12.5 * thickness)),
                fake_points(30),
                completion_reason="시편 파단",
                history_id=f"rec-{i}",
            )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_excel_batch_export(self):
        import openpyxl
        from exporters.excel_exporter import ExcelExporter

        path = os.path.join(self.tmpdir.name, "batch.xlsx")
        ExcelExporter.export_batch(path, self.session.records, self.session.statistics(), "KO")
        self.assertTrue(os.path.exists(path))
        wb = openpyxl.load_workbook(path)
        self.assertIn("배치 요약", wb.sheetnames)
        self.assertIn("오버레이 원시 데이터", wb.sheetnames)

        values = [str(c.value) for row in wb["배치 요약"].iter_rows() for c in row if c.value is not None]
        self.assertTrue(any("SP-001" in v for v in values))
        self.assertTrue(any("최대 하중 (N)" in v for v in values))
        self.assertTrue(any("표준편차" in v for v in values))
        self.assertTrue(any("배치 통계" in v for v in values))
        raw_rows = list(wb["오버레이 원시 데이터"].iter_rows(min_row=2))
        self.assertEqual(len(raw_rows), 90)   # 3 시편 x 30 점

        # 영문 라벨 출력도 정상 생성되는지
        path_en = os.path.join(self.tmpdir.name, "batch_en.xlsx")
        ExcelExporter.export_batch(path_en, self.session.records, self.session.statistics(), "EN")
        wb_en = openpyxl.load_workbook(path_en)
        self.assertIn("Batch Summary", wb_en.sheetnames)

    def test_pdf_batch_export(self):
        from exporters.pdf_exporter import PDFExporter

        path = os.path.join(self.tmpdir.name, "batch.pdf")
        PDFExporter.export_batch(path, self.session.records, self.session.statistics(), "KO")
        self.assertTrue(os.path.exists(path))
        with open(path, "rb") as f:
            self.assertEqual(f.read(5), b"%PDF-")
        self.assertGreater(os.path.getsize(path), 3000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
