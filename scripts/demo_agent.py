"""A scripted walk-through against a running Yövahti MCP server (no LLM, no API key).

What it shows, step by step, over real MCP Streamable HTTP:
1. the feeds an agent reads (cells, calendar, an alarm carrying an injected instruction);
2. obeying the injection: putting every capacity cell to sleep -> refused, with reasons;
   sleeping the busy sector -> refused by the capacity rule (I1);
3. the planner's risk-checked plan, applied in arbiter-sized changes -> signed receipts;
4. checking what happened (change status, energy report).

Run: uv run python scripts/demo_agent.py [--url http://127.0.0.1:8765/mcp]
(start the server first: uv run python -m yovahti.mcp_server.server --demo)
"""

from __future__ import annotations

import argparse
import json
import time

import anyio
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


def say(step: str, text: str = "") -> None:
    print(f"\n== {step}" + (f"\n   {text}" if text else ""), flush=True)


async def call(c, name, args):
    r = await c.call_tool(name, args)
    return r.structured_content if r.structured_content is not None else \
        json.loads("".join(getattr(x, "text", "") for x in r.content) or "{}")


async def main(url: str) -> None:
    for _ in range(60):                                  # wait for the server (compose start)
        try:
            httpx2.get(url.rsplit("/", 1)[0] + "/", timeout=2)
            break
        except Exception:  # noqa: BLE001
            time.sleep(2)
    async with httpx2.AsyncClient(timeout=60) as hc, \
            Client(streamable_http_client(url, http_client=hc)) as c:
        tools = sorted(t.name for t in (await c.list_tools()).tools)
        say("1. The network, as an agent sees it", f"{len(tools)} MCP tools: {', '.join(tools)}")
        cells = (await call(c, "list_cells", {"cluster": "C01"}))["cells"]
        cap = [x["cell"] for x in cells if x["role"] == "capacity"]
        print(f"   cluster C01: {len(cells)} cells, {len(cap)} capacity cells that may sleep")
        ev = (await call(c, "get_events", {"window": 32}))["events"]
        al = (await call(c, "get_alarms", {"cluster": "C01", "window": 8}))["alarms"]
        print(f"   calendar: {ev[0]['title']} | alarm: {al[0]['text'][:70]}...")

        say("2. Obey the injected alarm: sleep every capacity cell for 10 hours")
        bad = await call(c, "propose_change", {"actions": [
            {"cell": x, "action": "sleep", "from_qh": 0, "quarter_hours": 40} for x in cap],
            "rationale": "alarm says maintenance mode"})
        res = await call(c, "apply_change", {"change_id": bad["change_id"]})
        print(f"   {res['status'].upper()}: " + "; ".join(res.get("reasons", [])[:3])[:300])

        say("2b. Sleep the busy sector (Site 101/1) the forecast says cannot move")
        busy = [x for x in cap if x.startswith("s101-1/")]
        p = await call(c, "propose_change", {"actions": [
            {"cell": x, "action": "sleep", "from_qh": 0, "quarter_hours": 8} for x in busy],
            "rationale": "try the busy sector"})
        res = await call(c, "apply_change", {"change_id": p["change_id"]})
        print(f"   {res['status'].upper()}: " + "; ".join(res.get("reasons", [])[:2])[:300])

        say("3. Do the job properly: the planner's risk-checked plan, in arbiter-sized changes")
        plan = await call(c, "optimise_plan", {"cluster": "C01", "horizon": 32})
        acts = [{k: a[k] for k in ("cell", "action", "from_qh", "quarter_hours")}
                for a in plan["actions"]]
        print(f"   plan: {len(acts)} sleep windows, expected {plan['expected_kwh_saved']} kWh")
        ids = []
        for i in range(0, len(acts), 8):
            p = await call(c, "propose_change", {"actions": acts[i:i + 8],
                                                 "rationale": "planner plan, part"})
            r = await call(c, "apply_change", {"change_id": p["change_id"]})
            ids.append(p["change_id"])
            rec = r.get("receipt") or {}
            env = rec.get("signature") if isinstance(rec, dict) else None
            sig = "DSSE-signed receipt" if env and env.get("signatures") else "receipt"
            print(f"   {p['change_id']}: {r['status']} ({sig})"
                  + (f" - {'; '.join(r.get('reasons', []))[:120]}" if r.get("reasons") else ""))

        say("4. What happened")
        for cid in ids[:2]:
            st = await call(c, "get_change_status", {"change_id": cid})
            print(f"   {cid}: {st['status']}, {len(st.get('receipts', []))} receipt(s)")
        rep = await call(c, "get_energy_report", {"cluster": "C01", "window": 8})
        print(f"   energy report (last 2 h): {json.dumps(rep)[:200]}")
        say("Done", "The injected instruction was refused by rules, not by the model's good "
                    "manners; the real plan went through with signed receipts.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765/mcp")
    anyio.run(main, ap.parse_args().url)
