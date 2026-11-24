"""What an applied schedule really does: replay it in the world simulator (closes I30 for
evaluation). The network view only records the schedule; here the simulator re-routes the
real traffic, computes energy, congestion and unserved traffic, and runs the watchdog.

Reference points on the same sectors and quarter-hours: B0 always-on, the planner alone under
the same protocol (one ``optimise_plan`` applied through the same gate, no LLM), and B4 with its
usual hourly re-planning.
"""

from __future__ import annotations

import numpy as np

from yovahti.baselines.simple import always_on
from yovahti.mcp_server.network import Network
from yovahti.plan.dp import DPPlanner, PlannerConfig
from yovahti.trust.admission import AgentIdentity
from yovahti.world.data import time_slice
from yovahti.world.sim import run, summarise

COLS = ("kwh_saved_pct", "congested_qh_per_sector_day", "unserved_gb", "watchdog_wakes",
        "sleep_share_mid", "sleep_share_nr")


def cluster_sectors(net: Network, cluster: str) -> np.ndarray:
    return np.array(sorted({net.cells[c][0] for c in net.cells_in(cluster)}))


def _schedule_policy(net: Network, sectors: np.ndarray, t0: int, t1: int):
    mid = net.mid_state[t0:t1][:, sectors]
    nr = net.nr_state[t0:t1][:, sectors]

    def policy(obs):
        t = min(obs.t, mid.shape[0] - 1)
        return mid[t], nr[t]
    return policy


def apply_plan_alone(net: Network, cluster: str, horizon: int = 32) -> list[dict]:
    """The planner alone: apply optimise_plan through the same gate, split to respect I3."""
    who = AgentIdentity("planner-alone", model="none")
    plan = net.optimise_plan(cluster, horizon)
    cap_cells = sum(1 for c in net.cells_in(cluster) if net.cells[c][1] != "low")
    chunk = max(1, int(net.arbiter.max_cluster_share * cap_cells))
    acts = [{k: a[k] for k in ("cell", "action", "from_qh", "quarter_hours")}
            for a in plan["actions"]]
    by_cell: dict[str, list[dict]] = {}
    for a in acts:
        by_cell.setdefault(a["cell"], []).append(a)
    cells = list(by_cell)
    out = []
    for i in range(0, len(cells), chunk):
        batch = [a for c in cells[i:i + chunk] for a in by_cell[c]]
        ch = net.propose_change(who, batch, "planner alone")
        out.append(net.apply_change(who, ch["change_id"]))
    return out


def compare_night(nets: dict[str, Network], cluster: str, t0: int, t1: int) -> dict:
    """{name: summary} for each network's schedule plus B0 and rolling B4, same window."""
    ref = next(iter(nets.values()))
    sectors = cluster_sectors(ref, cluster)
    w = time_slice(ref.w, t0, t1).subset(sectors)
    cfg = ref.wc
    b0 = run(w, always_on, "B0", cfg)
    rows = {"B0 always-on": summarise(w, b0, b0)}
    for name, net in nets.items():
        rows[name] = summarise(w, run(w, _schedule_policy(net, sectors, t0, t1), name, cfg), b0)
    fc = {t: {"issues": v["issues"], **{q: v[q][..., sectors] for q in (0.1, 0.5, 0.9)}}
          for t, v in ref.f.items() if t in ("mid", "nr", "low")}
    b4 = DPPlanner(w, fc, PlannerConfig(), cfg, issue_offset=ref.issue_offset + t0)
    rows["B4 rolling (hourly re-plan)"] = summarise(w, run(w, b4, "B4", cfg), b0)
    kwh = float(b0.total_wh().sum() / 1000)
    return {"sectors": int(len(sectors)), "from": ref.time(t0), "until": ref.time(t1),
            "b0_kwh": round(kwh, 1),
            "rows": {k: {c: round(float(v.get(c, 0.0)), 3) for c in COLS} for k, v in
                     rows.items()}}
