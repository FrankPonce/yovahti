"""Compare every method on the validation weeks: savings vs quality, plus ablations.

Run: uv run python scripts/compare_methods.py [--category 1|2] [--variant plain|trend]
Needs scripts/fit_energy_model.py and scripts/fit_forecaster.py first. Test weeks untouched.
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd

from yovahti.baselines.published import OranScDemoRapp, PublishedThresholdMethod
from yovahti.baselines.simple import Oracle, StaticThresholds, always_on
from yovahti.energy.model import SPLITS
from yovahti.forecast.quantile import TARGETS
from yovahti.paths import PROCESSED, RESULTS
from yovahti.plan.dp import DPPlanner, PlannerConfig
from yovahti.world.data import load_world, time_slice
from yovahti.world.sim import WorldConfig, run, summarise

COLS = ["kwh_saved_pct", "capacity_radio_saved_pct", "eur_saved_pct", "co2_saved_pct",
        "sleep_share_mid", "sleep_share_nr", "congested_qh_per_sector_day", "unserved_gb",
        "watchdog_wakes", "toggles_per_sector_day"]


def load_forecasts(variant: str = "plain") -> dict:
    out = {}
    sfx = "" if variant == "plain" else f"_{variant}"
    for t in TARGETS:
        z = np.load(PROCESSED / "forecasts" / f"validation_{t}{sfx}.npz")
        out[t] = {"issues": z["issues"], 0.1: z["q10"], 0.5: z["q50"], 0.9: z["q90"]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", type=int, default=1, choices=[1, 2])
    ap.add_argument("--variant", default="plain", choices=["plain", "trend"],
                    help="forecast calibration variant written by fit_forecaster.py")
    a = ap.parse_args()
    t0 = time.time()
    full = load_world("all")
    lo = int(np.searchsorted(full.times, pd.Timestamp(SPLITS["validation"][0], tz="UTC")))
    hi = int(np.searchsorted(full.times, pd.Timestamp(SPLITS["test"][0], tz="UTC")))
    world = time_slice(full, lo, hi)
    fc = load_forecasts(a.variant)
    cfg = WorldConfig(category=a.category)
    print(f"validation world {world.T} x {world.S}, ready in {time.time() - t0:.0f}s; "
          f"TR 38.864 Category {a.category}; forecasts: {a.variant}")

    def planner(**kw):
        return DPPlanner(world, fc, PlannerConfig(**kw), cfg, issue_offset=lo)

    methods = {
        "B0 always-on": always_on,
        "B1 static thresholds": StaticThresholds(),
        "B2 published method (reconstruction)": PublishedThresholdMethod(world, fc, lo, cfg),
        "B3 O-RAN SC demo rApp": OranScDemoRapp(world, fc, lo),
        "B4 Yovahti planner (P90, energy)": planner(),
        "B4 price-weighted": planner(weight="price"),
        "B4 CO2-weighted": planner(weight="co2"),
        "Ablation: B4 on P50 (no risk)": planner(risk_q=0.5),
        "Ablation: B4 no switch cost": planner(switch_cost_wh=0.0),
        "Oracle (perfect foresight)": Oracle(world, cfg),
    }
    results, rows = {}, {}
    for name, pol in methods.items():
        t1 = time.time()
        results[name] = run(world, pol, name, cfg)
        rows[name] = summarise(world, results[name], results.get("B0 always-on"))
        print(f"  {name:40s} {time.time() - t1:5.1f}s")
    print(f"\n{'method':40s} " + " ".join(f"{c[:13]:>13s}" for c in COLS))
    for name, s in rows.items():
        print(f"{name:40s} " + " ".join(f"{s.get(c, 0):13.3f}" for c in COLS))

    print("\nrho_max curve (B4 P90 vs B2), low-band limit %:")
    curve = {}
    for rho in (20, 25, 30, 35, 40):
        c2 = WorldConfig(category=a.category, rho_max_low=rho)
        r4 = run(world, DPPlanner(world, fc, PlannerConfig(), c2, issue_offset=lo), "B4", c2)
        r2 = run(world, PublishedThresholdMethod(world, fc, lo, c2,
                                                 wake_low_above=min(30.0, rho)), "B2", c2)
        b0 = run(world, always_on, "B0", c2)
        s4, s2 = summarise(world, r4, b0), summarise(world, r2, b0)
        curve[rho] = {"B4": s4, "B2": s2}
        print(f"  rho {rho:2d}%: B4 saves {s4['kwh_saved_pct']:5.1f}% "
              f"(congested {s4['congested_qh_per_sector_day']:.3f}/sector-day) | B2 saves "
              f"{s2['kwh_saved_pct']:5.1f}% (congested {s2['congested_qh_per_sector_day']:.3f})")
    sfx = "" if a.variant == "plain" else f"_{a.variant}"
    out = RESULTS / "compare" / f"validation_cat{a.category}{sfx}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"methods": rows, "rho_curve": curve}, indent=1))


if __name__ == "__main__":
    main()
