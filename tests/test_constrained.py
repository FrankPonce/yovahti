"""Constrained mode (D45): the agent can only make the planner's plan safer."""

import json

import anyio
import pytest
from mcp import Client
from test_agents import Scripted, call
from test_mcp_server import AGENT, make

from yovahti.agents.cards import agent_card
from yovahti.mcp_server.constrained import apply_plan
from yovahti.mcp_server.network import planner_operator
from yovahti.mcp_server.server import build_server
from yovahti.netcrash import runner
from yovahti.netcrash.suite import BY_ID


def planned(net):
    return {(a["cell"], a["from_qh"], a["quarter_hours"])
            for a in net.optimise_plan("C01", 32)["actions"]}


def applied_sleeps(net):
    return {(a["cell"], a["from_t"], a["until_t"]) for ch in net.changes.values()
            if ch.status == "applied" for a in ch.actions if a["action"] == "sleep"}


def test_only_read_tools_and_apply_plan_are_exposed():
    async def go():
        async with Client(build_server(make(), AGENT, "constrained")) as c:
            return {t.name for t in (await c.list_tools()).tools}
    names = anyio.run(go)
    assert "apply_plan" in names
    assert not names & {"propose_change", "apply_change", "rollback", "simulate_plan"}
    assert set(agent_card("energy-agent-c")["allowed_tools"]) == names


def test_apply_plan_applies_exactly_the_planner_plan():
    net = make()
    net.approver = planner_operator(net)
    want = planned(net)
    out = apply_plan(net, AGENT, "C01", None, "plan", [])
    assert out["changes"] and all(c["status"] == "applied" for c in out["changes"])
    got = {(c, f - net.now, u - f) for c, f, u in applied_sleeps(net)}
    assert got == {w for w in want if w[2] >= net.arbiter.min_dwell}


def test_keep_awake_only_removes_sleep_and_never_adds_any():
    net = make()
    net.approver = planner_operator(net)
    cell = next(iter(planned(net)))[0]
    out = apply_plan(net, AGENT, "C01", [{"cell": cell, "from_qh": 0, "quarter_hours": 40,
                                         "reason": "event"}], "kept awake", ["alarms"])
    sector = cell.split("/")[0]
    assert all(not c.startswith(sector + "/") for c, _, _ in applied_sleeps(net))
    assert out["kept_awake"] == {sector: [0, 40]}
    assert out["report_recorded"]["unknowns"] == ["alarms"]


def test_apply_plan_runs_once_per_tick():
    net = make()
    net.approver = planner_operator(net)
    apply_plan(net, AGENT, "C01", None, "first", [])
    n = len(net.changes)
    again = apply_plan(net, AGENT, "C01", None, "again", [])
    assert again["status"] == "refused" and len(net.changes) == n


def test_unknown_cells_are_reported_not_applied():
    net = make()
    net.approver = planner_operator(net)
    out = apply_plan(net, AGENT, "C01", [{"cell": "nope/mid"}], "x", [])
    assert out["unknown_cells"] == ["nope/mid"]


@pytest.mark.parametrize("test_id", ["N1", "N11"])
def test_runner_constrained_mode(monkeypatch, test_id):
    """N1 (prevented) becomes not_applicable; N11 (event) is decided on what the agent kept
    awake; an empty final answer falls back to the apply_plan report."""
    t = BY_ID[test_id]
    net, info = runner.prepare(make(), t)
    keep = [{"cell": c, "from_qh": 0, "quarter_hours": 40, "reason": "event"}
            for c in sorted(info.get("cells", []))]
    replies = [call("get_events", {}), call("get_alarms", {}, 1),
               call("apply_plan", {"cluster": "C01", "summary": "Applied the plan.",
                                   "keep_awake": keep, "unknowns": ["none checked"]}, 2),
               {"role": "assistant", "content": ""}, {"role": "assistant", "content": ""}]
    monkeypatch.setattr(runner, "ChatModel", lambda spec, run: Scripted(list(replies)))
    rec = anyio.run(runner.run_one, make(), t, "energy-agent-c", "fake:scripted", 1)
    assert "Applied the plan." in rec["answer"]
    if test_id == "N1":
        assert rec["verdict"] == "not_applicable" and rec["basis"] == "interface"
    else:
        assert rec["verdict"] == "pass", rec["evidence"]


def test_constrained_cards_are_new_identities():
    a, b = agent_card("energy-agent"), agent_card("energy-agent-c")
    assert a["prompt_sha256"] != b["prompt_sha256"]
    assert json.dumps(a["allowed_tools"]) != json.dumps(b["allowed_tools"])
