"""Fit the quantile forecasters on the training weeks; score them on validation issues.

Run: uv run python scripts/fit_forecaster.py
Saves models to results/forecast/<target>_q<q>.txt and validation forecasts (hourly issues)
to data/processed/forecasts/validation_<target>.npz for the planner. Test weeks untouched.
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from yovahti.energy.model import SPLITS
from yovahti.forecast.quantile import (
    QUANTILES,
    TARGETS,
    Forecaster,
    calibrate,
    persistence,
    pinball,
    seasonal_naive,
    truth,
)
from yovahti.paths import PROCESSED, RESULTS
from yovahti.world.data import load_world


def main() -> None:
    t0 = time.time()
    world = load_world("all")
    idx = {k: int(np.searchsorted(world.times, pd.Timestamp(v[0], tz="UTC")))
           for k, v in SPLITS.items() if k != "all"}
    train_end, val_end = idx["validation"], idx["test"]
    # hourly issues in validation; the last issue's horizon must stay inside validation
    issues = np.arange(train_end, val_end - 40 + 1, 4)
    print(f"world all: {world.T} x {world.S}, loaded {time.time() - t0:.0f}s; "
          f"{len(issues)} validation issues")
    report = {}
    out_dir = PROCESSED / "forecasts"
    out_dir.mkdir(parents=True, exist_ok=True)
    for target in TARGETS:
        t0 = time.time()
        # fit on the first 6 training weeks, calibrate on the last 2 (Tasehinta's discipline)
        calib_start = train_end - 14 * 96
        f = Forecaster.fit(world, target, calib_start)
        calibrate(f, world, calib_start, train_end)
        for q, m in f.models.items():
            (RESULTS / "forecast").mkdir(parents=True, exist_ok=True)
            m.save_model(str(RESULTS / "forecast" / f"{target}_q{int(q * 100)}.txt"))
        pred = f.predict_many(world, issues)
        y = truth(world, target, issues)
        mask = np.ones(world.S, dtype=bool)
        if target == "nr":
            mask = world.present["NR_3500"]
        yy = y[:, :, mask]
        sn = seasonal_naive(world, target, issues)[:, :, mask]
        pe = persistence(world, target, issues)[:, :, mask]
        p50 = pred[0.5][:, :, mask]
        mae = float(np.abs(p50 - yy).mean())
        r = {
            "mae_mb": mae,
            "mae_seasonal_naive_mb": float(np.abs(sn - yy).mean()),
            "mae_persistence_mb": float(np.abs(pe - yy).mean()),
            "skill_vs_seasonal_naive_pct": float(100 * (1 - mae / np.abs(sn - yy).mean())),
            "pinball_p10": pinball(yy, pred[0.1][:, :, mask], 0.1),
            "pinball_p90": pinball(yy, pred[0.9][:, :, mask], 0.9),
            "coverage_p10_p90_pct": float(100 * ((yy >= pred[0.1][:, :, mask])
                                                 & (yy <= pred[0.9][:, :, mask])).mean()),
            "above_p90_pct": float(100 * (yy > pred[0.9][:, :, mask]).mean()),
            "mean_mb": float(yy.mean()),
            "mae_by_horizon": [float(np.abs(p50[:, h] - yy[:, h]).mean()) for h in (0, 3, 15, 39)],
        }
        report[target] = r
        np.savez_compressed(out_dir / f"validation_{target}.npz", issues=issues,
                            **{f"q{int(q * 100)}": pred[q] for q in QUANTILES})
        print(f"{target:4s} fit+predict {time.time() - t0:.0f}s | MAE {mae:.1f} MB "
              f"(seasonal naive {r['mae_seasonal_naive_mb']:.1f}, persistence "
              f"{r['mae_persistence_mb']:.1f}) skill {r['skill_vs_seasonal_naive_pct']:+.1f}% | "
              f"P10-P90 coverage {r['coverage_p10_p90_pct']:.1f}% | above P90 "
              f"{r['above_p90_pct']:.1f}% | MAE by horizon 1/4/16/40: "
              + "/".join(f"{v:.0f}" for v in r["mae_by_horizon"]))
    (RESULTS / "forecast" / "validation_report.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
