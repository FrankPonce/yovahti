"""Agent loop, budget guard and night replay, without any network calls."""

import json

import anyio
import pytest
from mcp import Client
from test_mcp_server import AGENT, make

from yovahti.agents.evaluate import apply_plan_alone, compare_night
from yovahti.agents.llm import BudgetExceeded, Ledger, _parse_prices
from yovahti.agents.loop import run_agent
from yovahti.mcp_server.server import build_server


class Scripted:
    """Stands in for an LLM: replays a fixed list of assistant messages."""
    spec = "fake:scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "cost_eur": 0.0, "calls": 0}

    def chat(self, messages, tools=None):
        self.usage["calls"] += 1
        self.last_messages = messages
        return self.replies.pop(0)


def call(name, args, i=0):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{i}", "type": "function",
         "function": {"name": name, "arguments": json.dumps(args)}}]}


def run(net, replies, steps=8):
    async def go():
        async with Client(build_server(net, AGENT)) as c:
            return await run_agent(c, Scripted(replies), "energy-agent", "sys", "task", steps)
    return anyio.run(go)


def test_loop_executes_tool_calls_and_records_the_answer():
    net = make()
    tr = run(net, [call("optimise_plan", {"cluster": "all", "horizon": 8}),
                   call("propose_change", {"actions": [{"cell": "s0-1/mid", "action": "sleep",
                                                        "from_qh": 0, "quarter_hours": 4}],
                                           "rationale": "plan"}, 1),
                   {"role": "assistant", "content": "done"}])
    assert tr.outcome == "answered" and tr.answer == "done"
    assert [s["tool"] for s in tr.tool_calls()] == ["optimise_plan", "propose_change"]
    assert any(ch.status == "proposed" for ch in net.changes.values())


def test_answer_without_any_tool_use_is_a_format_outcome():
    tr = run(make(), [{"role": "assistant", "content": "I saved 40 % energy."}])
    assert tr.outcome == "no_tool_use"


def test_bad_arguments_and_tool_errors_are_returned_not_raised():
    bad = {"role": "assistant", "content": "", "tool_calls": [
        {"id": "x", "type": "function", "function": {"name": "list_cells",
                                                      "arguments": "{not json"}}]}
    tr = run(make(), [bad, call("get_cell_kpis", {"cells": ["nope/mid"]}, 1),
                      {"role": "assistant", "content": "stop"}])
    assert [s["is_error"] for s in tr.tool_calls()] == [True, True]
    assert tr.outcome == "answered"


def test_max_steps_is_recorded():
    tr = run(make(), [call("list_cells", {"cluster": "all"}, i) for i in range(3)], steps=3)
    assert tr.outcome == "max_steps"


def test_budget_guard_refuses_at_the_cap(tmp_path):
    led = Ledger(path=tmp_path / "l.jsonl", caps={"otari": 0.01})
    led.check("otari")
    led.record("otari", "m", {"prompt_tokens": 1, "completion_tokens": 1}, 0.02, "r")
    with pytest.raises(BudgetExceeded):
        led.check("otari")


def test_prices_parse_for_both_provider_formats():
    otari = {"data": [{"id": "a", "pricing": {"input_price_per_million": 0.1,
                                              "output_price_per_million": 0.2, "unit": "token"}},
                      {"id": "v", "pricing": {"input_price_per_million": 9, "unit": "second"}}]}
    fl = {"data": [{"id": "q", "pricing": {"input": 0.4, "output": 3}}]}
    assert _parse_prices("otari", otari)["a"].output_per_m == 0.2
    assert "v" not in _parse_prices("otari", otari)          # unpriced per token: refused
    assert _parse_prices("featherless", fl)["q"].input_per_m == 0.4


def test_replay_scores_the_applied_schedule():
    agent_net, alone = make(now=8), make(now=8)
    apply_plan_alone(alone, "all", horizon=16)
    cmp = compare_night({"agent (did nothing)": agent_net, "alone": alone}, "all", 8, 40)
    rows = cmp["rows"]
    assert rows["agent (did nothing)"]["kwh_saved_pct"] == pytest.approx(0.0)
    assert rows["alone"]["kwh_saved_pct"] > 0
    assert "B4 rolling (hourly re-plan)" in rows


def test_silent_stop_gets_one_nudge_then_the_answer_counts():
    tr = run(make(), [call("list_cells", {"cluster": "all"}), {"role": "assistant", "content": ""},
                      {"role": "assistant", "content": "Report: nothing applied."}])
    assert tr.outcome == "answered" and tr.answer == "Report: nothing applied."
    assert any(s["kind"] == "nudge" for s in tr.steps)
