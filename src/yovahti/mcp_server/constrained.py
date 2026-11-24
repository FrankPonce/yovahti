"""Constrained mode: the agent can only make the planner's plan *safer* (D45).

In full mode an agent proposes any sleep on any cell and the arbiter has to catch the bad ones.
Here it gets one act tool, ``apply_plan``: the server takes the planner's risk-checked plan,
removes sleep from the windows the agent asks to keep awake, and applies the rest through the
same admission and arbiter, under the agent's own identity. The agent can never add a sleep,
pick a cell the planner did not, split a change, roll one back or call an out-of-card tool:
those failure modes are gone by construction, not caught after the fact.

What the agent still contributes is what it showed in the event experiments (E21, E23):
reading the calendar and keeping the right sectors awake. It also files a structured report
(``summary`` plus explicit ``unknowns``) with the call, so "no data" cannot silently become
"all clear" and a run never ends without a report (G35).
"""

from __future__ import annotations

from typing import Any

from yovahti.agents.evaluate import _cut
from yovahti.mcp_server.network import Network
from yovahti.trust.admission import AgentIdentity


def apply_plan(net: Network, agent: AgentIdentity, cluster: str,
               keep_awake: list[dict[str, Any]] | None, summary: str,
               unknowns: list[str] | None, horizon: int = 32) -> dict[str, Any]:
    """Planner plan minus the agent's keep-awake windows, applied once per clock tick."""
    done = getattr(net, "_constrained_applied", {})
    if done.get(cluster) == net.now:
        return {"status": "refused", "reasons": [
            "the plan for this cluster was already applied at this time; check its changes "
            "with get_change_status instead of applying again"],
            "changes": done.get(f"{cluster}:ids", [])}
    windows: dict[str, tuple[int, int]] = {}
    bad = []
    for k in keep_awake or []:
        cell = str(k.get("cell", ""))
        if cell not in net.cells:
            bad.append(cell)
            continue
        sector = cell.split("/")[0]
        lo = max(0, int(k.get("from_qh", 0)))
        hi = lo + max(1, int(k.get("quarter_hours", 1)))
        w = windows.get(sector)
        windows[sector] = (min(lo, w[0]), max(hi, w[1])) if w else (lo, hi)
    plan = net.optimise_plan(cluster, horizon)
    acts = _cut(plan.get("actions", []), windows) if windows else list(plan.get("actions", []))
    # a cut can leave a stub shorter than the minimum dwell (I4), which the arbiter refuses
    acts = [{k: a[k] for k in ("cell", "action", "from_qh", "quarter_hours")} for a in acts
            if a["quarter_hours"] >= net.arbiter.min_dwell]
    cap_cells = sum(1 for c in net.cells_in(cluster) if net.cells[c][1] != "low")
    chunk = max(1, int(net.arbiter.max_cluster_share * cap_cells))
    by_cell: dict[str, list[dict]] = {}
    for a in acts:
        by_cell.setdefault(a["cell"], []).append(a)
    cells = list(by_cell)
    results = []
    rationale = (summary or "planner plan")[:500]
    for i in range(0, len(cells), chunk):
        batch = [a for c in cells[i:i + chunk] for a in by_cell[c]]
        prop = net.propose_change(agent, batch, rationale)
        if "change_id" not in prop:
            results.append(prop)
            continue
        res = net.apply_change(agent, prop["change_id"])
        results.append({"change_id": prop["change_id"], "status": res.get("status"),
                        "reasons": res.get("reasons", [])})
    ids = [r["change_id"] for r in results if "change_id" in r]
    done[cluster], done[f"{cluster}:ids"] = net.now, ids
    net._constrained_applied = done
    return {"cluster": cluster, "kept_awake": {s: list(w) for s, w in windows.items()},
            "unknown_cells": bad, "sleep_actions_applied_or_pending": len(acts),
            "changes": results, "report_recorded": {"summary": summary,
                                                    "unknowns": unknowns or []},
            "note": "statuses: applied, awaiting_approval (a human must approve; nothing is "
                    "applied yet), refused, or unknown (no acknowledgement yet: do not "
                    "apply again)"}
