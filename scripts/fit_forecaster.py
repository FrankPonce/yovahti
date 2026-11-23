"""Fit the quantile forecasters and write calibrated validation forecasts for the planner.

Run: uv run python scripts/fit_forecaster.py [--level-norm] [--calib global|mondrian|rolling]
Fit on the first six training weeks, calibrate on the last two (and, for ``rolling``, on
realised validation outcomes as they become known). Defaults follow the experiments that won
on both windows (D29, FINDINGS E17). Test weeks untouched.
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd

from yovahti.energy.model import SPLITS
from yovahti.forecast import calibration as cal
from yovahti.forecast.quantile import (
    HORIZON,
    QUANTILES,
    TARGETS,
    TZ,
    Forecaster,
    persistence,
    pinball,
    seasonal_naive,
    truth,
)
from yovahti.paths import PROCESSED, RESULTS
from yovahti.world.data import load_world


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level-norm", action=argparse.BooleanOptionalAction, default=False)
    ap.add_argument("--calib", choices=["global", "mondrian", "rolling"], default="rolling")
    a = ap.parse_args()
    t0 = time.time()
    world = load_world("all")
    idx = {k: int(np.searchsorted(world.times, pd.Timestamp(v[0], tz="UTC")))
           for k, v in SPLITS.items() if k != "all"}
    train_end, val_end = idx["validation"], idx["test"]
    fit_end = train_end - 14 * 96
    issues_all = np.arange(fit_end, val_end - HORIZON + 1, 4)
    evm = issues_all >= train_end
    calm = issues_all + HORIZON <= train_end
    issues = issues_all[evm]
    hour = world.times.tz_convert(TZ).hour.to_numpy()[issues_all[:, None]
                                                       + np.arange(HORIZON)[None, :]]
    print(f"world all: {world.T} x {world.S}, loaded {time.time() - t0:.0f}s; "
          f"{len(issues)} validation issues; level_norm={a.level_norm}, calib={a.calib}")
    report = {"config": {"level_norm": a.level_norm, "calib": a.calib}}
    out_dir = PROCESSED / "forecasts"
    out_dir.mkdir(parents=True, exist_ok=True)
    for target in TARGETS:
        t0 = time.time()
        f = Forecaster.fit(world, target, fit_end, level_norm=a.level_norm)
        for q, m in f.models.items():
            (RESULTS / "forecast").mkdir(parents=True, exist_ok=True)
            m.save_model(str(RESULTS / "forecast" / f"{target}_q{int(q * 100)}.txt"))
        mask = world.present["NR_3500"] if target == "nr" else np.ones(world.S, dtype=bool)
        logp = f.predict_log(world, issues_all)
        ylog = np.log1p(truth(world, target, issues_all))
        if a.calib == "global":
            lp = cal.apply_global(logp, cal.global_offsets(
                {q: v[calm] for q, v in logp.items()}, ylog[calm], mask))
        elif a.calib == "mondrian":
            lp = cal.apply_mondrian(logp, cal.mondrian_offsets(
                {q: v[calm] for q, v in logp.items()}, ylog[calm], hour[calm], mask), hour)
        else:
            lp = cal.rolling_mondrian(logp, ylog, hour, issues_all, evm, fit_end,
                                       sectors=mask)
        pred = {q: v[evm] for q, v in cal.to_mb(lp).items()}

        y = truth(world, target, issues)
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
        print(f"{target:4s} {time.time() - t0:.0f}s | MAE {mae:.1f} MB (seasonal naive "
              f"{r['mae_seasonal_naive_mb']:.1f}) skill {r['skill_vs_seasonal_naive_pct']:+.1f}% |"
              f" P10-P90 coverage {r['coverage_p10_p90_pct']:.1f}% | above P90 "
              f"{r['above_p90_pct']:.1f}%")
    (RESULTS / "forecast" / "validation_report.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
