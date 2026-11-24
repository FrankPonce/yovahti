"""One night end to end: an LLM energy agent acts on a cluster through MCP; then the simulator
replays what it applied, next to B0, the planner alone (same protocol) and rolling B4.

Run: uv run python scripts/run_agent_night.py --model otari:deepseek/deepseek-v4-flash
         [--cluster C01] [--start "2025-10-27 22:00"] [--hours 10] [--steps 16]
Validation weeks only (test weeks untouched). Spend is capped per provider (D20).
"""

from __future__ import annotations

import argparse
import json
import re
import time

import anyio
from mcp import Client

from yovahti.agents import roles
from yovahti.agents.evaluate import apply_plan_alone, compare_night
from yovahti.agents.llm import ChatModel, Ledger
from yovahti.agents.loop import run_agent
from yovahti.mcp_server.network import Network
from yovahti.mcp_server.server import build_server, load_validation_network
from yovahti.paths import RESULTS
from yovahti.trust.admission import AgentIdentity


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="provider:model-id")
    ap.add_argument("--cluster", default="C01")
    ap.add_argument("--start", default="2025-10-27 22:00")
    ap.add_argument("--hours", type=int, default=10)
    ap.add_argument("--steps", type=int, default=16)
    a = ap.parse_args()
    t_load = time.time()
    net = load_validation_network(a.start)
    alone = Network(net.w, net.f, now=net.now, issue_offset=net.issue_offset)
    t0, t1 = net.now, min(net.w.T, net.now + 4 * a.hours)
    print(f"network ready in {time.time() - t_load:.0f}s; now {net.time(t0)}", flush=True)

    run_id = f"{a.start[:10]}_{a.cluster}_{re.sub(r'[^A-Za-z0-9.-]+', '-', a.model)}"
    model = ChatModel(a.model, run=run_id)
    agent = AgentIdentity("energy-agent", model=a.model)
    system = roles.ENERGY.format(cluster=a.cluster)
    task = roles.ENERGY_TASK.format(now=net.time(t0), cluster=a.cluster)

    async def go():
        async with Client(build_server(net, agent)) as c:
            return await run_agent(c, model, "energy-agent", system, task, max_steps=a.steps)
    trace = anyio.run(go)
    apply_plan_alone(alone, a.cluster)
    cmp = compare_night({f"Agent {a.model}": net, "Planner alone (same protocol)": alone},
                        a.cluster, t0, t1)

    changes = {cid: {"status": ch.status, "reasons": ch.reasons, "n_actions": len(ch.actions)}
               for cid, ch in net.changes.items()}
    out = {"run": run_id, "prompt_version": roles.PROMPT_VERSION, "trace": trace.to_json(),
           "changes": changes, "comparison": cmp,
           "spent_eur_total": {p: round(Ledger().spent(p), 4) for p in ("otari", "featherless")}}
    path = RESULTS / "agents" / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"\noutcome {trace.outcome} after {len(trace.steps)} steps, "
          f"{len(trace.tool_calls())} tool calls, {trace.seconds}s, "
          f"{trace.usage.get('prompt_tokens', 0)}+{trace.usage.get('completion_tokens', 0)} "
          f"tokens, EUR {trace.usage.get('cost_eur', 0):.4f}")
    print("tools:", " ".join(s["tool"] + ("!" if s["is_error"] else "")
                             for s in trace.tool_calls()))
    print("changes:", {k: (v["status"], v["n_actions"]) for k, v in changes.items()})
    print(f"\n{cmp['sectors']} sectors, {cmp['from']} -> {cmp['until']}, B0 {cmp['b0_kwh']} kWh")
    cols = list(next(iter(cmp["rows"].values())))
    print(f"{'':34s}" + "".join(f"{c[:14]:>15s}" for c in cols))
    for k, r in cmp["rows"].items():
        print(f"{k[:34]:34s}" + "".join(f"{r[c]:15.3f}" for c in cols))
    print("\nanswer:", trace.answer[:1500])
    print(f"\nsaved to {path}")


if __name__ == "__main__":
    main()
