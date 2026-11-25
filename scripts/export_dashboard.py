"""Export everything the static dashboard shows into web/data/ (D10: static JSON, no backend).

Run: uv run python scripts/export_dashboard.py [--replay-model otari:deepseek/deepseek-v4-flash]
Reads the committed results (compare, forecast, events, netcrash, attestations). With
--replay-model it also re-runs ONE event episode (cluster C01, 27 Oct 22:00, synthetic surge)
for the night replay: per sector and quarter-hour, the state of each radio and congestion,
for the planner alone and the agent, plus the agent's tool calls (costs about EUR 0.05).
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
from pathlib import Path

from yovahti.paths import RESULTS, ROOT

WEB = ROOT / "web" / "data"


def read(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def latest(pattern: str) -> list[str]:
    return sorted(glob.glob(str(RESULTS / pattern)))


def results_summary() -> dict:
    cmp = json.loads((RESULTS / "compare" / "validation_cat1.json").read_text())
    cat2 = json.loads((RESULTS / "compare" / "validation_cat2.json").read_text())
    fc = json.loads((RESULTS / "forecast" / "validation_report.json").read_text())
    keep = {"B1 static thresholds": "B1 static thresholds",
            "B2 published method (reconstruction)": "B2 published method (reconstruction)",
            "B3 O-RAN SC demo rApp": "B3 O-RAN SC rApp logic",
            "B4 Yovahti planner (P90, energy)": "B4 Yövahti planner",
            "Ablation: B4 on P50 (no risk)": "B4 on P50 (ablation)",
            "Oracle (perfect foresight)": "Oracle (perfect foresight)"}
    cols = ("kwh_saved_pct", "congested_qh_per_sector_day", "unserved_gb", "watchdog_wakes",
            "capacity_radio_saved_pct")
    methods = [{"name": v, **{c: round(cmp["methods"][k][c], 3) for c in cols}}
               for k, v in keep.items()]
    curve = [{"margin": float(m), **{c: round(s[c], 3) for c in cols}}
             for m, s in cmp["margin_curve"].items()]
    b0k = cmp["methods"]["B0 always-on"]
    b4k = cmp["methods"]["B4 Yovahti planner (P90, energy)"]
    energy = {"b0_kwh": round(b0k["kwh"]), "b4_kwh_saved": round(b0k["kwh"] - b4k["kwh"]),
              "b4_kwh_per_sector_day": round(b4k["kwh_saved_per_sector_day"], 2),
              "b4_co2_saved_kg": round(b0k["kg_co2"] - b4k["kg_co2"]),
              "b4_eur_saved": round(b0k["eur"] - b4k["eur"]), "days": 14}
    return {"period": "validation weeks 26 Oct – 8 Nov 2025", "sectors": 749, "energy": energy,
            "methods": methods, "margin_curve": curve,
            "cat2_b4_kwh_saved_pct": round(cat2["methods"]["B4 Yovahti planner (P90, energy)"]
                                           ["kwh_saved_pct"], 2),
            "forecast_skill_pct": {t: round(fc[t]["skill_vs_seasonal_naive_pct"], 1)
                                   for t in ("mid", "nr", "low")},
            "forecast_coverage_pct": {t: round(fc[t]["coverage_p10_p90_pct"], 1)
                                      for t in ("mid", "nr", "low")}}


def netcrash() -> dict:
    """Newest suite version per agent x model (v1 cards stay where no v2 run exists, labelled).
    Below the admission coverage bar (80 %) a pair is "not measurable", not scored 0."""
    best: dict[tuple[str, str], dict] = {}
    modes = []
    for p in latest("netcrash/*-v2[clw]-*.json"):
        if p.endswith("matrix.md"):
            continue
        d = read(p)
        modes.append({"agent": d["target"]["agent_card"]["id"], "model": d["model"]["name"],
                      "score": d["summary"]["score"], "coverage": d["summary"]["coverage"],
                      "cost_eur": d["summary"]["cost_eur"],
                      "decided": sum(t["verdict"] in ("pass", "fail", "flaky")
                                     for t in d["tests"]),
                      "failed": [t["id"] for t in d["tests"] if t["verdict"] in ("fail", "flaky")]})
    for p in latest("netcrash/*-agent-*.json"):
        if "-n20-" in p or "-v2c-" in p or "-v2l-" in p or "-v2w-" in p:   # see "modes"
            continue
        d = read(p)
        key = (d["target"]["agent_card"]["id"], d["model"]["name"])
        if key not in best or d["suite"]["version"] >= best[key]["suite"]["version"]:
            best[key] = d
    out = []
    for d in best.values():
        runs = [r for t in d["tests"] for r in t["runs"]]
        errors = sum(r.get("verdict") == "error" for r in runs)
        out.append({"agent": d["target"]["agent_card"]["id"], "model": d["model"]["name"],
                    "suite": d["suite"]["version"], "runs": len(runs), "errors": errors,
                    "measurable": d["summary"]["coverage"] >= 80,   # the admission coverage bar
                    "score": d["summary"]["score"], "coverage": d["summary"]["coverage"],
                    "cost_eur": d["summary"]["cost_eur"],
                    "card_sha256": d["target"]["network_sha256"],
                    "tests": [{"id": t["id"], "title": t["title"], "verdict": t["verdict"],
                               "pass_rate": t["pass_rate"],
                               "evidence": [r.get("evidence", "") for r in t["runs"]]}
                              for t in d["tests"]]})
    n20 = []
    for p in latest("netcrash/*-n20-*-agent-*.json"):
        d = read(p)
        t = d["tests"][0]
        n20.append({"agent": d["target"]["agent_card"]["id"], "model": d["model"]["name"],
                    "verdict": t["verdict"], "pass_rate": t["pass_rate"]})
    att = latest("netcrash/attestations/*.dsse.json")
    return {"scorecards": out, "n20": n20, "modes": modes,
            "attestation": read(att[0]) if att else None,
            "jwks": json.loads((ROOT / "trust" / "tester.jwks.json").read_text())
            if (ROOT / "trust" / "tester.jwks.json").exists() else None}


def events() -> dict:
    out = {}
    pats = (("match", "events/*-event-value.json"), ("ferry", "events/*-event-value-ferry.json"))
    for kind, pat in pats:
        files = latest(pat)
        if files:
            d = read(files[-1])
            out[kind] = {"synthetic_events": True, "summary": d["summary"],
                         "episodes": len(d["episodes"]), "models": d["models"]}
    return out


def how_it_works(night: str = "2025-10-27") -> dict:
    """One real sector, one real night: forecast, P90 check, chosen sleep schedule (scene 03)."""
    import numpy as np

    from yovahti.forecast.quantile import HORIZON
    from yovahti.mcp_server.server import load_validation_network
    from yovahti.plan.dp import STATES

    net = load_validation_network(f"{night} 22:00")
    t0, k = net.now, net.latest_issue()
    lag = t0 - (int(net.f["mid"]["issues"][k]) - net.issue_offset)
    pl, wc = net.planner, net.wc
    n = HORIZON - lag
    cost = net.costs(k)[lag:lag + n]
    path = pl.solve(cost, np.zeros(net.w.S, dtype=np.int64))
    h = np.arange(lag, lag + n)

    def q(t, qq, s=slice(None)):
        return net.f[t][qq][k][h][:, s].astype(float)

    cap = np.where(pl.cap_low > 0, pl.cap_low, np.inf)
    moved90 = (q("low", 0.9) + q("mid", 0.9) + q("nr", 0.9)) / cap * wc.peak_margin
    both = (STATES[path, 0] == 1) & (STATES[path, 1] == 1)
    crosses = (moved90 > wc.rho_max_low).any(axis=0)
    sleeps = both.sum(axis=0)
    wakes_in_time = ~(both & (moved90 > wc.rho_max_low)).any(axis=0)
    ok = net.w.present["NR_3500"] & crosses & wakes_in_time & (sleeps >= 16)
    s = int(np.argmax(np.where(ok, sleeps, -1)))
    j = s
    moved = {qq: (q("low", qq, s) + q("mid", qq, s) + q("nr", qq, s)) / cap[s] * wc.peak_margin
             for qq in (0.1, 0.5, 0.9)}
    total = {qq: q("low", qq, s) + q("mid", qq, s) + q("nr", qq, s) for qq in (0.1, 0.5, 0.9)}
    name = net.w.sectors[s]
    label = f"s{name.split(' ')[1].replace('/', '-')}" if " " in name else name
    return {"night": night, "sector": label,
            "times": [net.time(t0 + i)[11:16] for i in range(n)],
            "traffic_mb": {f"p{int(qq * 100)}": [round(v, 1) for v in total[qq]] for qq in total},
            "coverage_load_if_asleep_pct": {f"p{int(qq * 100)}": [round(v, 1) for v in moved[qq]]
                                            for qq in moved},
            "limit_pct": wc.rho_max_low,
            "mid_asleep": [int(x) for x in STATES[path[:, j], 0]],
            "nr_asleep": [int(x) for x in STATES[path[:, j], 1]]}


def energy_split() -> dict:
    """Radio energy by radio type, always-on vs B4, validation weeks (scene 02's bars)."""
    import numpy as np
    import pandas as pd

    from yovahti.baselines.simple import always_on
    from yovahti.energy.model import SPLITS
    from yovahti.forecast.quantile import TARGETS
    from yovahti.paths import PROCESSED
    from yovahti.plan.dp import DPPlanner, PlannerConfig
    from yovahti.world.data import load_world, time_slice
    from yovahti.world.sim import WorldConfig, run

    full = load_world("all")
    lo = int(np.searchsorted(full.times, pd.Timestamp(SPLITS["validation"][0], tz="UTC")))
    hi = int(np.searchsorted(full.times, pd.Timestamp(SPLITS["test"][0], tz="UTC")))
    world = time_slice(full, lo, hi)
    fc = {}
    for t in TARGETS:
        z = np.load(PROCESSED / "forecasts" / f"validation_{t}.npz")
        fc[t] = {"issues": z["issues"], 0.1: z["q10"], 0.5: z["q50"], 0.9: z["q90"]}
    cfg = WorldConfig()
    b0 = run(world, always_on, "B0", cfg)
    b4 = run(world, DPPlanner(world, fc, PlannerConfig(), cfg, issue_offset=lo), "B4", cfg)

    def kwh(r):
        return {"coverage": float(r.energy["low"].sum() / 1e3),
                "capacity": float((r.energy["mid"].sum() + r.energy["nr3500"].sum()) / 1e3)}
    return {"always_on": kwh(b0), "yovahti": kwh(b4)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay-model", default=None)
    ap.add_argument("--how", action="store_true",
                    help="recompute the how-it-works sector (loads the world)")
    a = ap.parse_args()
    logging.getLogger("mcp").setLevel(logging.CRITICAL)
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    WEB.mkdir(parents=True, exist_ok=True)
    data = {"results": results_summary(), "netcrash": netcrash(), "events": events()}
    ind = RESULTS / "compare" / "industry_validation.json"
    if ind.exists():                                   # other companies' methods (E41, D47)
        data["industry"] = json.loads(ind.read_text())["methods"]
    if a.how:
        data["how"] = how_it_works()
        data["split"] = energy_split()
    elif (WEB / "dashboard.json").exists():
        old = json.loads((WEB / "dashboard.json").read_text(encoding="utf-8"))
        for key in ("how", "split"):
            if old.get(key):
                data[key] = old[key]
    if a.replay_model:
        from replay_episode import replay_episode
        data["replay"] = replay_episode(a.replay_model)
    elif (WEB / "dashboard.json").exists():
        old = json.loads((WEB / "dashboard.json").read_text(encoding="utf-8"))
        if old.get("replay"):
            data["replay"] = old["replay"]
    (WEB / "dashboard.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print("wrote", WEB / "dashboard.json", {k: bool(v) for k, v in data.items()})


if __name__ == "__main__":
    main()
