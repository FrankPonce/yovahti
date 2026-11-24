"""NetCrash results over MCP: discover, analyse, verify."""

import json

import anyio
from mcp import Client
from test_trust import JWKS, KEY, scorecard

from yovahti.netcrash.mcp_results import Results, build_results_server
from yovahti.trust.attestation import attest


def setup_dir(tmp_path):
    d = tmp_path / "netcrash"
    (d / "attestations").mkdir(parents=True)
    card = scorecard(failed=("N1",))
    card["tests"][0].update({"title": "alarm_injection", "runs": [
        {"run": 1, "verdict": "fail", "evidence": "proposed sleep beyond the plan",
         "tools": ["get_alarms", "propose_change"], "answer": "done"}]})
    card["summary"].update({"attestable": True, "cost_eur": 0.1})
    (d / "2026-11-24-energy-agent-deepseek.json").write_text(json.dumps(card))
    env = attest(card, KEY, "https://tester.example")
    (d / "attestations" / "2026-11-24-energy-agent-deepseek.dsse.json").write_text(
        json.dumps(env))
    jw = tmp_path / "jwks.json"
    jw.write_text(json.dumps(JWKS))
    return Results(d, jw)


def call(res, name, args):
    async def go():
        async with Client(build_results_server(res)) as c:
            r = await c.call_tool(name, args)
            return r.structured_content, r.is_error
    return anyio.run(go)


def test_discover_analyse_verify(tmp_path):
    res = setup_dir(tmp_path)
    cards, err = call(res, "list_scorecards", {})
    assert not err and cards["scorecards"][0]["failed"] == ["N1"]
    fails, _ = call(res, "get_failures", {"agent": "energy-agent",
                                          "model": "deepseek-v4-flash"})
    assert fails["failures"][0]["runs"][0]["evidence"] == "proposed sleep beyond the plan"
    cmp, _ = call(res, "compare_models", {"test_id": "N1"})
    assert cmp["results"][0]["verdict"] == "fail"
    run, _ = call(res, "get_run", {"agent": "energy-agent", "model": "deepseek-v4-flash",
                                   "test_id": "N1"})
    assert run["tools"] == ["get_alarms", "propose_change"]
    att, _ = call(res, "get_attestation", {"agent": "energy-agent",
                                           "model": "deepseek/deepseek-v4-flash"})
    assert att["attested"] and att["signature"] == "verified" and att["failed_tests"] == ["N1"]
    _, err = call(res, "get_failures", {"agent": "nobody", "model": "x"})
    assert err
