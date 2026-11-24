"""B2+ (fairer published method, I14) and a per-user throughput proxy (I29), validation weeks.

Run: uv run python scripts/fairness_and_throughput.py
Test weeks are locked and never touched (D36).

Throughput proxy: capacity per active downlink user, in Mbit/s, = the layer's full capacity
(MB per quarter-hour at 100 % load, x 8 / 900 s) / active DL users on it. For every
sector-quarter-hour where a capacity layer sleeps, the moved users' proxy *before* is what
their own layer offered; *after* is what the receiving layer offers with everyone on it.
Users counted from the operator's "active users DL" counter (per carrier, 15-min average).
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
from compare_methods import load_forecasts

from yovahti.baselines.published import PublishedThresholdMethod, PublishedThresholdPlus
from yovahti.baselines.simple import always_on
from yovahti.energy.model import SPLITS
from yovahti.paths import PROCESSED, RESULTS
from yovahti.plan.dp import DPPlanner, PlannerConfig
from yovahti.world.data import BANDWIDTH, EFFICIENCY, LOW, _fill, _pivot, load_world, time_slice
from yovahti.world.sim import ASLEEP, WorldConfig, run, summarise

MID = ["LTE_1800", "NR_2100"]


def active_users(world, lo_ts, hi_ts) -> dict[str, np.ndarray]:
    out = {}
    for c in ["LTE_700", "LTE_800", "LTE_1800", "NR_2100", "NR_3500"]:
        d = pd.read_parquet(PROCESSED / "slovak" / f"Dataset_03_{c}.parquet",
                            columns=["site", "sector", "time", "active_dl"])
        d = d[(d["time"] >= lo_ts) & (d["time"] < hi_ts)]
        d["unit_id"] = d["site"].astype(str) + "/" + d["sector"].astype(str)
        raw = _pivot(d, "active_dl", world.times, world.sectors)
        a, _ = _fill(np.where(raw > 1e6, np.nan, raw))       # float-max sentinels (G30)
        out[c] = np.where(world.present[c], np.nan_to_num(a), 0.0)
    return out


def mbps(world, carriers) -> np.ndarray:
    cap = sum(world.present[c] * EFFICIENCY[c] * BANDWIDTH[c] for c in carriers)   # MB/qh per %
    return cap * 100 * 8 / 900


def proxy(world, r, users) -> dict:
    low_cap, mid_cap, nr_cap = mbps(world, LOW), mbps(world, MID), mbps(world, ["NR_3500"])
    u_low = users["LTE_700"] + users["LTE_800"]
    u_mid = users["LTE_1800"] + users["NR_2100"]
    u_nr = users["NR_3500"]
    ms, ns = r.mid_state == ASLEEP, r.nr_state == ASLEEP
    before, after, w = [], [], []
    # mid asleep: mid users (and NR users if NR also sleeps) land on the low band
    moved = u_mid + np.where(ns, u_nr, 0.0)
    sel = ms & (moved > 0.05)
    b = np.where(sel, mid_cap[None] / np.maximum(u_mid + np.where(ns, 0, 0), 1e-3), np.nan)
    a = np.where(sel, low_cap[None] / np.maximum(u_low + moved, 1e-3), np.nan)
    before.append(b[sel]), after.append(a[sel]), w.append(moved[sel])
    # only NR asleep: NR users land on the mid band
    sel = ns & ~ms & (u_nr > 0.05)
    b = np.where(sel, nr_cap[None] / np.maximum(u_nr, 1e-3), np.nan)
    a = np.where(sel, mid_cap[None] / np.maximum(u_mid + u_nr, 1e-3), np.nan)
    before.append(b[sel]), after.append(a[sel]), w.append(u_nr[sel])
    b, a, w = (np.concatenate(x) for x in (before, after, w))
    if not len(w):
        return {"moved_user_qh": 0}
    ratio = a / b

    def wq(x, q):
        o = np.argsort(x)
        cw = np.cumsum(w[o]) / w.sum()
        return float(x[o][np.searchsorted(cw, q)])
    return {"moved_user_qh": float(w.sum()),
            "after_mbps_median": round(wq(a, 0.5), 2), "after_mbps_p10": round(wq(a, 0.1), 2),
            "before_mbps_median": round(wq(b, 0.5), 2),
            "ratio_median": round(wq(ratio, 0.5), 3), "ratio_p10": round(wq(ratio, 0.1), 3),
            "share_below_5mbps": round(float(w[a < 5].sum() / w.sum()), 4)}


def main() -> None:
    t0 = time.time()
    full = load_world("all")
    lo_ts, hi_ts = (pd.Timestamp(SPLITS[s][0], tz="UTC") for s in ("validation", "test"))
    lo, hi = (int(np.searchsorted(full.times, x)) for x in (lo_ts, hi_ts))
    world = time_slice(full, lo, hi)
    fc = load_forecasts("plain", "validation")
    cfg = WorldConfig()
    users = active_users(world, lo_ts, hi_ts)
    print(f"validation {world.T} x {world.S}, users loaded, {time.time() - t0:.0f}s", flush=True)
    methods = {"B0 always-on": always_on,
               "B2 published method (reconstruction)": PublishedThresholdMethod(world, fc, lo,
                                                                                cfg)}
    for q in (0.5, 0.9):
        for wake in (20.0, 25.0, 30.0):
            methods[f"B2+ predictive wake P{int(q * 100)}, wake {wake:.0f}%"] = \
                PublishedThresholdPlus(world, fc, lo, cfg, wake_low_above=wake, wake_q=q)
    methods["B4 Yovahti planner (P90)"] = DPPlanner(world, fc, PlannerConfig(), cfg,
                                                    issue_offset=lo)
    methods["B4 on P50"] = DPPlanner(world, fc, PlannerConfig(risk_q=0.5), cfg, issue_offset=lo)
    rows, b0 = {}, None
    for name, pol in methods.items():
        r = run(world, pol, name, cfg)
        b0 = b0 or r
        s = summarise(world, r, b0)
        s["throughput"] = proxy(world, r, users) if name != "B0 always-on" else {}
        rows[name] = s
        tp = s["throughput"]
        print(f"{name:42s} saved {s.get('kwh_saved_pct', 0):5.1f} % | congested "
              f"{s['congested_qh_per_sector_day']:.2f}/sector-day | unserved "
              f"{s['unserved_gb'] / 1000:5.2f} TB | moved users' Mbps median "
              f"{tp.get('after_mbps_median', '-')} (P10 {tp.get('after_mbps_p10', '-')}), "
              f"x{tp.get('ratio_median', '-')} of before", flush=True)
    out = RESULTS / "compare" / "fairness_throughput_validation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
