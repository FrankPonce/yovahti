"""Yövahti against published methods from Ericsson, Nokia, Elisa, Parallel Wireless and Reiss
et al. (reconstructions; docs/SOURCES.md), on the validation weeks, same simulator.

Learned baselines (Nokia Q-learning, Reiss-style classifier) train on the training weeks only.
Test weeks untouched (D36). Writes results/compare/industry_validation.json.

Run: uv run python scripts/industry_baselines.py
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
from compare_methods import load_forecasts
from fairness_and_throughput import active_users

from yovahti.baselines.industry import (
    ElisaDefaultPlan,
    EricssonBlogThresholds,
    Layers,
    NokiaQLearning,
    ParallelWirelessRule,
    ReissClassifier,
    train_classifier,
    train_q,
)
from yovahti.baselines.published import PublishedThresholdMethod, PublishedThresholdPlus
from yovahti.baselines.simple import Oracle, StaticThresholds, always_on
from yovahti.energy.model import SPLITS
from yovahti.paths import RESULTS
from yovahti.plan.dp import DPPlanner, PlannerConfig
from yovahti.world.data import load_world, time_slice
from yovahti.world.sim import WorldConfig, run, summarise

COLS = ["kwh_saved_pct", "congested_qh_per_sector_day", "unserved_gb", "watchdog_wakes",
        "toggles_per_sector_day", "sleep_share_mid", "sleep_share_nr"]


def main() -> None:
    t0 = time.time()
    full = load_world("all")

    def at(day):
        return int(np.searchsorted(full.times, pd.Timestamp(day, tz="UTC")))
    tr_lo, lo, hi = at(SPLITS["train"][0]), at(SPLITS["validation"][0]), at(SPLITS["test"][0])
    world = time_slice(full, lo, hi)
    fc = load_forecasts("plain", "validation")
    cfg = WorldConfig()
    layers = Layers.of(full)
    users = active_users(full, full.times[0], full.times[-1] + pd.Timedelta("15min"))
    print(f"validation {world.T} x {world.S}; full {full.T}; {time.time() - t0:.0f}s", flush=True)

    t1 = time.time()
    q = {w: train_q(layers, tr_lo, lo, cfg, weight=w) for w in (1.0, 10.0, 30.0, 100.0)}
    clf = train_classifier(layers, tr_lo, lo)
    print(f"trained Q-tables and classifiers in {time.time() - t1:.0f}s", flush=True)

    def planner(**kw):
        return DPPlanner(world, fc, PlannerConfig(**kw), cfg, issue_offset=lo)
    low_tr = layers.low[tr_lo:lo]
    methods = {
        "B0 always-on": always_on,
        "B1 static thresholds": StaticThresholds(),
        "B2 Ericsson published (patent + blog)": PublishedThresholdMethod(world, fc, lo, cfg),
        "B2b Ericsson as in the 2023 blog (PRB + users, daily)":
            EricssonBlogThresholds(world, fc, lo, users=users, user_offset=lo),
        "B2+ Ericsson + our predictive wake": PublishedThresholdPlus(world, fc, lo, cfg,
                                                                     wake_low_above=20.0),
        "Elisa default plan (01-06, load <= 10 %)": ElisaDefaultPlan(world),
        "Parallel Wireless 2-h near-zero rule + rollback":
            ParallelWirelessRule(world, fc, lo, low_mean=low_tr.mean(0), low_sd=low_tr.std(0)),
    }
    for w, tab in q.items():
        methods[f"Nokia Q-learning (weight {w:g})"] = NokiaQLearning(layers, lo, tab)
    for tau in (0.5, 0.9, 0.97, 0.99, 0.995):
        methods[f"Reiss-style classifier (tau {tau:g})"] = ReissClassifier(layers, lo, clf, tau)
    methods.update({
        "B4 Yovahti (P90, default)": planner(),
        "B4 Yovahti on P50": planner(risk_q=0.5),
        "B4 Yovahti careful (margin 1.5)": planner(margin=1.5),
        "Oracle (perfect foresight)": Oracle(world, cfg),
    })
    rows, b0 = {}, None
    for name, pol in methods.items():
        t2 = time.time()
        r = run(world, pol, name, cfg)
        b0 = b0 or r
        rows[name] = summarise(world, r, b0)
        print(f"  {name:55s} {time.time() - t2:5.1f}s", flush=True)
    oracle = rows["Oracle (perfect foresight)"]["kwh_saved_pct"]
    print(f"\n{'method':55s} {'saved':>7s} {'%oracle':>8s} {'cong/sd':>8s} {'unserv GB':>10s}"
          f" {'wakes':>7s} {'toggles':>8s}")
    for name, s in rows.items():
        s["share_of_oracle_pct"] = round(100 * s["kwh_saved_pct"] / oracle, 1) if oracle else None
        print(f"{name:55s} {s['kwh_saved_pct']:7.2f} {s['share_of_oracle_pct'] or 0:8.1f} "
              f"{s['congested_qh_per_sector_day']:8.3f} {s['unserved_gb']:10.1f} "
              f"{s['watchdog_wakes']:7.0f} {s['toggles_per_sector_day']:8.2f}")
    out = RESULTS / "compare" / "industry_validation.json"
    out.write_text(json.dumps({"split": "validation", "methods":
                               {k: {c: v.get(c) for c in COLS + ["share_of_oracle_pct"]}
                                for k, v in rows.items()}}, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
