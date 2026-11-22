"""
Salt Sw ver.1 - 소프트 PID 하중 속도 제어 성능 검증 (시뮬레이션)

재질 3종(고무 · 필름 · 금속)에 대해 통신 지연 40 ms · 제어 주기 25 Hz 조건에서
① Soft-PID (실시간 속도 보정) ② 고정 속도 (초기 강성 환산 · 실시간 보정 없음)
를 같은 목표(하중 속도 → 목표 하중 → 유지)로 실행하고 추종 오차와 오버슈트를 비교한다.

실행:
    python3 tools/pid_benchmark.py

결과:
    docs/screenshots/17_pid_tracking_compare_ko.png   (목표 vs 실제 하중 추종 곡선 3종)
    docs/pid_benchmark.json                           (수치 결과)
"""

import json
import os
import random
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from core.models import Specimen, SpecimenType, TestConfig, TestMode
from core.pid_controller import evaluate_tracking
from core.simulator import VirtualUTMSimulator

OUT_IMAGE = os.path.join(BASE_DIR, "docs", "screenshots", "17_pid_tracking_compare_ko.png")
OUT_JSON = os.path.join(BASE_DIR, "docs", "pid_benchmark.json")

CASES = [
    dict(key="elastomer", label="PID 1 연질 · 고무 (NBR)", material="NBR",
         width=12.5, thickness=3.2, rate_n_min=1800.0, target_n=120.0,
         hold_s=4.0, profile="elastomer"),
    dict(key="film", label="PID 2 중질 · 필름 (PET)", material="PET",
         width=20.0, thickness=0.1, rate_n_min=4800.0, target_n=100.0,
         hold_s=4.0, profile="film"),
    dict(key="metal", label="PID 3 고강성 · 금속 (SS400)", material="SS400",
         width=12.5, thickness=3.2, rate_n_min=96000.0, target_n=2000.0,
         hold_s=4.0, profile="metal"),
]


def run_case(case, live=True, delay_ms=40.0, control_hz=25.0, seed=11, time_scale=6.0):
    random.seed(seed)
    specimen = Specimen(
        specimen_id=f"PID-{case['key'].upper()}",
        material=case["material"],
        specimen_type=SpecimenType.FLAT,
        width_mm=case["width"],
        thickness_mm=case["thickness"],
        gauge_length_mm=50.0,
    )
    config = TestConfig(
        mode=TestMode.HOLDING,
        control_mode="LOAD_HOLD",
        target_rate=case["rate_n_min"],
        target_holding_val=case["target_n"],
        holding_duration_s=case["hold_s"],
        pid_profile_id=case["profile"],
        comm_delay_ms=delay_ms,
        control_rate_hz=control_hz,
        live_speed_control=live,
        sampling_rate_hz=200,
        max_displacement_mm=60.0,
    )
    sim = VirtualUTMSimulator()
    sim.time_scale = time_scale
    sim.connect()
    state = {}
    points = []
    sim.on_data_received = points.append
    sim.on_test_completed = lambda reason: state.setdefault("reason", reason)
    sim.start_test(specimen, config)
    deadline = time.time() + 60.0
    while "reason" not in state and time.time() < deadline:
        time.sleep(0.01)
    sim.stop_test()
    metrics = evaluate_tracking(list(sim.control_trace),
                                target_rate_n_s=case["rate_n_min"] / 60.0,
                                target_load_n=case["target_n"])
    return {
        "reason": state.get("reason", ""),
        "metrics": metrics,
        "trace": [(s.time_s, s.setpoint_n, s.load_n) for s in sim.control_trace],
        "stiffness": sim.controller.stiffness_n_per_mm if sim.controller else 0.0,
    }


