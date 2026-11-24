"""Growth / 4G->5G migration candidates (HANDOFF 7.1, FINDINGS G28), scored on TWO windows.

Run: uv run python scripts/growth_experiments.py [nr mid low]
Windows as in forecast_experiments.py (D29). Every variant uses the D30 set-up (no level
normalisation, daily rolling Mondrian calibration, 14 days) unless it changes one piece:

  base         D30 as is (model frozen at the window's fit end)
  C1-med7      P50 calibrated on the last 7 days, tails on 14
  C1-med3      P50 calibrated on the last 3 days, tails on 14
  C2-trend     extrapolated drift of the median residual added to every quantile
  M1-hl14      time-decay sample weights, half-life 14 days
  M2-refit     model re-fitted weekly on all data before each refit point (out-of-sample)
  M2+C2        both

Besides pinball/skill/coverage it reports whether the P50 is a median (share of outcomes below
it) and the sum bias (P50 total vs real total), which for skewed traffic is NOT zero for a
correct median (FINDINGS G28). Test weeks are never touched.
"""

from __future__ import annotations

import json
import sys
import time

import numpy as np
import pandas as pd

from yovahti.forecast import calibration as cal
from yovahti.forecast.quantile import (
    HORIZON,
    TARGETS,
    TZ,
    WEEK,
    Forecaster,
    refit_predict_log,
    seasonal_naive,
    truth,
)
from yovahti.paths import RESULTS
from yovahti.world.data import load_world

WINDOWS = {
    "inner": ("2025-09-28", "2025-10-12", "2025-10-26"),
    "validation": ("2025-10-12", "2025-10-26", "2025-11-09"),
}


def metrics(pred: dict, y: np.ndarray, sn: np.ndarray, week: np.ndarray) -> dict:
    p10, p50, p90 = pred[0.1], pred[0.5], pred[0.9]
    mae = np.abs(p50 - y).mean()
    pin = lambda p, q: np.maximum(q * (y - p), (q - 1) * (y - p)).mean()  # noqa: E731
    r = {
        "pinball": float((pin(p10, 0.1) + pin(p50, 0.5) + pin(p90, 0.9)) / 3),
        "pinball_p50": float(pin(p50, 0.5)),
        "pinball_p90": float(pin(p90, 0.9)),
        "skill_pct": float(100 * (1 - mae / np.abs(sn - y).mean())),
        "coverage_pct": float(100 * ((y >= p10) & (y <= p90)).mean()),
        "above_p90_pct": float(100 * (y > p90).mean()),
        "below_p50_pct": float(100 * (y < p50).mean()),
        "sum_bias_pct": float(100 * (p50.sum() / y.sum() - 1)),
    }
    for k in (0, 1):
        m = week == k
        r[f"below_p50_wk{k}"] = float(100 * (y[m] < p50[m]).mean())
        r[f"above_p90_wk{k}"] = float(100 * (y[m] > p90[m]).mean())
    return r


def main() -> None:
    t0 = time.time()
    w = load_world("all")
    lt_hour = w.times.tz_convert(TZ).hour.to_numpy()
    print(f"world {w.T} x {w.S}, {time.time() - t0:.0f}s", flush=True)

    def ix(d):
        return int(np.searchsorted(w.times, pd.Timestamp(d, tz="UTC")))

    targets = [t for t in TARGETS if len(sys.argv) < 2 or t in sys.argv[1:]]
    report: dict = {}
    for wname, (fit_end_d, eval_start_d, eval_end_d) in WINDOWS.items():
        fit_end, eval_start, eval_end = ix(fit_end_d), ix(eval_start_d), ix(eval_end_d)
        issues = np.arange(fit_end, eval_end - HORIZON + 1, 4)
        evm = issues >= eval_start
        tgt_idx = issues[:, None] + np.arange(HORIZON)[None, :]
        hour = lt_hour[tgt_idx]
        for target in targets:
            t1 = time.time()
            mask = w.present["NR_3500"] if target == "nr" else np.ones(w.S, bool)
            y = truth(w, target, issues)
            ylog = np.log1p(y)
            sn = seasonal_naive(w, target, issues)
            week = np.broadcast_to(((tgt_idx[evm] - eval_start) // WEEK)[..., None],
                                   y[evm][..., mask].shape)
            base = Forecaster.fit(w, target, fit_end)
            lp_base = base.predict_log(w, issues)
            lp_hl = Forecaster.fit(w, target, fit_end, half_life_days=14).predict_log(w, issues)
            lp_rf = refit_predict_log(w, target, fit_end, issues, base=base)

            ctx = (ylog, hour, issues, evm, fit_end)

            def roll(lp, ctx=ctx, mask=mask, **kw):
                return cal.rolling_mondrian(lp, *ctx, sectors=mask, **kw)

            variants = {
                "base": roll(lp_base),
                "C1-med7": roll(lp_base, median_window_days=7),
                "C1-med3": roll(lp_base, median_window_days=3),
                "C2-trend": roll(lp_base, trend=True),
                "M1-hl14": roll(lp_hl),
                "M2-refit": roll(lp_rf),
                "M2+C2": roll(lp_rf, trend=True),
            }
            for vname, lp in variants.items():
                pred = {q: v[evm][..., mask] for q, v in cal.to_mb(lp).items()}
                m = metrics(pred, y[evm][..., mask], sn[evm][..., mask], week)
                report.setdefault(target, {}).setdefault(vname, {})[wname] = m
            print(f"{wname:10s} {target:4s} {time.time() - t1:5.0f}s", flush=True)

    out = RESULTS / "forecast" / "growth_experiments.json"
    old = json.loads(out.read_text()) if out.exists() else {}
    old.update(report)
    out.write_text(json.dumps(old, indent=1))
    cols = ["pinball", "pinball_p50", "pinball_p90", "skill_pct", "above_p90_pct",
            "below_p50_pct", "below_p50_wk1", "sum_bias_pct"]
    for target, rows in report.items():
        b = rows["base"]
        print(f"\n=== {target}   (inner | validation; pinball columns as % change vs base)")
        print(f"{'variant':10s} " + " ".join(f"{c[:15]:>17s}" for c in cols))
        for key, r in rows.items():
            cells = []
            for c in cols:
                if c.startswith("pinball"):
                    cells.append(" | ".join(f"{100 * (r[wn][c] / b[wn][c] - 1):+6.2f}"
                                            for wn in WINDOWS))
                else:
                    cells.append(" | ".join(f"{r[wn][c]:6.1f}" for wn in WINDOWS))
            print(f"{key:10s} " + " ".join(f"{s:>17s}" for s in cells))


if __name__ == "__main__":
    main()
