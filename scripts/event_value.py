"""Value of the unstructured channel (OVERVIEW thesis, E1): does reading the event calendar
let an LLM agent avoid congestion that the planner alone walks into?

Run: uv run python scripts/event_value.py --models otari:deepseek/deepseek-v4-flash ...
         [--clusters C01 C02 C03 C04] [--nights 2025-10-27 2025-10-28 2025-11-03]

Per episode (cluster x night, clock 22:00): three sectors the planner wants asleep between
22:30 and 00:30 get a SYNTHETIC crowd surge (yovahti.world.events) that the forecasts don't
know about; the event calendar announces it. Arms, all replayed in the simulator on the surged
traffic, same protocol (one decision at 22:00, applied through the same gate):
  planner alone  - optimise_plan applied as is
  agent x model  - energy agent with the calendar, through MCP
Validation weeks only; spend capped per provider (D20).
"""

from __future__ import annotations

import argparse
import json
import logging
import time

import anyio
import numpy as np
import pandas as pd
from mcp import Client

from yovahti.agents import roles
from yovahti.agents.evaluate import apply_plan_alone, compare_night
from yovahti.agents.llm import ChatModel, Ledger
from yovahti.agents.loop import run_agent
from yovahti.mcp_server.network import Network
from yovahti.mcp_server.server import build_server, load_validation_network
from yovahti.netcrash.standin import standin
from yovahti.paths import RESULTS
from yovahti.trust.admission import AgentIdentity
from yovahti.world.events import Event, inject

CONC = {"otari": 4, "featherless": 2}
STEPS = 24   # a full cluster needs several propose/apply pairs (I3 splits the plan)
# Event kinds (all SYNTHETIC). "match" is the experiment in FINDINGS E21, unchanged.
KINDS = {
    "match": {"clock": "22:00", "start": 2, "end": 10, "full": True, "title": "Football match ends",
              "text": "The football match at the stadium ends at {s}. About 8 000 fans leave past "
                      "sectors {sec}; expect very heavy mobile traffic there until {e}."},
    "ferry": {"clock": "04:00", "start": 6, "end": 10, "full": False, "title": "Night ferry docks",
              "text": "The night ferry from Stockholm docks at the harbour at {s}. About 2 000 "
                      "passengers walk off past sectors {sec}; expect very heavy mobile traffic "
                      "there until {e}."},
}


def episode_networks(base: Network, cluster: str, t0: int,
                     kind: str = "match") -> tuple[Network, list[Event], dict]:
    """Cluster slice at t0 with a surge on 3 sectors the planner would sleep."""
    k = KINDS[kind]
    sl = standin(base, cluster=cluster, n_sites=10)
    sl.now = t0
    plan = sl.optimise_plan("C01", 32)
    start, end = t0 + k["start"], t0 + k["end"]
    asleep: dict[str, set[str]] = {}
    for a in plan["actions"]:
        lo, hi = a["from_qh"], a["from_qh"] + a["quarter_hours"]
        if lo <= k["start"] and (hi >= k["end"] if k["full"] else hi > k["start"]):
            sec, layer = a["cell"].split("/")
            asleep.setdefault(sec, set()).add(layer)
    both = sorted(s for s, ls in asleep.items() if {"mid"} <= ls)
    chosen = both[:3]
    idx = tuple(sorted({sl.cells[f"{s}/mid"][0] for s in chosen}))
    ev = Event(k["title"], idx, start, end)
    text = k["text"].format(s=sl.time(start)[11:16], sec=", ".join(chosen), e=sl.time(end)[11:16])
    info = {"kind": kind, "sectors": chosen, "from": sl.time(start), "until": sl.time(end),
            "text": text, "window_qh": [k["start"], k["end"]]}
    return sl, [ev], info


def make_net(sl: Network, events: list[Event], calendar: list[dict]) -> Network:
    w = inject(sl.w, events, sl.wc)
    return Network(w, sl.f, now=sl.now, issue_offset=sl.issue_offset, world_cfg=sl.wc,
                   events=calendar)


