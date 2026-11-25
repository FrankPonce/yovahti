"""Do ideas from other published methods improve Yövahti's planner? (validation weeks only)

Compared against the uniform margin dial: an idea helps only if it beats the dial's curve at
matched congestion. Writes results/compare/borrowed_ideas_validation.json.

Run: uv run python scripts/borrowed_ideas.py
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
from compare_methods import load_forecasts

from yovahti.baselines.simple import always_on
from yovahti.energy.model import SPLITS
from yovahti.paths import RESULTS
from yovahti.plan.dp import DPPlanner, PlannerConfig
from yovahti.plan.variants import AdaptiveMarginPlanner, NightRollback
from yovahti.world.data import load_world, time_slice
from yovahti.world.sim import WorldConfig, run, summarise


def main() -> None:
    t0 = time.time()
    full = load_world("all")

    def at(day):
        return int(np.searchsorted(full.times, pd.Timestamp(day, tz="UTC")))
    lo, hi = at(SPLITS["validation"][0]), at(SPLITS["test"][0])
    world = time_slice(full, lo, hi)
    fc = load_forecasts("plain", "validation")
    cfg = WorldConfig()

    def b4(**kw):
        return DPPlanner(world, fc, PlannerConfig(**kw), cfg, issue_offset=lo)

    def adaptive(step):
        return AdaptiveMarginPlanner(world, fc, PlannerConfig(), cfg, issue_offset=lo, step=step)
    methods = {"B0": always_on}
    for m in (1.0, 1.15, 1.3, 1.5):
        methods[f"B4 margin {m:g} (dial)"] = b4(margin=m)
    methods.update({
        "B4 + adaptive margin x1.15 (Samsung idea)": adaptive(1.15),
        "B4 + adaptive margin x1.3 (Samsung idea)": adaptive(1.3),
        "B4 + night rollback (Parallel Wireless idea)": NightRollback(b4(), world),
        "B4 + adaptive x1.3 + night rollback": NightRollback(adaptive(1.3), world),
    })
    print(f"ready in {time.time() - t0:.0f}s", flush=True)
    rows, b0 = {}, None
    for name, pol in methods.items():
        r = run(world, pol, name, cfg)
        b0 = b0 or r
        rows[name] = summarise(world, r, b0)
    print(f"\n{'variant':48s} {'saved':>7s} {'cong/sd':>8s} {'unserv GB':>10s} {'wakes':>7s}")
    for name, s in rows.items():
        print(f"{name:48s} {s['kwh_saved_pct']:7.2f} {s['congested_qh_per_sector_day']:8.3f} "
              f"{s['unserved_gb']:10.1f} {s['watchdog_wakes']:7.0f}")
    out = RESULTS / "compare" / "borrowed_ideas_validation.json"
    keep = ("kwh_saved_pct", "congested_qh_per_sector_day", "unserved_gb", "watchdog_wakes",
            "toggles_per_sector_day")
    out.write_text(json.dumps({k: {c: v[c] for c in keep} for k, v in rows.items()}, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
