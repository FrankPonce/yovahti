"""Measured energy of a *local* agent night on the laptop GPU (I36; E30 was an estimate).

The energy agent runs one validation night through MCP on a local model (Ollama, RTX 4050
Laptop GPU) while ``nvidia-smi`` samples board power every 100 ms. Reported:

* GPU energy over the agent's run, gross and above the idle baseline (measured 30 s before,
  model loaded and warm), per 1k tokens and per call;
* that energy against the kWh the same night's agent schedule saved (the replay in
  run_agent_night.py), i.e. the net-savings question of E30 with a measurement instead of
  published figures.

Scope, stated in the result: GPU board power only. CPU, RAM, screen and PSU losses are not
measured (no wall meter); a laptop's whole-system draw under this load is perhaps 1.5-2x the
GPU's, so the fraction is given gross, above idle and with a 2x system factor.

Run: uv run python scripts/local_model_energy.py [--model ollama:qwen3:4b] [--hourly]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from yovahti.paths import RESULTS, ROOT

SYSTEM_FACTOR = 2.0


class PowerLog:
    def __init__(self, period_ms: int = 100) -> None:
        self.samples: list[tuple[float, float]] = []
        self._p = subprocess.Popen(
            ["nvidia-smi", "--query-gpu=power.draw", "--format=csv,noheader,nounits",
             f"-lms={period_ms}"], stdout=subprocess.PIPE, text=True)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self._p.stdout:
            with contextlib.suppress(ValueError):
                self.samples.append((time.time(), float(line.strip())))

    def window(self, t0: float, t1: float) -> tuple[float, float, int]:
        """Energy (Wh, trapezoid) and mean power (W) between t0 and t1."""
        s = [(t, p) for t, p in self.samples if t0 <= t <= t1]
        if len(s) < 2:
            return 0.0, 0.0, len(s)
        j = sum((b[0] - a[0]) * (a[1] + b[1]) / 2 for a, b in zip(s, s[1:], strict=False))
        return j / 3600, j / (s[-1][0] - s[0][0]), len(s)

    def stop(self) -> None:
        self._p.terminate()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="ollama:qwen3:4b")
    ap.add_argument("--hourly", action="store_true")
    ap.add_argument("--idle", type=float, default=30.0)
    a = ap.parse_args()
    name = a.model.split(":", 1)[1]
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,power.limit", "--format=csv,noheader"],
                         capture_output=True, text=True).stdout.strip()

    log = PowerLog()
    t = time.time()                      # warm-up: load the weights onto the GPU
    httpx.post("http://localhost:11434/api/generate", timeout=300,
               json={"model": name, "prompt": "ok", "keep_alive": "30m",
                     "options": {"num_predict": 1}})
    load_wh, _, _ = log.window(t, time.time())
    time.sleep(3)
    t_idle = time.time()
    time.sleep(a.idle)
    _, idle_w, _ = log.window(t_idle, time.time())

    cmd = [sys.executable, "scripts/run_agent_night.py", "--model", a.model]
    cmd += ["--hourly"] if a.hourly else []
    t0 = time.time()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          env=env)
    t1 = time.time()
    log.stop()
    print(proc.stdout[-2500:], proc.stderr[-1500:], sep="\n")
    wh, mean_w, n = log.window(t0, t1)
    net_wh = max(wh - idle_w * (t1 - t0) / 3600, 0.0)

    saved = next(line.split()[-1] for line in proc.stdout.splitlines()
                 if line.startswith("saved to "))
    night = json.loads(Path(saved).read_text(encoding="utf-8"))
    cmp = night["comparison"]
    row = next(v for k, v in cmp["rows"].items() if k.startswith("Agent"))
    agent_kwh = cmp["b0_kwh"] * row["kwh_saved_pct"] / 100
    # the denominator is what a night's work saves: the agent's own result if it applied a
    # plan, else the planner's risk-checked plan on the same night (same protocol), labelled
    ref = cmp["rows"]["Planner alone (same protocol)"]
    saved_kwh = agent_kwh if agent_kwh > 0 else cmp["b0_kwh"] * ref["kwh_saved_pct"] / 100
    basis = "agent" if agent_kwh > 0 else "planner alone, same night (the agent applied nothing)"
    calls = [night["trace"]["usage"]] + [h["usage"] for h in night["hourly"]]
    tokens = sum(u.get("prompt_tokens", 0) + u.get("completion_tokens", 0) for u in calls)
    n_calls = sum(u.get("calls", 0) for u in calls)

    def share(e_wh: float) -> float | None:
        return round(100 * e_wh / 1000 / saved_kwh, 4) if saved_kwh > 0 else None

    out = {"gpu": gpu, "model": a.model, "hourly": a.hourly, "night": night["run"],
           "outcome": night["trace"]["outcome"], "seconds": round(t1 - t0, 1),
           "samples": n, "idle_w": round(idle_w, 2), "mean_w": round(mean_w, 2),
           "load_wh": round(load_wh, 4), "gpu_wh_gross": round(wh, 4),
           "gpu_wh_above_idle": round(net_wh, 4), "llm_calls": n_calls, "tokens": tokens,
           "gpu_wh_per_1k_tokens": round(1000 * wh / tokens, 4) if tokens else None,
           "gpu_wh_per_call": round(wh / n_calls, 4) if n_calls else None,
           "changes": night["changes"], "agent_saved_kwh": round(agent_kwh, 2),
           "night_saved_kwh": round(saved_kwh, 2), "savings_basis": basis,
           "share_of_savings_pct": {"gpu_gross": share(wh), "gpu_above_idle": share(net_wh),
                                    f"system_{SYSTEM_FACTOR:g}x_gross": share(SYSTEM_FACTOR * wh)},
           "scope": "GPU board power from nvidia-smi only; CPU, RAM, screen, PSU not measured",
           "note": "the night itself (simulator, MCP server, replay) runs in the same window "
                   "on the CPU; only the GPU is attributed to the model"}
    path = RESULTS / "compare" / f"local_model_energy{'_hourly' if a.hourly else ''}.json"
    path.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
