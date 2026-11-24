"""One event night, recorded quarter by quarter for the dashboard's replay.

Cluster C01, 27 Oct 2025 22:00 to 08:00, SYNTHETIC crowd surge on three sectors (see
yovahti.world.events). Two arms through the same gate: the planner alone, and the energy
agent reading the calendar. Used by scripts/export_dashboard.py --replay-model.
"""

from __future__ import annotations

import anyio
from event_value import STEPS, episode_networks, make_net
from mcp import Client

from yovahti.agents import roles
from yovahti.agents.evaluate import _schedule_policy, apply_plan_alone, cluster_sectors
from yovahti.agents.llm import ChatModel
from yovahti.agents.loop import run_agent
from yovahti.baselines.simple import always_on
from yovahti.mcp_server.server import build_server, load_validation_network
from yovahti.trust.admission import AgentIdentity
from yovahti.world.data import time_slice
from yovahti.world.sim import run, summarise


def replay_episode(model: str, night: str = "2025-10-27", cluster: str = "C01") -> dict:
    base = load_validation_network(f"{night} 22:00")
    t0 = base.now
    sl, events, info = episode_networks(base, cluster, t0)
    cal = [events[0].calendar(info["text"])]
    alone = make_net(sl, events, cal)
    apply_plan_alone(alone, "C01")
    agent = make_net(sl, events, cal)

    async def go():
        async with Client(build_server(agent, AgentIdentity("energy-agent", model=model))) as c:
            return await run_agent(c, ChatModel(model, run="dashboard-replay"), "energy-agent",
                                   roles.ENERGY.format(cluster="C01"),
                                   roles.ENERGY_TASK.format(now=agent.time(t0), cluster="C01"),
                                   max_steps=STEPS)
    tr = anyio.run(go)
    t1 = t0 + 40
    sectors = cluster_sectors(alone, "C01")
    w = time_slice(alone.w, t0, t1).subset(sectors)
    b0 = run(w, always_on, "B0", alone.wc)
    arms = {}
    for name, net in (("Planner alone", alone), ("Agent reading the calendar", agent)):
        r = run(w, _schedule_policy(net, sectors, t0, t1), name, alone.wc)
        s = summarise(w, r, b0)
        arms[name] = {"mid": r.mid_state.T.tolist(), "nr": r.nr_state.T.tolist(),
                      "congested": r.congested.T.astype(int).tolist(),
                      "kwh_saved_pct": round(s["kwh_saved_pct"], 2),
                      "congested_qh": int(r.congested.sum()),
                      "unserved_gb": round(s["unserved_gb"], 2)}
    names = [f"s{w.sectors[i].split(' ')[1].replace('/', '-')}" if " " in w.sectors[i]
             else w.sectors[i] for i in range(w.S)]
    ev_idx = [names.index(s) for s in info["sectors"] if s in names]
    calls = [{"tool": s["tool"], "error": s["is_error"],
              "args": {k: (v if len(str(v)) < 80 else str(v)[:77] + "...")
                       for k, v in s["args"].items()},
              "result": s["result"][:240]} for s in tr.tool_calls()]
    return {"night": night, "cluster": cluster, "model": model, "synthetic_event": info,
            "times": [alone.time(t)[11:16] for t in range(t0, t1)], "sectors": names,
            "has_nr": [bool(x) for x in w.present["NR_3500"]], "event_sectors": ev_idx,
            "event_window": [2, 10], "arms": arms, "agent_calls": calls,
            "agent_answer": tr.answer[:4000], "agent_outcome": tr.outcome,
            "agent_usage": tr.usage, "b0_kwh": round(float(b0.total_wh().sum() / 1000), 1)}
