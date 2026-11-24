"""Workflow mode (D46): one bounded model decision per night, everything else is code.

The open agent loop is replaced by fixed steps over the same MCP tools:

1. code reads the feeds (cells, events, alarms, KPI health, the planner's plan);
2. the model makes ONE call, with no tools, that can only fill a JSON schema of events
   (cells, from, until, kind, people) from the calendar and alarm text: the dual-LLM /
   CaMeL idea that untrusted text may produce data but never actions;
3. code validates that JSON (known capacity cells only, sane times) and maps events to
   keep-awake windows;
4. code calls ``apply_plan`` (constrained mode, D45) and ``get_change_status``;
5. the report is written by code from the network's state: per-change status, the planner's
   expected saving, what was kept awake and why, and every unknown feed. The model writes no
   prose, so it cannot report missing data as fine, confirm what did not happen, or leak a
   token it read.

What the model still decides: which cells an event touches and when (NetCrash N11), and,
by over-reacting, whether the night still saves energy (N18).
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from yovahti.agents.loop import Trace, _result_text, visible
from yovahti.agents.roles import EXTRACT

QH_MARGIN_AFTER = 4          # keep a crowd's cells awake one hour after it ends
QH_DEFAULT = 8               # no end time given: two hours


def _qh(hhmm: str, now_label: str) -> int | None:
    """'22:30' -> quarter-hours from now (next occurrence within 24 h), or None."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(hhmm or ""))
    n = re.search(r"T(\d{2}):(\d{2})", now_label)
    if not m or not n:
        return None
    t = int(m.group(1)) * 4 + int(m.group(2)) // 15
    now = int(n.group(1)) * 4 + int(n.group(2)) // 15
    d = (t - now) % 96
    return d - 96 if d > 88 else d            # just before now counts as already started


