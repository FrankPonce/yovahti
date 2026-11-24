"""NetCrash results as an MCP server: test data an AI assistant can discover, analyse and act on.

Run: uv run python -m yovahti.netcrash.mcp_results [--port 8766]   (Streamable HTTP, /mcp)

Read-only over results/netcrash/: scorecards, per-run evidence and signed attestations.
Every attestation is verified against the tester's published key before it is reported.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from yovahti.netcrash.suite import BY_ID
from yovahti.paths import RESULTS, ROOT
from yovahti.trust.attestation import read_attestation

READ = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


def agent_of(card: dict) -> str:
    t = card.get("target") or {}
    from_url = t.get("network_url", "").rsplit("/", 1)[-1].removesuffix(".json")
    return (t.get("agent_card") or {}).get("id") or from_url


class Results:
    def __init__(self, root: Path = RESULTS / "netcrash",
                 jwks: Path = ROOT / "trust" / "tester.jwks.json"):
        self.root, self.jwks_path = root, jwks

    def cards(self) -> list[tuple[str, dict]]:
        out = []
        for p in sorted(self.root.glob("*-agent-*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("schema") == "crash-test/scorecard@1":
                out.append((p.stem, d))
        return out

    def find(self, agent: str, model: str) -> tuple[str, dict]:
        hits = [(n, d) for n, d in self.cards() if agent_of(d) == agent
                and model in (d["model"]["name"], d["model"]["name"].split("/")[-1])]
        if not hits:
            raise ValueError(f"no scorecard for {agent} on {model}; call list_scorecards")
        return hits[-1]


def build_results_server(res: Results | None = None) -> MCPServer:
    res = res or Results()
    mcp = MCPServer("netcrash-results", version="0.1.0", instructions=(
        "NetCrash: behavioural tests for network agents, per agent x model. Start with "
        "list_scorecards, then get_failures or compare_models; get_run shows one run's "
        "evidence; get_attestation verifies a signed result."))

    @mcp.tool(annotations=READ)
    def list_tests() -> dict[str, Any]:
        """The NetCrash test catalogue: id, name and what passing means."""
        return {"tests": [{"id": t.id, "name": t.title,
                           "faults": list(t.faults)} for t in BY_ID.values()]}

    @mcp.tool(annotations=READ)
    def list_scorecards() -> dict[str, Any]:
        """Every scorecard: agent, model, score, coverage, failed tests, cost, date."""
        return {"scorecards": [{
            "id": name, "agent": agent_of(d), "model": d["model"]["name"],
            "score": d["summary"]["score"], "coverage": d["summary"]["coverage"],
            "attestable": d["summary"].get("attestable"),
            "failed": [t["id"] for t in d["tests"] if t["verdict"] == "fail"],
            "flaky": [t["id"] for t in d["tests"] if t["verdict"] == "flaky"],
            "cost_eur": d["summary"].get("cost_eur"), "finished_at": d.get("finished_at")}
            for name, d in res.cards()]}

    @mcp.tool(annotations=READ)
    def get_failures(agent: str, model: str) -> dict[str, Any]:
        """Failed and flaky tests of one agent x model, with each run's evidence."""
        name, d = res.find(agent, model)
        bad = [{"test": t["id"], "name": t["title"], "verdict": t["verdict"],
                "pass_rate": t["pass_rate"],
                "runs": [{"run": r["run"], "verdict": r["verdict"],
                          "evidence": r.get("evidence", "")} for r in t["runs"]]}
               for t in d["tests"] if t["verdict"] in ("fail", "flaky")]
        return {"scorecard": name, "score": d["summary"]["score"], "failures": bad}

    @mcp.tool(annotations=READ)
    def compare_models(test_id: str) -> dict[str, Any]:
        """One test across every agent x model: verdict, pass rate, first evidence."""
        if test_id not in BY_ID:
            raise ValueError(f"unknown test {test_id!r}; call list_tests")
        rows = []
        for _name, d in res.cards():
            for t in d["tests"]:
                if t["id"] == test_id:
                    ev = next((r.get("evidence") for r in t["runs"] if r.get("evidence")), "")
                    rows.append({"agent": agent_of(d),
                                 "model": d["model"]["name"], "verdict": t["verdict"],
                                 "pass_rate": t["pass_rate"], "evidence": ev})
        return {"test": test_id, "name": BY_ID[test_id].title, "results": rows}

    @mcp.tool(annotations=READ)
    def get_run(agent: str, model: str, test_id: str, run: int = 1) -> dict[str, Any]:
        """One run: tools the agent called, its verdict and evidence, and its report."""
        name, d = res.find(agent, model)
        for t in d["tests"]:
            if t["id"] == test_id:
                for r in t["runs"]:
                    if r["run"] == run:
                        return {"scorecard": name, "test": test_id, **{
                            k: r.get(k) for k in ("verdict", "evidence", "basis", "outcome",
                                                  "tools", "changes", "usage")},
                            "answer": (r.get("answer") or "")[:3000]}
        raise ValueError(f"no run {run} of {test_id} for {agent} on {model}")

    @mcp.tool(annotations=READ)
    def get_attestation(agent: str, model: str) -> dict[str, Any]:
        """The signed attestation for an agent x model, verified against the tester key."""
        name, _ = res.find(agent, model)
        p = res.root / "attestations" / f"{name}.dsse.json"
        if not p.exists():
            return {"scorecard": name, "attested": False,
                    "reason": "no attestation (coverage below 80 % or not yet signed)"}
        jwks = json.loads(res.jwks_path.read_text(encoding="utf-8"))
        v = read_attestation(json.loads(p.read_text(encoding="utf-8")), jwks)
        if not v["ok"]:
            return {"scorecard": name, "attested": False, "reason": v["reason"]}
        pr = v["statement"]["predicate"]
        return {"scorecard": name, "attested": True, "signature": "verified",
                "keyid": v["keyid"], "subject": v["statement"]["subject"],
                "result": pr["result"], "score": pr["score"], "coverage": pr["coverage"],
                "failed_tests": pr["failedTests"], "expires": pr["expiresAt"]}

    return mcp


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8766)
    a = ap.parse_args()
    import anyio
    server = build_results_server()
    print(f"NetCrash results on http://{a.host}:{a.port}/mcp", flush=True)
    anyio.run(lambda: server.run_streamable_http_async(host=a.host, port=a.port))


if __name__ == "__main__":
    main()
