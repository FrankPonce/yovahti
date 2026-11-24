"""Real RAN in the loop, spike (I35, roadmap tier 2): srsRAN 4G over ZeroMQ in WSL.

Two parts, both on a real LTE protocol stack (EPC, eNB, UE; RRC/NAS attach, GTP user plane):

1. Wake latency: N sleep/wake cycles of the cell (eNB stopped, started), timed inside WSL from
   "start" to the eNB's ready line and to the first user-plane packet reaching the UE (ping).
   The simulator and the arbiter assume a slept layer can carry traffic again within one
   quarter-hour (900 s); this measures the software side of that assumption.
2. In the loop: a validation night on the MCP network. The planner's changes go through the
   arbiter (I1-I9, simulated operator for I8) as for any agent; one cell the change sleeps is
   *mapped* to the real eNB. Every quarter-hour (compressed to --tick seconds) the stepped
   world's state of that cell is commanded to the eNB, and the eNB's and UE's real state is
   read back and compared.

What it is not: no radio hardware, so no power-amplifier warm-up, no real power draw, no RF;
the ZeroMQ link runs far below air rates. Throughput numbers are the ZMQ link's, labelled so.

Run: uv run python scripts/ran_spike.py [--trials 10] [--hours 6] [--tick 15]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import time
from pathlib import Path

from yovahti.agents.evaluate import apply_plan_alone
from yovahti.mcp_server.network import planner_operator
from yovahti.mcp_server.server import load_validation_network
from yovahti.paths import RESULTS, ROOT

SH = f"/mnt/{ROOT.drive[0].lower()}{ROOT.as_posix()[2:]}/scripts/ran/ran.sh"   # WSL view


def ran(*args: str, timeout: float = 120) -> str:
    r = subprocess.run(["wsl", "-d", "Ubuntu", "-u", "root", "--", "bash", SH, *args],
                       capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()


def kv(text: str) -> dict[str, str]:
    return dict(re.findall(r"(\w+)=(\S+)", text))


def num(x: str) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def wake_trials(n: int, off: float) -> dict:
    rows = []
    for i in range(n):
        r = kv(ran("trial", str(off), timeout=240))
        rows.append({k: num(v) for k, v in r.items()})
        print(f"  trial {i + 1}: {r}", flush=True)
    ok = [r["traffic_s"] for r in rows if r.get("traffic_s") is not None]
    ready = [r["enb_ready_s"] for r in rows if r.get("enb_ready_s") is not None]
    return {"trials": rows, "off_s": off, "reattached": len(ok), "of": n,
            "traffic_s_median": round(statistics.median(ok), 2) if ok else None,
            "traffic_s_max": round(max(ok), 2) if ok else None,
            "enb_ready_s_median": round(statistics.median(ready), 2) if ready else None,
            "share_of_quarter_hour_max_pct": round(100 * max(ok) / 900, 2) if ok else None,
            "ue_retries": sum(int(r.get("ue_retries") or 0) for r in rows)}


def in_the_loop(hours: int, tick: float, start: str) -> dict:
    net = load_validation_network(start)
    net.approver = planner_operator(net)
    apply_plan_alone(net, "C01")                       # planner as agent, through the arbiter
    applied = [c for c in net.changes.values() if c.status == "applied"]
    cells = [a["cell"] for c in applied for a in c.actions if a["action"] == "sleep"]
    if not cells:
        return {"error": "no applied sleep in the plan"}
    cell = max(set(cells), key=cells.count)
    s, layer = net.cells[cell]
    # fresh stack for the night: after the trials srsEPC holds one stale context per re-attach
    # and stops reaching an idle UE by paging (an EPC artefact, not the cell's state)
    ran("down")
    fresh = kv(ran("up", timeout=240))
    t0 = net.now
    log, prev, wakes, mism = [], "awake", [], 0          # the stack starts up and attached
    for _ in range(4 * hours):
        net.advance(1)
        want = net.actual(net.now - 1, s, layer)
        if want != prev:
            r = kv(ran("enb-stop" if want == "asleep" else "enb-start", timeout=240))
            if want == "awake":
                wakes.append({k: num(v) for k, v in r.items()})
            prev = want
        time.sleep(max(0.0, tick - 1.5))
        st = kv(ran("state"))
        real = "awake" if st.get("enb") == "1" and st.get("ping_ms", "none") != "none" else (
            "asleep" if st.get("enb") == "0" else "degraded")
        mism += real != want
        log.append({"t": net.time(net.now - 1), "commanded": want, "real": real,
                    "ue_ip": st.get("ue_ip"), "ping_ms": num(st.get("ping_ms"))})
        print(f"  {net.time(net.now - 1)} {cell}: commanded {want:6s} real {real}", flush=True)
    if prev == "asleep":
        ran("enb-start", timeout=240)
    return {"fresh_up": fresh, "cell": cell, "layer": layer, "from": net.time(t0),
            "quarter_hours": 4 * hours,
            "tick_s": tick, "changes": {c.change_id: c.status for c in net.changes.values()},
            "transitions": sum(1 for a, b in zip(log, log[1:], strict=False)
                               if a["commanded"] != b["commanded"]),
            "wake_to_traffic_s": wakes, "mismatched_quarter_hours": mism, "log": log}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--off", type=float, default=10.0)
    ap.add_argument("--hours", type=int, default=6)
    ap.add_argument("--tick", type=float, default=15.0)
    ap.add_argument("--start", default="2025-10-27 22:00")
    a = ap.parse_args()
    ran("down")
    t = time.time()
    up = ran("up", timeout=180)
    print("up:", up, f"({time.time() - t:.1f}s)", flush=True)
    if "ue_ip=" not in up:
        raise SystemExit("UE did not attach; see /tmp/ran/*.out in WSL")
    base = {"attach_s_incl_epc_enb": round(time.time() - t, 1),
            "zmq_downlink_mbps": num(ran("iperf", "5")), "state": kv(ran("state"))}
    print("baseline", base, flush=True)
    out = {"stack": "srsRAN 4G release_23_11, ZeroMQ virtual radio, WSL2 Ubuntu 26.04",
           "baseline": base, "wake": wake_trials(a.trials, a.off)}
    print("wake", {k: v for k, v in out["wake"].items() if k != "trials"}, flush=True)
    out["loop"] = in_the_loop(a.hours, a.tick, a.start)
    out["after_wake_zmq_downlink_mbps"] = num(ran("iperf", "5"))
    ran("down")
    path = RESULTS / "ran" / "srsran_spike.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    print("wrote", Path(path).relative_to(ROOT))


if __name__ == "__main__":
    main()
