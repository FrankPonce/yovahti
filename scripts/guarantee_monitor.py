"""Watch the guarantee on the validation weeks, then show it catching drift.

1. As run: daily checks of the default planner (P90, margin 1.0, implicit alpha 0.10).
2. Drift: the same weeks with traffic 20 % above what the forecasts expected from day 8 on
   (scores x 1.2): the monitor should raise the alarm and suggest a wider margin.

Run: uv run python scripts/guarantee_monitor.py   (validation weeks only, D36)
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace

import numpy as np
import pandas as pd
from compare_methods import load_forecasts

from yovahti.energy.model import SPLITS
from yovahti.forecast.bound import scores
from yovahti.forecast.monitor import daily_checks
from yovahti.paths import RESULTS
from yovahti.world.data import load_world, time_slice
from yovahti.world.sim import WorldConfig


def show(title, checks):
    print(f"\n{title}")
    for c in checks:
        print(f"  day {c.day:2d}: miss {c.miss:.3f} (limit {c.limit:.3f}, n {c.n:,}) "
              f"night {c.groups.get('night', float('nan')):.3f} "
              f"day {c.groups.get('day', float('nan')):.3f}"
              f"  {'ALARM' if c.alarm else 'ok   '}  suggested margin {c.suggested_margin:.3f}")


def main() -> None:
    full = load_world("all")
    lo, hi = (int(np.searchsorted(full.times, pd.Timestamp(SPLITS[s][0], tz="UTC")))
              for s in ("validation", "test"))
    world = time_slice(full, lo, hi)
    fc = load_forecasts("plain", "validation")
    sc = scores(world, fc, lo, WorldConfig())
    as_run = daily_checks(sc, current_margin=1.0, alpha=0.10)
    show("As run (P90, margin 1.0, alpha 0.10)", as_run)
    drift_r = np.where(sc.t // 96 >= 7, sc.r * 1.2, sc.r)
    drifted = daily_checks(replace(sc, r=drift_r), current_margin=1.0, alpha=0.10)
    show("Drift: traffic +20 % above forecast from day 7", drifted)
    out = RESULTS / "compare" / "guarantee_monitor_validation.json"
    out.write_text(json.dumps({"alpha": 0.10, "margin": 1.0,
                               "as_run": [asdict(c) for c in as_run],
                               "drift_plus_20pct_from_day_7": [asdict(c) for c in drifted]},
                              indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
