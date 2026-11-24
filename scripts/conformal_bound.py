"""Conformal congestion bound on the validation weeks (forecast/bound.py).

Two folds: calibrate the margin on one validation week, check it on the other, and swap.
For each alpha: the margin, the miss rate on the held-out week (should be <= alpha), and
B4 run with that margin: energy saved and congested / slept sector-quarter-hours (the bound
says <= alpha). Test weeks untouched (D36).

Run: uv run python scripts/conformal_bound.py
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
from compare_methods import load_forecasts

from yovahti.baselines.simple import always_on
from yovahti.energy.model import SPLITS
from yovahti.forecast.bound import margin, mondrian_margin, scores
from yovahti.paths import RESULTS
from yovahti.plan.dp import DPPlanner, PlannerConfig
from yovahti.world.data import load_world, time_slice
from yovahti.world.sim import ASLEEP, WorldConfig, run, summarise

ALPHAS = (0.2, 0.1, 0.05, 0.02)


def main() -> None:
    t0 = time.time()
    full = load_world("all")
    lo, hi = (int(np.searchsorted(full.times, pd.Timestamp(SPLITS[s][0], tz="UTC")))
              for s in ("validation", "test"))
    world = time_slice(full, lo, hi)
    fc = load_forecasts("plain", "validation")
    cfg = WorldConfig()
    sc = scores(world, fc, lo, cfg)
    half = world.T // 2
    weeks = {"week 1": sc.t < half, "week 2": sc.t >= half}
    print(f"{len(sc.r):,} sleep-eligible sector-QH scored in {time.time() - t0:.0f}s; "
          f"median score {np.median(sc.r):.3f}, raw P90 miss {np.mean(sc.r > 1):.3f}",
          flush=True)
    b0 = run(world, always_on, "B0", cfg)
    out = {"raw_p90_miss": float(np.mean(sc.r > 1)), "n": int(len(sc.r)), "folds": {}}
    for cal_name, cal in weeks.items():
        ev_name = next(k for k in weeks if k != cal_name)
        ev = weeks[ev_name]
        ev_t = np.zeros(world.T, dtype=bool)
        ev_t[half:] = ev_name == "week 2"
        ev_t[:half] = ev_name == "week 1"
        rows = {}
        for a in ALPHAS:
            m = margin(sc.r[cal], a)
            mm = mondrian_margin(sc, cal, a)
            miss = float(np.mean(sc.r[ev] > m))
            r = run(world, DPPlanner(world, fc, PlannerConfig(margin=m), cfg, issue_offset=lo),
                    f"B4 m={m:.2f}", cfg)
            slept = ((r.mid_state == ASLEEP) | (r.nr_state == ASLEEP))[ev_t]
            cong = r.congested[ev_t]
            s = summarise(world, r, b0)
            rows[str(a)] = {"margin": m, "mondrian": mm, "heldout_miss": miss,
                            "congested_per_slept": float(cong.sum() / max(slept.sum(), 1)),
                            "kwh_saved_pct": s["kwh_saved_pct"],
                            "congested_qh_per_sector_day": s["congested_qh_per_sector_day"]}
            print(f"  calibrate {cal_name}, check {ev_name} | alpha {a:4.2f}: margin {m:.3f} "
                  f"(night {mm['night']:.3f}, day {mm['day']:.3f}); held-out miss {miss:.3f}; "
                  f"B4 saves {s['kwh_saved_pct']:5.1f} %, congested/slept "
                  f"{rows[str(a)]['congested_per_slept']:.4f} "
                  f"({'within' if rows[str(a)]['congested_per_slept'] <= a else 'ABOVE'} bound)",
                  flush=True)
        out["folds"][f"{cal_name} -> {ev_name}"] = rows
    path = RESULTS / "compare" / "conformal_bound_validation.json"
    path.write_text(json.dumps(out, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
