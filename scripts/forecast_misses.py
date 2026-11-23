"""Where do the forecasts miss? Break validation errors down by every axis that could matter.

Run: uv run python scripts/forecast_misses.py
Uses the saved validation forecasts (data/processed/forecasts) and the real traffic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from yovahti.energy.model import SPLITS
from yovahti.forecast.quantile import HORIZON, TARGETS, seasonal_naive, truth
from yovahti.paths import PROCESSED
from yovahti.world.data import load_world

TZ = "Europe/Bratislava"


def main() -> None:
    w = load_world("all")
    v0 = int(np.searchsorted(w.times, pd.Timestamp(SPLITS["validation"][0], tz="UTC")))
    for target in TARGETS:
        z = np.load(PROCESSED / "forecasts" / f"validation_{target}.npz")
        issues = z["issues"]
        p50, p90 = z["q50"].astype(float), z["q90"].astype(float)
        y = truth(w, target, issues)
        sn = seasonal_naive(w, target, issues)
        mask = w.present["NR_3500"] if target == "nr" else np.ones(w.S, bool)
        y, p50, p90, sn = y[..., mask], p50[..., mask], p90[..., mask], sn[..., mask]
        tgt_idx = issues[:, None] + np.arange(HORIZON)[None, :]          # [n, H]
        lt = w.times.tz_convert(TZ)
        hour = lt.hour.to_numpy()[tgt_idx]
        dow = lt.day_of_week.to_numpy()[tgt_idx]
        day = (tgt_idx - v0) // 96
        ae = np.abs(p50 - y)
        miss90 = y > p90
        print(f"\n================ {target}  (mean {y.mean():.0f} MB; MAE {ae.mean():.0f}; "
              f"seasonal naive {np.abs(sn - y).mean():.0f}; above P90 {100 * miss90.mean():.1f}%)")

        def by(name, key, n, y=y, ae=ae, sn=sn, miss90=miss90, p50=p50):
            rows = []
            for k in range(n):
                m = key == k
                if not m.any():
                    continue
                mm = np.broadcast_to(m[..., None], y.shape)
                rows.append((k, ae[mm].mean(), np.abs(sn - y)[mm].mean(),
                             100 * miss90[mm].mean(), (p50 - y)[mm].mean(), y[mm].mean()))
            print(f"-- by {name}: key | MAE | naive MAE | %>P90 | bias (pred-true) | mean")
            for r in rows:
                print(f"   {r[0]:3d} | {r[1]:7.0f} | {r[2]:7.0f} | {r[3]:5.1f} | {r[4]:+7.0f} | "
                      f"{r[5]:7.0f}")

        by("local hour", hour, 24)
        by("day of validation (0 = Sun 26 Oct, DST ends)", day, 14)
        by("day of week (0 = Mon)", dow, 7)
        hb = np.broadcast_to(np.minimum(np.arange(HORIZON) // 4, 9)[None, :], tgt_idx.shape)
        by("horizon hour", hb, 10)
        # sector size deciles
        lvl = y.mean(axis=(0, 1))
        dec = pd.qcut(lvl, 10, labels=False, duplicates="drop")
        rows = []
        for k in sorted(set(dec)):
            m = dec == k
            rows.append((k, ae[..., m].mean(), np.abs(sn - y)[..., m].mean(),
                         100 * miss90[..., m].mean(), y[..., m].mean()))
        print("-- by sector size decile: decile | MAE | naive | %>P90 | mean")
        for r in rows:
            print(f"   {r[0]:3d} | {r[1]:7.0f} | {r[2]:7.0f} | {r[3]:5.1f} | {r[4]:7.0f}")
        # error concentration
        se = np.sort(ae.ravel())[::-1]
        print(f"-- top 1% of errors carry {100 * se[:len(se) // 100].sum() / se.sum():.0f}% of "
              f"total absolute error; top 10% carry "
              f"{100 * se[:len(se) // 10].sum() / se.sum():.0f}%")


if __name__ == "__main__":
    main()
