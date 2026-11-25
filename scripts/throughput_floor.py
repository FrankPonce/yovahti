"""The per-user throughput floor as a dial (E44): energy, congestion and what moved users get.

B4 with min_user_mbps 0 (published method) and 10-20 on the validation weeks; the moved
users' rate uses the same proxy as E27 (scripts/fairness_and_throughput.py).

Run: uv run python scripts/throughput_floor.py   (validation only, D36)
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from compare_methods import load_forecasts
from fairness_and_throughput import active_users, proxy

from yovahti.baselines.simple import always_on
from yovahti.energy.model import SPLITS
from yovahti.paths import RESULTS
from yovahti.plan.dp import DPPlanner, PlannerConfig
from yovahti.world.data import load_world, time_slice
from yovahti.world.sim import WorldConfig, run, summarise


def main() -> None:
    full = load_world("all")
    lo, hi = (int(np.searchsorted(full.times, pd.Timestamp(SPLITS[s][0], tz="UTC")))
              for s in ("validation", "test"))
    world = time_slice(full, lo, hi)
    fc = load_forecasts("plain", "validation")
    cfg = WorldConfig()
    users_full = active_users(full, full.times[0], full.times[-1] + pd.Timedelta("15min"))
    users_val = {c: a[lo:hi] for c, a in users_full.items()}
    b0 = run(world, always_on, "B0", cfg)
    rows = {}
    print(f"{'floor Mbit/s':>12s} {'saved':>7s} {'cong/sd':>8s} {'moved median':>13s} "
          f"{'moved P10':>10s}")
    for floor in (0, 10, 11, 12, 13, 14, 15, 20):
        pol = DPPlanner(world, fc, PlannerConfig(min_user_mbps=float(floor)), cfg,
                        issue_offset=lo, users=users_full, user_offset=0)
        r = run(world, pol, f"floor {floor}", cfg)
        s = summarise(world, r, b0)
        tp = proxy(world, r, users_val)
        rows[floor] = {"kwh_saved_pct": s["kwh_saved_pct"],
                       "congested_qh_per_sector_day": s["congested_qh_per_sector_day"],
                       "throughput": tp}
        print(f"{floor:12d} {s['kwh_saved_pct']:7.2f} {s['congested_qh_per_sector_day']:8.3f} "
              f"{tp.get('after_mbps_median', float('nan')):13.1f} "
              f"{tp.get('after_mbps_p10', float('nan')):10.1f}", flush=True)
    out = RESULTS / "compare" / "throughput_floor_validation.json"
    out.write_text(json.dumps(rows, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
