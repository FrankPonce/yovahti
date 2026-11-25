"""How much more could a partial-shutdown state save? An analytic bound, not a planner state.

During the quarter-hours Yövahti (B4, default) keeps a capacity radio *awake* while its load is
low, half its antenna branches could be muted instead (Elisa WO2022058648A1; 3GPP spatial
adaptation). Two published power models disagree on what that saves:

* low  · 3GPP TR 38.864 clause 5.1: only the antenna part of the *dynamic* DL power scales with
         the fraction of active TxRUs: saving = A x (1 - s_a) x dynamic energy, A = 0.4,
         s_a = 0.5. Static power does not scale (baseline).
* high · Elisa's patent, measured at 0 % load on an 800/1800 site: partial shutdown of all
         cells saved 89 W where a full shutdown of the 1800 cells saved 213 W, so per hour
         partial ~ 0.42 x the full-sleep saving (idle x (1 - deep-sleep ratio)).

Capacity lost by muting branches is NOT modelled (no public model for this dataset), so the
bound is applied only where the layer's load is under ``max_load`` and is an upper limit on
what such a state could add. Validation weeks only.

Run: uv run python scripts/partial_shutdown_bound.py
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from compare_methods import load_forecasts

from yovahti.baselines.industry import Layers, _sleep_ratios
from yovahti.baselines.simple import always_on
from yovahti.energy.model import SPLITS
from yovahti.paths import RESULTS
from yovahti.plan.dp import DPPlanner, PlannerConfig
from yovahti.world.data import load_world, time_slice
from yovahti.world.sim import AWAKE, WorldConfig, run

A, S_A, ELISA_RATIO = 0.4, 0.5, 89 / 213


def main() -> None:
    full = load_world("all")
    lo, hi = (int(np.searchsorted(full.times, pd.Timestamp(SPLITS[s][0], tz="UTC")))
              for s in ("validation", "test"))
    world = time_slice(full, lo, hi)
    fc = load_forecasts("plain", "validation")
    cfg = WorldConfig()
    b0 = run(world, always_on, "B0", cfg)
    r = run(world, DPPlanner(world, fc, PlannerConfig(), cfg, issue_offset=lo), "B4", cfg)
    lay = Layers.of(world)
    r_mid, r_nr = _sleep_ratios(cfg)
    total_b0 = b0.total_wh().sum()
    total_b4 = r.total_wh().sum()
    out = {}
    for max_load in (5.0, 10.0, 20.0):
        low_tr = high = 0.0
        for unit, state, load, ratio in (("mid", r.mid_state, lay.mid, r_mid),
                                         ("nr3500", r.nr_state, lay.nr, r_nr)):
            idle = world.idle[unit][None]
            cand = (state == AWAKE) & (load < max_load) & (idle > 0)
            dyn = np.clip(r.energy[unit] - idle, 0, None)
            low_tr += float((A * (1 - S_A) * dyn)[cand].sum())
            high += float((ELISA_RATIO * idle * (1 - ratio) * np.ones_like(dyn))[cand].sum())
        out[max_load] = {"extra_pct_of_b0_low_tr38864": round(100 * low_tr / total_b0, 2),
                         "extra_pct_of_b0_high_elisa": round(100 * high / total_b0, 2),
                         "b4_saved_pct": round(100 * (1 - total_b4 / total_b0), 2)}
        print(f"partial shutdown where awake and load < {max_load:4.1f} %: extra "
              f"{out[max_load]['extra_pct_of_b0_low_tr38864']:.2f} % (TR 38.864) to "
              f"{out[max_load]['extra_pct_of_b0_high_elisa']:.2f} % (Elisa measured) of radio "
              f"energy, on top of B4's {out[max_load]['b4_saved_pct']:.2f} %", flush=True)
    path = RESULTS / "compare" / "partial_shutdown_bound_validation.json"
    path.write_text(json.dumps(out, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