async def run_episode(base, cluster, t0, models, sems, out, kind="match"):
    sl, events, info = episode_networks(base, cluster, t0, kind)
    cal = [events[0].calendar(info["text"])]
    alone = make_net(sl, events, cal)
    apply_plan_alone(alone, "C01")
    ideal = make_net(sl, events, cal)
    win = tuple(info["window_qh"])
    apply_plan_alone(ideal, "C01", keep_awake={s: win for s in info["sectors"]})
    nets = {"planner alone": alone, "planner + ideal calendar reader": ideal}
    traces = {}

    async def one(m):
        net = make_net(sl, events, cal)
        provider = m.split(":", 1)[0]
        async with sems[provider]:
            model = ChatModel(m, run=f"event:{cluster}:{t0}")
            ident = AgentIdentity("energy-agent", model=m)
            async with Client(build_server(net, ident)) as c:
                tr = await run_agent(c, model, "energy-agent",
                                     roles.ENERGY.format(cluster="C01"),
                                     roles.ENERGY_TASK.format(now=net.time(t0), cluster="C01"),
                                     max_steps=STEPS)
        nets[f"agent {m}"] = net
        traces[m] = {"outcome": tr.outcome, "tools": [s["tool"] for s in tr.tool_calls()],
                     "answer": tr.answer[:2000], "usage": tr.usage}

    async with anyio.create_task_group() as tg:
        for m in models:
            tg.start_soon(one, m)
    cmp = compare_night(nets, "C01", t0, t0 + 40)
    ev_sec = np.array(events[0].sectors)
    # congestion on the event sectors only, during the event window
    rec = {"cluster": cluster, "night": sl.time(t0)[:10], "event": info,
           "comparison": cmp, "traces": traces}
    out.append(rec)
    print(f"{cluster} {sl.time(t0)[:16]} event on {info['sectors']} ({len(ev_sec)} sectors)",
          flush=True)
    for k, r in cmp["rows"].items():
        print(f"   {k[:40]:40s} saved {r['kwh_saved_pct']:6.2f}%  congested "
              f"{r['congested_qh_per_sector_day']:.3f}/sector-day  unserved "
              f"{r['unserved_gb']:.2f} GB  wakes {r['watchdog_wakes']:.0f}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--clusters", nargs="+", default=["C01", "C02", "C03", "C04"])
    ap.add_argument("--nights", nargs="+", default=["2025-10-27", "2025-10-28", "2025-11-03"])
    ap.add_argument("--kind", choices=list(KINDS), default="match")
    a = ap.parse_args()
    for name in ("mcp", "httpx"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    t_load = time.time()
    clock = KINDS[a.kind]["clock"]
    base = load_validation_network(f"{a.nights[0]} {clock}")
    print(f"network ready in {time.time() - t_load:.0f}s", flush=True)

    def t_of(night: str) -> int:
        ts = pd.Timestamp(f"{night} {clock}").tz_localize("Europe/Bratislava").tz_convert("UTC")
        return int(np.searchsorted(base.w.times, ts))

    out: list[dict] = []

    async def go():
        sems = {p: anyio.Semaphore(n) for p, n in CONC.items()}
        async with anyio.create_task_group() as tg:
            for night in a.nights:
                for cl in a.clusters:
                    tg.start_soon(run_episode, base, cl, t_of(night), a.models, sems, out, a.kind)
    anyio.run(go)

    # aggregate over episodes: sums of congested sector-quarter-hours, unserved, mean saving
    agg: dict[str, dict] = {}
    for rec in out:
        n_sec, days = rec["comparison"]["sectors"], 40 / 96
        for k, r in rec["comparison"]["rows"].items():
            a_ = agg.setdefault(k, {"episodes": 0, "kwh_saved_pct": [], "congested_qh": 0.0,
                                    "unserved_gb": 0.0, "watchdog_wakes": 0})
            a_["episodes"] += 1
            a_["kwh_saved_pct"].append(r["kwh_saved_pct"])
            a_["congested_qh"] += r["congested_qh_per_sector_day"] * n_sec * days
            a_["unserved_gb"] += r["unserved_gb"]
            a_["watchdog_wakes"] += r["watchdog_wakes"]
    summary = {k: {**v, "kwh_saved_pct": round(float(np.mean(v["kwh_saved_pct"])), 2),
                   "congested_qh": round(v["congested_qh"], 1),
                   "unserved_gb": round(v["unserved_gb"], 2)} for k, v in agg.items()}
    print("\n== summary over", len(out), "episodes (event surges are SYNTHETIC)")
    for k, v in summary.items():
        print(f"   {k[:44]:44s} saved {v['kwh_saved_pct']:6.2f}%  congested QH "
              f"{v['congested_qh']:6.1f}  unserved {v['unserved_gb']:6.2f} GB  wakes "
              f"{v['watchdog_wakes']}  (n={v['episodes']})")
    sfx = "" if a.kind == "match" else f"-{a.kind}"
    path = RESULTS / "events" / f"{time.strftime('%Y-%m-%d')}-event-value{sfx}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"synthetic_events": True, "kind": a.kind, "models": a.models,
                                "summary": summary, "episodes": out}, indent=1,
                               ensure_ascii=False), encoding="utf-8")
    print("spent:", {p: round(Ledger().spent(p), 3) for p in ("otari", "featherless")})
    print("saved to", path)


if __name__ == "__main__":
    main()
