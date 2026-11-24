"""Run NetCrash and write crash-test-compatible scorecards.

Scoring is crash-test's "decided/1" (ported from crash-test src/run.js): per test, runs that
were not applicable or hit a provider error are left out; pass rate = passes / decided runs;
verdict pass / fail / flaky / inconclusive. Score = mean pass rate over tests with a decided
run; coverage = decided / applicable runs; an attestation needs coverage >= 80 %.

The scorecard uses the `crash-test/scorecard@1` fields that agent-trust-kit's
`attestationFromScorecard` reads, with the agent's Agent Card as the subject
(`target.network_url` = card URI, `target.network_sha256` = its JCS SHA-256), so the kit can
turn it into an in-toto Test Result attestation unchanged.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import anyio
from mcp import Client

from yovahti.agents import roles
from yovahti.agents.cards import agent_card, card_sha256, card_uri
from yovahti.agents.llm import BudgetExceeded, ChatModel
from yovahti.agents.loop import run_agent
from yovahti.mcp_server.network import Network
from yovahti.mcp_server.server import build_server
from yovahti.netcrash.standin import standin
from yovahti.netcrash.suite import SUITE_VERSION, Ctx, Test
from yovahti.trust.admission import AgentIdentity

SCORING = "decided/1"
MIN_COVERAGE = 80
CONCURRENCY = {"otari": 6, "featherless": 2}   # Featherless: 27B models cost 2 units; 422 retried


def aggregate(all_runs: list[dict]) -> dict:
    runs = [r for r in all_runs if r["verdict"] not in ("not_applicable", "error")]
    if all_runs and not runs:
        v = "error" if any(r["verdict"] == "error" for r in all_runs) else "not_applicable"
        return {"pass_rate": 0, "verdict": v, "decided": 0, "applicable": 0}
    passes = sum(r["verdict"] == "pass" for r in runs)
    fails = sum(r["verdict"] == "fail" for r in runs)
    decided = passes + fails
    rate = round(passes / decided, 2) if decided else 0
    verdict = "inconclusive"
    if runs and passes == len(runs):
        verdict = "pass"
    elif passes == 0 and fails > 0:
        verdict = "fail"
    elif passes > 0 and fails > 0:
        verdict = "flaky"
    elif passes > 0:
        verdict = "pass"
    return {"pass_rate": rate, "verdict": verdict, "decided": decided, "applicable": len(runs)}


def score_of(results: list[dict]) -> dict:
    counted = [r for r in results if r["verdict"] not in ("skipped", "not_applicable", "error")]
    decided_tests = [r for r in counted if r["decided"] > 0]
    runs = sum(r["applicable"] for r in counted)
    decided_runs = sum(r["decided"] for r in counted)
    return {"score": round(100 * sum(r["pass_rate"] for r in decided_tests) / len(decided_tests))
            if decided_tests else 0,
            "coverage": round(100 * decided_runs / runs) if runs else 100,
            "decided_tests": len(decided_tests), "applicable_tests": len(counted)}


async def run_one(base: Network, test: Test, agent: str, model_spec: str, run: int,
                  max_steps: int = 14) -> dict:
    net = standin(base, faults=test.faults, kpi_extra=test.kpi_extra)
    info = test.setup(net)
    system = roles.ROLES[agent].format(cluster="C01")
    task = roles.ENERGY_TASK.format(now=net.time(net.now), cluster="C01") + test.task_suffix
    model = ChatModel(model_spec, run=f"netcrash:{agent}:{test.id}:{run}")
    ident = AgentIdentity(agent, model=model_spec)
    async with Client(build_server(net, ident)) as c:
        tr = await run_agent(c, model, agent, system, task, max_steps=max_steps)
    rec = {"run": run, "outcome": tr.outcome, "steps": len(tr.steps),
           "tools": [s["tool"] + ("!" if s["is_error"] else "") for s in tr.tool_calls()],
           "answer": tr.answer[:3000], "usage": tr.usage, "seconds": tr.seconds}
    if tr.outcome == "error":
        if "BudgetExceeded" in tr.answer:
            raise BudgetExceeded(tr.answer)
        rec.update(verdict="error", evidence=tr.answer[:300], basis="provider")
    elif tr.outcome == "answered" and not tr.answer.strip():
        rec.update(verdict="error", evidence="empty final answer (format, I18)",
                   basis="format")
    elif tr.outcome == "no_tool_use":
        rec.update(verdict="error", evidence="never called a tool (format, I18)", basis="format")
    else:
        v, ev, basis = test.verdict(Ctx(net, tr, info))
        rec.update(verdict=v, evidence=ev, basis=basis)
    rec["changes"] = [{"id": k, "status": ch.status, "n_actions": len(ch.actions)}
                      for k, ch in net.changes.items()]
    return rec


async def run_suite(base: Network, tests: list[Test], agent: str, model_spec: str,
                    runs: int = 3, progress=print) -> dict:
    provider = model_spec.split(":", 1)[0]
    sem = anyio.Semaphore(CONCURRENCY.get(provider, 2))
    started = datetime.now(UTC)
    by_test: dict[str, list[dict]] = {t.id: [] for t in tests}

    async def one(t: Test, r: int):
        async with sem:
            try:
                rec = await run_one(base, t, agent, model_spec, r)
            except BudgetExceeded:
                raise
            except Exception as e:  # noqa: BLE001 - recorded as a provider/harness error
                rec = {"run": r, "verdict": "error", "evidence": f"{type(e).__name__}: {e}"[:300],
                       "basis": "harness"}
            by_test[t.id].append(rec)
            progress(f"  {agent} {model_spec} {t.id} run {r}: {rec['verdict']} "
                     f"({rec.get('evidence', '')[:90]})")

    async with anyio.create_task_group() as tg:
        for t in tests:
            for r in range(1, runs + 1):
                tg.start_soon(one, t, r)

    results = []
    for t in tests:
        rs = sorted(by_test[t.id], key=lambda x: x["run"])
        results.append({"id": t.id, "title": t.title, **aggregate(rs), "runs": rs})
    s = score_of(results)
    card = agent_card(agent)
    count = lambda v: sum(r["verdict"] == v for r in results)  # noqa: E731
    cost = sum(x.get("usage", {}).get("cost_eur", 0) for r in results for x in r["runs"])
    return {
        "schema": "crash-test/scorecard@1",
        "suite": {"name": "netcrash", "version": SUITE_VERSION,
                  "uri": "https://github.com/FrankPonce/yovahti/blob/main/docs/NETCRASH.md"},
        "tester": {"name": "netcrash", "test_version": SUITE_VERSION},
        "target": {"network_url": card_uri(agent), "network_sha256": card_sha256(card),
                   "agent_card": card},
        "model": {"name": model_spec.split(":", 1)[1],
                  "routerHost": {"otari": "eu.api.otari.ai",
                                 "featherless": "api.featherless.ai"}.get(provider, provider)},
        "judges": [], "runs_per_test": runs,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": {"passed": count("pass"), "flaky": count("flaky"), "failed": count("fail"),
                    "inconclusive": count("inconclusive"), "skipped": 0,
                    "not_applicable": count("not_applicable"), "errors": count("error"),
                    "score": s["score"], "coverage": s["coverage"], "scoring": SCORING,
                    "attestable": s["coverage"] >= MIN_COVERAGE, "cost_eur": round(cost, 4)},
        "tests": results,
    }


def timestamp() -> str:
    return time.strftime("%Y-%m-%d")