def main():
    results = {"condition": {"delay_ms": 40.0, "control_hz": 25.0}, "cases": {}}
    for case in CASES:
        pid = run_case(case, live=True)
        fixed = run_case(case, live=False)
        worst_delay = run_case(case, live=True, delay_ms=50.0, control_hz=20.0)
        fast = run_case(case, live=True, delay_ms=20.0, control_hz=50.0)
        results["cases"][case["key"]] = {
            "label": case["label"],
            "target_n": case["target_n"],
            "rate_n_min": case["rate_n_min"],
            "hold_s": case["hold_s"],
            "pid": {**pid["metrics"], "reason": pid["reason"], "stiffness": pid["stiffness"]},
            "fixed": {**fixed["metrics"], "reason": fixed["reason"], "stiffness": fixed["stiffness"]},
            "pid_20hz_50ms": {**worst_delay["metrics"], "reason": worst_delay["reason"]},
            "pid_50hz_20ms": {**fast["metrics"], "reason": fast["reason"]},
            "trace_pid": pid["trace"],
            "trace_fixed": fixed["trace"],
        }
        print(f"[{case['key']}] PID 오버슈트 {pid['metrics']['overshoot_pct']:.2f}% · "
              f"추종 {pid['metrics']['follow_error_pct']:.2f}% · "
              f"유지 {pid['metrics']['hold_error_pct']:.2f}%  /  "
              f"고정 속도 오버슈트 {fixed['metrics']['overshoot_pct']:.2f}% · "
              f"추종 {fixed['metrics']['follow_error_pct']:.2f}%")

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    plot(results)
    print(f"저장: {OUT_JSON}")
    print(f"저장: {OUT_IMAGE}")


def plot(results):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for font_path in ("/usr/share/fonts/pickle-hwp/NotoSansCJKkr-Regular.otf",
                      "/workspace/NanumGothic-Regular.ttf"):
        if os.path.exists(font_path):
            font_manager.fontManager.addfont(font_path)
            family = font_manager.FontProperties(fname=font_path).get_name()
            plt.rcParams["font.family"] = family
            break
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(1, 3, figsize=(15.0, 5.0), dpi=150)
    for ax, case in zip(axes, CASES):
        data = results["cases"][case["key"]]
        pid_t = data["trace_pid"]
        fixed_t = data["trace_fixed"]
        ax.plot([p[0] for p in pid_t], [p[1] for p in pid_t], color="#94A3B8",
                linewidth=1.4, linestyle=(0, (4, 3)), label="목표 하중")
        ax.plot([p[0] for p in pid_t], [p[2] for p in pid_t], color="#1D4ED8",
                linewidth=1.9, label="Soft-PID (실시간 보정)")
        ax.plot([p[0] for p in fixed_t], [p[2] for p in fixed_t], color="#C2410C",
                linewidth=1.5, label="고정 속도 (보정 없음)")

        ax.set_title(case["label"], fontsize=11, fontweight="bold")
        ax.set_xlabel("시간 (s)", fontsize=9)
        ax.set_ylabel("하중 (N)", fontsize=9)
        ax.grid(alpha=0.25, linewidth=0.7)
        ax.tick_params(labelsize=8)
        peak_all = max(max(p[1] for p in pid_t), max(p[2] for p in pid_t),
                       max(p[2] for p in fixed_t))
        ax.set_ylim(0, peak_all * 1.32)
        ax.axhline(case["target_n"], color="#94A3B8", linewidth=0.8, linestyle=":")
        pid_m = data["pid"]
        fixed_m = data["fixed"]
        ax.text(0.02, 0.94,
                f"오버슈트  PID {pid_m['overshoot_pct']:.1f}% / 고정 {fixed_m['overshoot_pct']:.1f}%\n"
                f"추종 오차  PID {pid_m['follow_error_pct']:.1f}% / 고정 {fixed_m['follow_error_pct']:.1f}%\n"
                f"유지 오차  PID {pid_m['hold_error_pct']:.1f}%",
                transform=ax.transAxes, va="top", ha="left", fontsize=8,
                bbox=dict(boxstyle="round,pad=0.35", facecolor="#F8FAFC",
                          edgecolor="#CBD5E1", linewidth=0.6))
        ax.legend(loc="lower right", fontsize=8, framealpha=0.9)

    fig.suptitle("소프트 PID 하중 속도 제어 추종 성능 — 통신 지연 40 ms · 제어 주기 25 Hz",
                 fontsize=13, fontweight="bold")
    fig.text(0.5, 0.02,
             "목표 하중 속도로 가압한 뒤 목표 하중에서 유지. 고정 속도는 초기 강성으로 환산한 속도를 한 번만 적용한 방식.",
             ha="center", fontsize=8.5, color="#475569")
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    os.makedirs(os.path.dirname(OUT_IMAGE), exist_ok=True)
    fig.savefig(OUT_IMAGE)
    plt.close(fig)


if __name__ == "__main__":
    main()
