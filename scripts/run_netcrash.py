"""NetCrash: behavioural tests for network agents, per agent x model (docs/NETCRASH.md).

Run: uv run python scripts/run_netcrash.py --models otari:deepseek/deepseek-v4-flash
         [--agents energy-agent sloppy-agent] [--runs 3] [--tests N1 N4 ...]
Stand-in networks are 3 real sites of cluster C01 on a validation-week night (test weeks
untouched). Spend is capped per provider (D20). Writes results/netcrash/<date>-<agent>-<model>.json
and results/netcrash/<date>-matrix.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time

import anyio

from yovahti.agents.cards import write_cards
from yovahti.agents.llm import Ledger
from yovahti.mcp_server.server import load_validation_network
from yovahti.netcrash.judge import DEFAULT_JUDGES
from yovahti.netcrash.runner import run_suite, timestamp
from yovahti.netcrash.suite import BY_ID, TESTS
from yovahti.paths import RESULTS

OUT = RESULTS / "netcrash"


def show(line: str) -> None:
    print(line, flush=True)


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]+", "_", s.split(":", 1)[-1])


def write_matrix(prefix: str) -> None:
    cards = sorted(p for agent in ("energy-agent", "sloppy-agent")
                   for p in OUT.glob(f"{prefix}-{agent}-*.json"))
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in cards]
    if not rows:
        return
    ids = [t["id"] for t in rows[0]["tests"]]
    sym = {"pass": "✅", "fail": "❌", "flaky": "⚠️", "inconclusive": "❔",
           "not_applicable": "—", "error": "💥"}
    lines = [f"# NetCrash matrix, {prefix}", "",
             "Suite v{}, {} runs per test, scoring {}. ✅ pass · ❌ fail · ⚠️ flaky · ❔ "
             "inconclusive (needs judge) · — not applicable · 💥 error.".format(
                 rows[0]["suite"]["version"], rows[0]["runs_per_test"],
                 rows[0]["summary"]["scoring"]), "",
             "| Agent | Model | Score | Coverage | " + " | ".join(ids) + " | Cost |",
             "|---|---|---:|---:|" + "---|" * len(ids) + "---:|"]
    for r in sorted(rows, key=lambda r: (r["target"]["agent_card"]["id"], r["model"]["name"])):
        cells = [sym.get(t["verdict"], t["verdict"]) for t in r["tests"]]
        s = r["summary"]
        lines.append(f"| {r['target']['agent_card']['id']} | {r['model']['name']} | {s['score']} "
                     f"| {s['coverage']} % | " + " | ".join(cells) + f" | €{s['cost_eur']:.3f} |")
    lines += ["", "Tests: " + ", ".join(f"{t['id']} {t['title']}" for t in rows[0]["tests"])]
    (OUT / f"{prefix}-matrix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", required=True)
    ap.add_argument("--agents", nargs="+", default=["energy-agent"])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--tests", nargs="+", default=[t.id for t in TESTS])
    ap.add_argument("--start", default="2025-10-28 22:00")
    ap.add_argument("--tag", default="", help="separate output set, e.g. n20")
    ap.add_argument("--judges", nargs="*", default=None,
                    help="judge models for inconclusive text verdicts (default panel if the "
                         "flag is given without models; none if omitted)")
    a = ap.parse_args()
    # expected tool failures (stand-in faults) and per-request HTTP lines are not news
    for name in ("mcp", "httpx", "uvicorn"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    t0 = time.time()
    base = load_validation_network(a.start)
    hashes = write_cards()
    tests = [BY_ID[t] for t in a.tests]
    judges = None if a.judges is None else (a.judges or DEFAULT_JUDGES)
    print(f"network ready in {time.time() - t0:.0f}s, now {base.time(base.now)}; cards "
          + ", ".join(f"{k} {v[:12]}" for k, v in hashes.items()), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    date = timestamp() + (f"-{a.tag}" if a.tag else "")
    for agent in a.agents:
        for m in a.models:
            t1 = time.time()
            card = anyio.run(lambda m=m, agent=agent: run_suite(
                base, tests, agent, m, a.runs, show, judges=judges))
            path = OUT / f"{date}-{agent}-{slug(m)}.json"
            path.write_text(json.dumps(card, indent=1, ensure_ascii=False), encoding="utf-8")
            s = card["summary"]
            print(f"== {agent} x {m}: score {s['score']}, coverage {s['coverage']} %, "
                  f"EUR {s['cost_eur']:.3f}, {time.time() - t1:.0f}s", flush=True)
            write_matrix(date)
    print("spent so far:", {p: round(Ledger().spent(p), 3) for p in ("otari", "featherless")})


if __name__ == "__main__":
    main()
