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
    return {"period": "validation weeks 26 Oct – 8 Nov 2025", "sectors": 749,
            "methods": methods, "margin_curve": curve,
            "cat2_b4_kwh_saved_pct": round(cat2["methods"]["B4 Yovahti planner (P90, energy)"]
                                           ["kwh_saved_pct"], 2),
            "forecast_skill_pct": {t: round(fc[t]["skill_vs_seasonal_naive_pct"], 1)
                                   for t in ("mid", "nr", "low")},
            "forecast_coverage_pct": {t: round(fc[t]["coverage_p10_p90_pct"], 1)
                                      for t in ("mid", "nr", "low")}}


def netcrash() -> dict:
    out = []
    for p in latest("netcrash/*-agent-*.json"):
        if "-n20-" in p:
            continue
        d = read(p)
        out.append({"agent": d["target"]["agent_card"]["id"], "model": d["model"]["name"],
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
    return {"scorecards": out, "n20": n20,
            "attestation": read(att[0]) if att else None,
            "jwks": json.loads((ROOT / "trust" / "tester.jwks.json").read_text())
            if (ROOT / "trust" / "tester.jwks.json").exists() else None}


def events() -> dict | None:
    files = latest("events/*-event-value.json")
    if not files:
        return None
    d = read(files[-1])
    return {"synthetic_events": True, "summary": d["summary"],
            "episodes": len(d["episodes"]), "models": d["models"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay-model", default=None)
    a = ap.parse_args()
    logging.getLogger("mcp").setLevel(logging.CRITICAL)
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    WEB.mkdir(parents=True, exist_ok=True)
    data = {"results": results_summary(), "netcrash": netcrash(), "events": events()}
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
