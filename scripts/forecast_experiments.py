"""Forecaster fixes, each scored on TWO windows (a change counts only if it wins both).

Run: uv run python scripts/forecast_experiments.py
Windows (UTC): inner backtest  fit < 28 Sep, calibrate 28 Sep-12 Oct, score 12-26 Oct
               validation      fit < 12 Oct, calibrate 12-26 Oct,     score 26 Oct-9 Nov
Variants: model {baseline, F1 level-normalised} x calibration {global, F2 Mondrian-by-hour,
F3 rolling Mondrian}. Test weeks are never touched.
"""

from __future__ import annotations

import json
import sys
import time

import numpy as np
import pandas as pd

from yovahti.forecast import calibration as cal
from yovahti.forecast.quantile import HORIZON, TARGETS, TZ, Forecaster, seasonal_naive, truth
from yovahti.paths import RESULTS
from yovahti.world.data import load_world

WINDOWS = {
    "inner": ("2025-09-28", "2025-10-12", "2025-10-26"),
    "validation": ("2025-10-12", "2025-10-26", "2025-11-09"),
}


def metrics(pred: dict, y: np.ndarray, sn: np.ndarray, hour: np.ndarray) -> dict:
    p50, p10, p90 = pred[0.5], pred[0.1], pred[0.9]
    mae = np.abs(p50 - y).mean()
    above = y > p90
    by_h = np.array([above[hour == h].mean() for h in range(24)])
    pin = lambda p, q: np.maximum(q * (y - p), (q - 1) * (y - p)).mean()  # noqa: E731
    return {
        "skill_pct": float(100 * (1 - mae / np.abs(sn - y).mean())),
        "mae": float(mae),
        "coverage_pct": float(100 * ((y >= p10) & (y <= p90)).mean()),
        "above_p90_pct": float(100 * above.mean()),
        "hourly_p90_err_pp": float(100 * np.abs(by_h - 0.10).mean()),
        "worst_hour_above_p90_pct": float(100 * by_h.max()),
        "pinball": float((pin(p10, 0.1) + pin(p50, 0.5) + pin(p90, 0.9)) / 3),
    }


def main() -> None:
    t0 = time.time()
    w = load_world("all")
    lt_hour = w.times.tz_convert(TZ).hour.to_numpy()
    print(f"world {w.T} x {w.S}, {time.time() - t0:.0f}s")

    def ix(d):
        return int(np.searchsorted(w.times, pd.Timestamp(d, tz="UTC")))

    report = {}
    for wname, (fit_end_d, eval_start_d, eval_end_d) in WINDOWS.items():
        fit_end, eval_start, eval_end = ix(fit_end_d), ix(eval_start_d), ix(eval_end_d)
        issues = np.arange(fit_end, eval_end - HORIZON + 1, 4)
        evm = issues >= eval_start
        calm = (issues + HORIZON <= eval_start)
        tgt_idx = issues[:, None] + np.arange(HORIZON)[None, :]
        hour = lt_hour[tgt_idx]
        for target in [t for t in TARGETS if len(sys.argv) < 2 or t in sys.argv[1:]]:
            mask = w.present["NR_3500"] if target == "nr" else np.ones(w.S, bool)
            y = truth(w, target, issues)
            ylog = np.log1p(y)
            sn = seasonal_naive(w, target, issues)
            for norm in (False, True):
                t1 = time.time()
                f = Forecaster.fit(w, target, fit_end, level_norm=norm)
                logp = f.predict_log(w, issues)
                variants = {
                    "global": cal.apply_global(
                        logp, cal.global_offsets({q: v[calm] for q, v in logp.items()},
                                                 ylog[calm], mask)),
                    "mondrian": cal.apply_mondrian(
                        logp, cal.mondrian_offsets({q: v[calm] for q, v in logp.items()},
                                                   ylog[calm], hour[calm], mask), hour),
                    "rolling": cal.rolling_mondrian(logp, ylog, hour, issues, evm, fit_end,
                                                sectors=mask),
                }
                for vname, lp in variants.items():
                    pred = {q: v[evm][..., mask] for q, v in cal.to_mb(lp).items()}
                    m = metrics(pred, y[evm][..., mask], sn[evm][..., mask],
                                np.broadcast_to(hour[evm][..., None],
                                                y[evm][..., mask].shape))
                    key = f"{'F1' if norm else 'base'}+{vname}"
                    report.setdefault(target, {}).setdefault(key, {})[wname] = m
                print(f"{wname:10s} {target:4s} level_norm={norm!s:5s} {time.time() - t1:5.0f}s",
                      flush=True)

    out = RESULTS / "forecast" / "experiments.json"
    old = json.loads(out.read_text()) if out.exists() else {}
    old.update(report)
    out.write_text(json.dumps(old, indent=1))
    cols = ["skill_pct", "coverage_pct", "above_p90_pct", "hourly_p90_err_pp",
            "worst_hour_above_p90_pct", "pinball"]
    for target, rows in report.items():
        print(f"\n=== {target}   (inner | validation)")
        print(f"{'variant':16s} " + " ".join(f"{c[:16]:>23s}" for c in cols))
        for key, r in rows.items():
            print(f"{key:16s} " + " ".join(
                f"{r['inner'][c]:10.2f} | {r['validation'][c]:10.2f}" for c in cols))


if __name__ == "__main__":
    main()
