"""Run B0, B1 and the oracle on a split and print the savings vs quality table.

Run: uv run python scripts/run_baselines.py [validation|train] [--category 1|2]
Never run on the test split before everything is frozen (D23).
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np

from yovahti.baselines.simple import Oracle, StaticThresholds, always_on
from yovahti.paths import RESULTS
from yovahti.world.data import load_world
from yovahti.world.sim import WorldConfig, run, summarise


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("split", nargs="?", default="validation", choices=["train", "validation"])
    p.add_argument("--category", type=int, default=1, choices=[1, 2])
    a = p.parse_args()

    t0 = time.time()
    world = load_world(a.split)
    print(f"world {a.split}: {world.T} quarter-hours x {world.S} sectors "
          f"(NR 3500 on {int(world.present['NR_3500'].sum())}), loaded in {time.time() - t0:.0f}s")
    print("imputed share: " + ", ".join(f"{k} {100 * v:.1f}%"
                                        for k, v in world.imputed_share.items()))

    cfg = WorldConfig(category=a.category)
    t0 = time.time()
    b0 = run(world, always_on, "B0 always-on", cfg)
    print(f"B0 simulated in {time.time() - t0:.1f}s")
    # model check: B0 energy vs measured energy for the mid-band and NR 3500 radios
    for unit in ("mid", "nr3500", "low"):
        meas = world.measured_energy[unit]
        ok = ~np.isnan(meas)
        if unit == "nr3500":
            ok &= world.present["NR_3500"][None, :]
        err = 100 * (b0.energy[unit][ok].sum() / meas[ok].sum() - 1)
        print(f"  B0 vs measured {unit:6s}: {err:+.1f}% total energy")

    runs = [b0,
            run(world, StaticThresholds(), "B1 static thresholds", cfg),
            run(world, Oracle(world, cfg), "Oracle (perfect foresight)", cfg)]
    rows = {r.name: summarise(world, r, b0) for r in runs}
    cols = ["kwh_saved_pct", "capacity_radio_saved_pct", "eur_saved_pct", "co2_saved_pct",
            "kwh_saved_per_sector_day", "sleep_share_mid", "sleep_share_nr",
            "congested_qh_per_sector_day", "unserved_gb", "watchdog_wakes",
            "toggles_per_sector_day"]
    print(f"\nSleep model: TR 38.864 Category {a.category} deep sleep; "
          f"rho_max low {cfg.rho_max_low}%, peak margin {cfg.peak_margin}")
    print(f"{'method':28s} " + " ".join(f"{c[:14]:>14s}" for c in cols))
    for name, s in rows.items():
        print(f"{name:28s} " + " ".join(f"{s.get(c, 0):14.3f}" for c in cols))
    out = RESULTS / "baselines" / f"{a.split}_cat{a.category}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
