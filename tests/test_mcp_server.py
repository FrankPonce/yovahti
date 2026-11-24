"""MCP server: no hindsight, safety invariants enforced, refusals explained, end to end."""

import anyio
import numpy as np
import pytest
from mcp import Client
from test_world import tiny_world

from yovahti.forecast.quantile import HORIZON
from yovahti.mcp_server.network import Network
from yovahti.mcp_server.server import build_server
from yovahti.trust.admission import AgentIdentity, AllowListAdmission

T, S = 200, 4
AGENT = AgentIdentity("energy-agent")


def forecasts(mid_mb):
    """Flat forecasts; per-sector mid-band P90 decides whether sleeping is feasible."""
    issues = np.arange(0, T - HORIZON, 4)
    n = len(issues)

    def flat(v):
        return np.broadcast_to(np.asarray(v, float), (n, HORIZON, S)).copy()
    return {"issues": issues,
            "mid": {"issues": issues, 0.1: flat(mid_mb) * 0.5, 0.5: flat(mid_mb),
                    0.9: flat(mid_mb) * 1.2},
            "nr": {"issues": issues, 0.1: flat(10.0), 0.5: flat(20.0), 0.9: flat(30.0)},
            "low": {"issues": issues, 0.1: flat(50.0), 0.5: flat(100.0), 0.9: flat(150.0)}}


def make(now=10, **kw):
    w = tiny_world(T=T, S=S)
    # sector 1 is busy: its mid traffic cannot move onto the low band at P90
    return Network(w, forecasts([100.0, 5000.0, 100.0, 100.0]), now=now, **kw)


def act(net, cell, action="sleep", start=0, n=8, agent=AGENT):
    ch = net.propose_change(agent, [{"cell": cell, "action": action, "from_qh": start,
                                     "quarter_hours": n}], "test")
    return net.apply_change(agent, ch["change_id"])


def test_cells_have_friendly_ids_and_roles():
    net = make()
    cells = {c["cell"]: c for c in net.list_cells("all")["cells"]}
    assert {"s0-1/low", "s0-1/mid", "s0-1/nr3500"} <= set(cells)
    assert cells["s0-1/low"]["role"] == "coverage" and not cells["s0-1/low"]["can_sleep"]


def test_forecast_is_the_newest_issued_at_or_before_now():
    net = make(now=10)                           # issues every 4 QH: newest is 8
    out = net.forecast_load(["s0-1/mid"], 4)
    assert out["issued_at"] == net.time(8)
    assert out["times"][0] == net.time(10) and len(out["cells"]["s0-1/mid"]["p90_mb"]) == 4


def test_kpis_stop_before_now_and_carry_timestamps():
    net = make(now=10)
    k = net.get_cell_kpis(["s0-1/mid"], 4)
    assert k["times"] == [net.time(t) for t in range(6, 10)]
    assert len(k["cells"]["s0-1/mid"]["load_pct"]) == 4


def test_optimise_plan_sleeps_only_where_feasible():
    plan = make().optimise_plan("all", 16)
    asleep = {a["cell"] for a in plan["actions"]}
    assert "s0-1/mid" in asleep and "s1-1/mid" not in asleep
    assert plan["expected_kwh_saved"] > 0


def test_feasible_sleep_is_applied_with_receipt_and_shows_up():
    net = make()
    r = act(net, "s0-1/mid")
    assert r["status"] == "applied" and len(r["receipt"]["sha256"]) == 64
    net.advance(2)
    assert net.get_cell_kpis(["s0-1/mid"], 1)["cells"]["s0-1/mid"]["state"] == ["asleep"]


def test_overload_is_refused_by_i1():
    r = act(make(), "s1-1/mid")
    assert r["status"] == "refused" and r["reasons"][0].startswith("I1 capacity")


def test_sleep_beyond_forecast_horizon_is_refused():
    r = act(make(), "s0-1/mid", n=HORIZON)       # newest issue is 2 QH old
    assert r["status"] == "refused" and "cannot verify" in r["reasons"][0]


def test_protected_and_coverage_cells_never_sleep():
    net = make(protected={"s2-1/mid"})
    assert act(net, "s2-1/mid")["reasons"][0].startswith("I2 protected")
    assert act(net, "s0-1/low")["reasons"][0].startswith("I5 scope")


def test_blast_radius_limits_one_change():
    net = make()
    cells = [f"s{i}-1/{lay}" for i in (0, 2, 3) for lay in ("mid", "nr3500")]
    ch = net.propose_change(AGENT, [{"cell": c, "action": "sleep", "from_qh": 0,
                                     "quarter_hours": 4} for c in cells], "all at once")
    r = net.apply_change(AGENT, ch["change_id"])
    assert r["status"] == "refused" and r["reasons"][0].startswith("I3 blast radius")


def test_unadmitted_agent_and_foreign_change_are_refused():
    net = make(admission=AllowListAdmission({"energy-agent"}))
    sloppy = AgentIdentity("sloppy-agent")
    assert act(net, "s0-1/mid", agent=sloppy)["reasons"][0].startswith("I6 admission")
    ch = net.propose_change(AGENT, [{"cell": "s0-1/mid", "action": "sleep"}], "mine")
    r = net.apply_change(sloppy, ch["change_id"])
    assert r["status"] == "refused" and net.changes[ch["change_id"]].status == "proposed"


def test_rollback_restores_only_the_future():
    net = make()
    cid = act(net, "s0-1/mid", n=8)["change_id"]
    net.advance(3)
    r = net.rollback(AGENT, cid)
    assert r["status"] == "rolled_back"
    s = net.cells["s0-1/mid"][0]
    assert (net.mid_state[10:13, s] == 1).all() and (net.mid_state[13:, s] == 0).all()


def test_mcp_round_trip_in_process():
    net = make()

    async def go():
        async with Client(build_server(net, AGENT)) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            assert len(tools) == 14
            assert tools["get_cell_kpis"].annotations.read_only_hint
            assert not tools["apply_change"].annotations.read_only_hint
            plan = await c.call_tool("optimise_plan", {"cluster": "all", "horizon": 8})
            assert not plan.is_error and plan.structured_content["expected_kwh_saved"] > 0
            bad = await c.call_tool("get_cell_kpis", {"cells": ["nope/mid"]})
            assert bad.is_error
    anyio.run(go)


@pytest.mark.parametrize("window", [0, 10_000])
def test_windows_are_clamped(window):
    assert len(make(now=150).get_cell_kpis(["s0-1/mid"], window)["times"]) in (1, 96)


def test_simulate_plan_is_a_dry_run():
    net = make()
    ok = net.simulate_plan(AGENT, [{"cell": "s0-1/mid", "action": "sleep", "from_qh": 0,
                                    "quarter_hours": 8}])
    assert ok["would_apply"] and ok["expected_kwh_saved_vs_now"] > 0
    bad = net.simulate_plan(AGENT, [{"cell": "s1-1/mid", "action": "sleep", "from_qh": 0,
                                     "quarter_hours": 8}])
    assert not bad["would_apply"] and bad["p90_overload_sector_qh"] == 8
    assert bad["reasons"][0].startswith("I1 capacity")
    assert not net.changes and (net.mid_state == 0).all()
