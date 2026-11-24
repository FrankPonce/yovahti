"""Does the forecaster generalise to another city, operator and decade? (S4 stretch)

Milan, Telecom Italia Big Data Challenge (Nov-Dec 2013, CC BY / ODbL, I7): internet activity
per 235 m grid square, 10-minute slots. Activity is a relative index, not MB (G13), so this
tests the *method* (same features, same LightGBM quantile model, same conformal calibration,
untouched hyper-parameters), not the energy numbers. 10-minute slots are resampled to
quarter-hours through the cumulative activity. A seeded sample of squares keeps it light.

Windows: fit before 27 Nov, calibrate 27 Nov - 4 Dec, score 4-18 Dec (normal weeks) and
18 Dec - 1 Jan (holidays: a hard, honest case). Metric as for Slovakia (fit_forecaster.py):
P50 skill vs seasonal naive (same quarter-hour a week earlier) and P10-P90 coverage.

Run: uv run python scripts/milan_generalisation.py [--squares 800]
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd

from yovahti.forecast.quantile import HORIZON, Forecaster, calibrate, seasonal_naive, truth
from yovahti.paths import PROCESSED, RESULTS
from yovahti.world.data import CARRIERS, WorldData

TZ = "Europe/Rome"


def load_milan(n_squares: int, seed: int = 0) -> WorldData:
    files = sorted((PROCESSED / "milan").glob("*.parquet"))
    rng = np.random.default_rng(seed)
    squares = np.sort(rng.choice(np.arange(1, 10001), n_squares, replace=False))
    parts = []
    for f in files:
        d = pd.read_parquet(f, columns=["square_id", "time", "internet"])
        parts.append(d[d["square_id"].isin(squares)])
    d = pd.concat(parts)
    d = d.groupby(["time", "square_id"])["internet"].sum().unstack().reindex(columns=squares)
    d = d.sort_index().fillna(0.0)
    # 10-min -> 15-min through the cumulative activity (piecewise-linear within a slot)
    t10 = d.index
    cum = np.vstack([np.zeros((1, d.shape[1])), np.cumsum(d.to_numpy(), axis=0)])
    edges = np.concatenate([t10.asi8, [t10.asi8[-1] + 600 * 10**9]])
    t15 = pd.date_range(t10[0].ceil("15min"), t10[-1].floor("15min"), freq="15min")
    c15 = np.column_stack([np.interp(t15.asi8, edges, cum[:, j]) for j in range(cum.shape[1])])
    vol = np.diff(c15, axis=0)
    times = t15[:-1]
    T, S = vol.shape  # noqa: N806
    z = np.zeros((T, S))
    return WorldData(times=times, sectors=[f"sq{s}" for s in squares],
                     util={c: z for c in CARRIERS},
                     vol={c: (vol if c == "LTE_1800" else z) for c in CARRIERS},
                     present={c: np.full(S, c == "LTE_1800") for c in CARRIERS},
                     gsm_util=z, idle={}, slopes={}, measured_energy={},
                     price=np.zeros(T), co2=np.zeros(T))


def score(world, f, a, b) -> dict:
    issues = np.arange(a, b - HORIZON + 1, 8)
    pred = f.predict_many(world, issues)
    y = truth(world, "mid", issues)
    sn = seasonal_naive(world, "mid", issues)
    mae = np.abs(pred[0.5] - y).mean()
    return {"skill_vs_seasonal_naive_pct": round(float(100 * (1 - mae / np.abs(sn - y).mean())),
                                                 1),
            "coverage_p10_p90_pct": round(float(100 * ((y >= pred[0.1]) &
                                                         (y <= pred[0.9])).mean()), 1),
            "above_p90_pct": round(float(100 * (y > pred[0.9]).mean()), 1),
            "issues": int(len(issues))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--squares", type=int, default=800)
    a = ap.parse_args()
    t0 = time.time()
    w = load_milan(a.squares)

    def at(day: str) -> int:
        return int(np.searchsorted(w.times, pd.Timestamp(day, tz=TZ).tz_convert("UTC")))
    fit_end, cal_end, mid, end = at("2013-11-27"), at("2013-12-04"), at("2013-12-18"), w.T
    print(f"Milan {w.T} quarter-hours x {w.S} squares in {time.time() - t0:.0f}s", flush=True)
    out = {"squares": w.S}
    for norm in (False, True):
        f = Forecaster.fit(w, "mid", fit_end, level_norm=norm)
        calibrate(f, w, fit_end, cal_end)
        key = "level_norm" if norm else "plain"
        out[key] = {"normal_weeks_4_18_dec": score(w, f, cal_end, mid),
                    "holidays_18_dec_1_jan": score(w, f, mid, end)}
        print(key, json.dumps(out[key]), flush=True)
    path = RESULTS / "forecast" / "milan_generalisation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