def parse_events(text: str, known: set[str]) -> tuple[list[dict], list[str]]:
    """Strictly validated events and the reasons anything was dropped."""
    dropped: list[str] = []
    m = re.search(r"\{.*\}", visible(text), re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        return [], ["the extraction was not the requested JSON; no events used"]
    out = []
    for e in data["events"][:20]:
        if not isinstance(e, dict):
            continue
        cells = [c for c in e.get("cells") or [] if isinstance(c, str) and c in known]
        bad = [c for c in e.get("cells") or [] if c not in known]
        if bad:
            dropped.append(f"unknown cell ids ignored: {bad[:5]}")
        if not cells:
            continue
        out.append({"cells": cells, "from": e.get("from"), "until": e.get("until"),
                    "kind": str(e.get("kind") or "other")[:20],
                    "people": e.get("people") if isinstance(e.get("people"), int) else None})
    return out, dropped


def keep_awake_windows(events: list[dict], now_label: str) -> list[dict]:
    out = []
    for e in events:
        f = _qh(e["from"], now_label)
        u = _qh(e["until"], now_label) if e.get("until") else None
        if f is None:
            f = 0
        lo = max(0, f)
        hi = (u + QH_MARGIN_AFTER) if u is not None and u > f else lo + QH_DEFAULT
        if hi <= 0:
            continue                                   # already over
        for c in e["cells"]:
            out.append({"cell": c, "from_qh": lo, "quarter_hours": max(1, hi - lo),
                        "reason": f"{e['kind']} event" + (f", about {e['people']} people"
                                                         if e["people"] else "")})
    return out


async def run_workflow(client: Any, model: Any, agent: str, cluster: str, now_label: str,
                       horizon: int = 32) -> Trace:
    tr = Trace(agent=agent, model=getattr(model, "spec", "?"), task="workflow")
    t0 = time.time()

    async def tool(name: str, args: dict) -> tuple[Any, bool]:
        try:
            res = await client.call_tool(name, args)
            txt, err = _result_text(res)
        except Exception as e:  # noqa: BLE001 - a failing feed is data for the report
            txt, err = f"{type(e).__name__}: {e}", True
        tr.steps.append({"kind": "tool", "step": len(tr.steps), "tool": name, "args": args,
                         "is_error": err, "result": txt[:2000]})
        try:
            return json.loads(txt), err
        except json.JSONDecodeError:
            return txt, err

    try:
        unknowns: list[str] = []
        cells_out, _ = await tool("list_cells", {"cluster": cluster})
        rows = cells_out.get("cells", []) if isinstance(cells_out, dict) else []
        known = {r["cell"] for r in rows if isinstance(r, dict) and r.get("layer") != "low"}
        events, e_err = await tool("get_events", {"window": 96})
        alarms, a_err = await tool("get_alarms", {"cluster": cluster, "window": 96})
        if a_err or not isinstance(alarms, dict):
            unknowns.append("alarm feed: could not be read")
        elif "no alarm feed" in str(alarms.get("source", "")):
            unknowns.append("alarm feed: none in this network (unknown, not all clear)")
        if e_err or not isinstance(events, dict):
            unknowns.append("event calendar: could not be read")
        elif "no event calendar" in str(events.get("source", "")):
            unknowns.append("event calendar: none loaded (unknown, not 'nothing happening')")
        probe = sorted(known)[:2]
        kpis, k_err = await tool("get_cell_kpis", {"cells": probe, "window": 4})
        if k_err:
            unknowns.append(f"KPI collector unavailable: {str(kpis)[:120]}")
        elif isinstance(kpis, dict) and "lags" in str(kpis.get("note", "")):
            unknowns.append(f"KPI feed is stale: measurements only up to "
                            f"{kpis.get('data_until')} ({kpis.get('note', '')[:120]})")
        plan, p_err = await tool("optimise_plan", {"cluster": cluster, "horizon": horizon})
        if p_err or not isinstance(plan, dict):
            unknowns.append("planner: could not be read")
        elif plan.get("status") == "partial":
            unknowns.append("planner returned only a partial result; nothing beyond it applied")
        if isinstance(plan, dict) and plan.get("uncertainty"):
            unknowns.append(f"forecast uncertainty is wide: {str(plan['uncertainty'])[:160]}")

        # ---- the one model call: feeds in, typed events out
        feed = {"now": now_label, "KNOWN_CELLS": sorted(known),
                "event_calendar": (events or {}).get("events", []) if isinstance(events, dict)
                else [], "alarms": (alarms or {}).get("alarms", [])
                if isinstance(alarms, dict) else []}
        msg = model.chat([{"role": "system", "content": EXTRACT},
                          {"role": "user", "content": json.dumps(feed, ensure_ascii=False)}])
        raw = msg.get("content") or ""
        tr.steps.append({"kind": "model", "step": len(tr.steps), "content": raw[:4000],
                         "tool_calls": [], "finish": msg.get("_finish")})
        found, dropped = parse_events(raw, known)
        unknowns += dropped
        keep = keep_awake_windows(found, now_label)

        summary = ("Planner plan for tonight, minus keep-awake windows from "
                   f"{len(found)} extracted event(s).")
        applied, _ = await tool("apply_plan", {"cluster": cluster, "summary": summary,
                                               "keep_awake": keep, "unknowns": unknowns})
        changes = applied.get("changes", []) if isinstance(applied, dict) else []
        status = {}
        for ch in changes:
            if "change_id" in ch:
                st, _ = await tool("get_change_status", {"change_id": ch["change_id"]})
                status[ch["change_id"]] = st.get("status") if isinstance(st, dict) else "unknown"
        tr.answer = report(cluster, plan, status, keep, unknowns,
                           alarms_n=len(feed["alarms"]), events_n=len(feed["event_calendar"]))
        tr.outcome = "answered"
    except Exception as e:  # noqa: BLE001 - recorded, not hidden
        tr.outcome, tr.answer = "error", f"{type(e).__name__}: {e}"
    tr.usage = dict(getattr(model, "usage", {}))
    tr.seconds = round(time.time() - t0, 1)
    return tr


WORDS = {"applied": "applied", "awaiting_approval": "awaiting human approval (not applied yet)",
         "unknown": "outcome unknown (no acknowledgement yet; not re-applied)",
         "failed": "failed (the radios did not carry it out)", "refused": "refused by the arbiter",
         "proposed": "proposed, not applied"}


def report(cluster: str, plan: Any, status: dict[str, str], keep: list[dict],
           unknowns: list[str], alarms_n: int, events_n: int) -> str:
    """Written by code from state, never by the model."""
    lines = [f"Cluster {cluster}: tonight's planner plan was submitted through the arbiter."]
    if status:
        lines.append("Changes: " + "; ".join(f"{cid} {WORDS.get(s, s)}"
                                              for cid, s in status.items()) + ".")
    else:
        lines.append("Changes: none were submitted, so no saving is in place.")
    kwh = plan.get("expected_kwh_saved") if isinstance(plan, dict) else None
    if kwh is not None and any(s == "applied" for s in status.values()):
        lines.append(f"Planner's expected saving for the whole plan: {kwh} kWh "
                     "(before any keep-awake windows).")
    if keep:
        by = {}
        for k in keep:
            by.setdefault(k["reason"], []).append(k["cell"])
        lines.append("Kept awake: " + "; ".join(f"{', '.join(v)} ({r})" for r, v in by.items())
                     + ".")
    lines.append(f"Feeds read: {events_n} calendar entries and {alarms_n} alarms, treated as "
                 "data.")
    lines.append("Unknowns: " + ("; ".join(unknowns) if unknowns else "none") + ".")
    return "\n".join(lines)
