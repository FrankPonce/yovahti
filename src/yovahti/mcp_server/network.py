"""The operator-side view of the network that the MCP server exposes (ARCHITECTURE §8).

`Network` is what an agent can see and touch, at a simulated clock ``now`` (a quarter-hour
index into the world). It is deliberately a *view*, not the world:

* KPIs are what was measured up to ``now - 1``, each with its data timestamp (stale data is
  visible, never hidden);
* forecasts are the ones issued at or before ``now`` (no hindsight);
* changes go through ``admit()`` and the arbiter before anything is scheduled, and every
  outcome (applied, refused, rolled back) gets a receipt.

Cells are (sector, layer) pairs: ``low`` is the coverage layer (LTE 700/800, never sleeps),
``mid`` (LTE 1800 + NR 2100) and ``nr3500`` are capacity layers that may sleep. Clusters are
groups of ten neighbouring site ids, a placeholder until the Turku layout exists (S3).

Known gaps in this first slice (tracked in ISSUES): scheduled sleep is recorded but the KPIs
still show the real, un-slept traffic (the closed loop with the simulator comes with S7);
request identity is fixed per server instance until RFC 9421 signatures land (I20).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
import rfc8785

from yovahti.arbiter.core import Arbiter, Verdict
from yovahti.forecast.quantile import HORIZON
from yovahti.plan.dp import STATES, DPPlanner, PlannerConfig
from yovahti.trust.admission import Admission, AgentIdentity, AllowListAdmission
from yovahti.world.data import BANDWIDTH, EFFICIENCY, WorldData
from yovahti.world.sim import ASLEEP, AWAKE, WorldConfig

TZ = "Europe/Bratislava"
LAYERS = {"low": ["LTE_700", "LTE_800"], "mid": ["LTE_1800", "NR_2100"], "nr3500": ["NR_3500"]}
FORECAST_TARGET = {"low": "low", "mid": "mid", "nr3500": "nr"}
CAPACITY_LAYERS = ("mid", "nr3500")
SITES_PER_CLUSTER = 10


def cell_id(sector: str, layer: str) -> str:
    """'Site 107/1' + 'mid' -> 's107-1/mid'."""
    m = re.match(r"\D*(\d+)\D+(\d+)", sector)
    base = f"s{m.group(1)}-{m.group(2)}" if m else sector.replace(" ", "").replace("/", "-")
    return f"{base}/{layer}"


def _iso(ts: pd.Timestamp) -> str:
    return ts.tz_convert(TZ).isoformat()


@dataclass
class Change:
    change_id: str
    agent: str
    actions: list[dict]
    rationale: str
    proposed_at: str
    status: str = "proposed"          # proposed | applied | refused | rolled_back | unknown
    reasons: list[str] = field(default_factory=list)
    receipts: list[dict] = field(default_factory=list)
    previous: dict | None = None      # schedule before apply, for rollback (I7)


class Network:
    """Agent-facing view over a world, its forecasts and a sleep schedule."""

    def __init__(self, world: WorldData, forecasts: dict[str, dict], *, now: int = 0,
                 issue_offset: int = 0, world_cfg: WorldConfig | None = None,
                 protected: set[str] | None = None, admission: Admission | None = None,
                 arbiter: Arbiter | None = None, alarms: list[dict] | None = None,
                 events: list[dict] | None = None):
        self.w, self.f = world, forecasts
        self.wc = world_cfg or WorldConfig()
        self.now = now
        self.issue_offset = issue_offset
        self.protected = protected or set()
        self.admission = admission or AllowListAdmission()
        self.arbiter = arbiter or Arbiter()
        self.alarms = alarms or []
        self.events = events or []
        self.cells: dict[str, tuple[int, str]] = {}
        for s, sec in enumerate(world.sectors):
            for layer, carriers in LAYERS.items():
                if any(world.present[c][s] for c in carriers):
                    self.cells[cell_id(sec, layer)] = (s, layer)
        sites = sorted({sec.split("/")[0] for sec in world.sectors},
                       key=lambda x: int(re.sub(r"\D", "", x) or 0))
        self.cluster_of_site = {site: f"C{i // SITES_PER_CLUSTER + 1:02d}"
                                for i, site in enumerate(sites)}
        # scheduled states per quarter-hour and sector (what the operator has committed to)
        self.mid_state = np.full((world.T, world.S), AWAKE, dtype=np.int8)
        self.nr_state = np.full((world.T, world.S), AWAKE, dtype=np.int8)
        self.changes: dict[str, Change] = {}
        self.planner = DPPlanner(world, forecasts, PlannerConfig(), self.wc,
                                 issue_offset=issue_offset)
        self._cost_cache: dict[int, np.ndarray] = {}

    # ------------------------------------------------------------------ lookup helpers
    def cluster(self, s: int) -> str:
        return self.cluster_of_site[self.w.sectors[s].split("/")[0]]

    def clusters(self) -> list[str]:
        return sorted(set(self.cluster_of_site.values()))

    def resolve(self, cells: list[str]) -> list[tuple[str, int, str]]:
        unknown = [c for c in cells if c not in self.cells]
        if unknown:
            raise ValueError(f"unknown cells: {unknown[:5]}")
        return [(c, *self.cells[c]) for c in cells]

    def cells_in(self, cluster: str) -> list[str]:
        if cluster != "all" and cluster not in self.clusters():
            raise ValueError(f"unknown cluster {cluster!r}; known: {self.clusters()}")
        return [c for c, (s, _) in self.cells.items()
                if cluster == "all" or self.cluster(s) == cluster]

    def time(self, t: int) -> str:
        return _iso(self.w.times[min(max(t, 0), self.w.T - 1)])

    def state(self, t: int, s: int, layer: str) -> str:
        if layer == "low":
            return "awake"
        arr = self.mid_state if layer == "mid" else self.nr_state
        return "asleep" if arr[t, s] == ASLEEP else "awake"

    def latest_issue(self) -> int:
        """Position k of the newest forecast issued at or before ``now`` (no hindsight)."""
        issues = np.asarray(self.f["mid"]["issues"]) - self.issue_offset
        k = int(np.searchsorted(issues, self.now, side="right")) - 1
        if k < 0:
            raise LookupError("no forecast issued yet at this time")
        return k

    def costs(self, k: int) -> np.ndarray:
        if k not in self._cost_cache:
            self._cost_cache = {k: self.planner.costs(k)}
        return self._cost_cache[k]

    # ------------------------------------------------------------------ read tools
    def list_cells(self, cluster: str) -> dict:
        out = []
        for c in self.cells_in(cluster):
            s, layer = self.cells[c]
            out.append({"cell": c, "sector": self.w.sectors[s], "cluster": self.cluster(s),
                        "layer": layer, "carriers": [x for x in LAYERS[layer]
                                                     if self.w.present[x][s]],
                        "role": "coverage" if layer == "low" else "capacity",
                        "can_sleep": layer in CAPACITY_LAYERS and c not in self.protected,
                        "protected": c in self.protected})
        return {"cluster": cluster, "clusters": self.clusters(), "cells": out}

    def get_cell_kpis(self, cells: list[str], window: int) -> dict:
        window = int(np.clip(window, 1, 96))
        t1 = self.now                                     # values up to now - 1 are known
        t0 = max(0, t1 - window)
        rows = []
        for c, s, layer in self.resolve(cells):
            carriers = [x for x in LAYERS[layer] if self.w.present[x][s]]
            cap = sum(EFFICIENCY[x] * BANDWIDTH[x] for x in carriers)
            for t in range(t0, t1):
                mb = float(sum(self.w.vol[x][t, s] for x in carriers))
                rows.append({"cell": c, "time": self.time(t),
                             "load_pct": round(mb / cap, 2) if cap else 0.0,
                             "dl_mb": round(mb, 1), "state": self.state(t, s, layer)})
        return {"now": self.time(self.now), "data_until": self.time(t1 - 1) if t1 else None,
                "note": "15-min averages; loads are the measured traffic (closed loop: S7)",
                "kpis": rows}

    def get_alarms(self, cluster: str, window: int) -> dict:
        lo = self.now - int(window)
        sel = [a for a in self.alarms
               if lo <= a.get("t", 0) < self.now and cluster in ("all", a.get("cluster"))]
        return {"source": "operator alarm feed" if self.alarms else
                "no alarm feed in this world (empty, not 'all clear')",
                "alarms": [{**{k: v for k, v in a.items() if k != "t"},
                            "time": self.time(a["t"])} for a in sel]}

    def get_events(self, window: int) -> dict:
        hi = self.now + int(window)
        sel = [e for e in self.events if self.now - 96 <= e.get("t", 0) < hi]
        return {"source": "event calendar and operator notes" if self.events else
                "no event calendar loaded (empty, not 'nothing happening')",
                "events": [{**{k: v for k, v in e.items() if k != "t"},
                            "time": self.time(e["t"])} for e in sel]}

    def get_prices(self, window: int) -> dict:
        idx = range(self.now, min(self.w.T, self.now + int(np.clip(window, 1, 96))))
        return {"unit": "EUR/MWh", "market": "Nord Pool FI day-ahead (internal use only)",
                "prices": [{"time": self.time(t), "price": round(float(self.w.price[t]), 2)}
                           for t in idx]}

    def get_carbon(self, window: int) -> dict:
        idx = range(max(0, self.now - int(np.clip(window, 1, 96))), self.now)
        return {"unit": "gCO2/kWh", "source": "Fingrid dataset 265 (realised, CC BY 4.0)",
                "carbon": [{"time": self.time(t), "gco2_per_kwh": round(float(self.w.co2[t]), 1)}
                           for t in idx]}

    def forecast_load(self, cells: list[str], horizon: int) -> dict:
        k = self.latest_issue()
        issue = int(self.f["mid"]["issues"][k]) - self.issue_offset
        lag = self.now - issue                         # quarter-hours since issue
        horizon = int(np.clip(horizon, 1, HORIZON - lag))
        out = []
        for c, s, layer in self.resolve(cells):
            tgt = FORECAST_TARGET[layer]
            carriers = [x for x in LAYERS[layer] if self.w.present[x][s]]
            cap = sum(EFFICIENCY[x] * BANDWIDTH[x] for x in carriers)
            pts = []
            for h in range(lag, lag + horizon):
                q = {f"p{int(qq * 100)}_mb": round(float(self.f[tgt][qq][k][h, s]), 1)
                     for qq in (0.1, 0.5, 0.9)}
                q["p90_load_pct"] = round(q["p90_mb"] / cap, 2) if cap else 0.0
                pts.append({"time": self.time(issue + h), **q})
            out.append({"cell": c, "forecast": pts})
        return {"issued_at": self.time(issue), "model": "LightGBM quantile, rolling Mondrian "
                "calibration (D30)", "forecasts": out}

    # ------------------------------------------------------------------ plan tools
    def _horizon_window(self, horizon: int) -> tuple[int, int, int]:
        k = self.latest_issue()
        lag = self.now - (int(self.f["mid"]["issues"][k]) - self.issue_offset)
        return k, lag, int(np.clip(horizon, 1, HORIZON - lag))

    def optimise_plan(self, cluster: str, horizon: int) -> dict:
        """B4 plan for the cluster's sectors from now; returns sleep windows and expected kWh."""
        k, lag, horizon = self._horizon_window(horizon)
        sectors = sorted({self.cells[c][0] for c in self.cells_in(cluster)})
        cost = self.costs(k)[lag:lag + horizon][:, sectors]          # [h, s, 4]
        cur = np.array([2 * self.mid_state[self.now, s] + self.nr_state[self.now, s]
                        for s in sectors], dtype=np.int64)
        path = self.planner.solve(cost, cur)                          # [h, s]
        hh = np.arange(horizon)[:, None]
        ss = np.arange(len(sectors))[None, :]
        planned_wh = float(cost[hh, ss, path].sum())
        awake_wh = float(cost[..., 0].sum())
        actions = []
        for j, s in enumerate(sectors):
            for layer, col in (("mid", 0), ("nr3500", 1)):
                c = cell_id(self.w.sectors[s], layer)
                if c not in self.cells or c in self.protected:
                    continue
                asleep = STATES[path[:, j], col] == ASLEEP
                for a, b in _runs(asleep):
                    actions.append({"cell": c, "action": "sleep", "from_qh": a,
                                    "quarter_hours": b - a, "from": self.time(self.now + a),
                                    "until": self.time(self.now + b)})
        return {"cluster": cluster, "issued_at": self.time(self.now), "horizon_qh": horizon,
                "risk": "every sleep keeps the receiving layer under its limit at the P90 "
                        "forecast x peak margin",
                "expected_kwh_saved": round((awake_wh - planned_wh) / 1000, 2),
                "expected_kwh_always_on": round(awake_wh / 1000, 2),
                "energy_scope": "capacity radios (mid, NR 3500) over the horizon, net of the "
                                "extra low-band load from moved traffic; planner twin (D5), "
                                "not the world",
                "actions": actions}

    # ------------------------------------------------------------------ act tools
    def propose_change(self, agent: AgentIdentity, actions: list[dict], rationale: str) -> dict:
        clean = []
        for a in actions:
            c = a.get("cell")
            if c not in self.cells:
                raise ValueError(f"unknown cell {c!r}")
            if a.get("action") not in ("sleep", "wake"):
                raise ValueError("action must be 'sleep' or 'wake'")
            start, n = int(a.get("from_qh", 0)), int(a.get("quarter_hours", 1))
            if start < 0 or n < 1:
                raise ValueError("from_qh must be >= 0 and quarter_hours >= 1")
            clean.append({"cell": c, "action": a["action"], "from_t": self.now + start,
                          "until_t": self.now + start + n})
        body = {"agent": agent.agent_id, "actions": clean, "rationale": rationale,
                "proposed_at": self.now}
        cid = "chg-" + hashlib.sha256(rfc8785.dumps(body)).hexdigest()[:12]
        if cid not in self.changes:
            self.changes[cid] = Change(cid, agent.agent_id, clean, rationale,
                                       self.time(self.now))
        tier = self.arbiter.approval_tier(len({a["cell"] for a in clean}))
        return {"change_id": cid, "status": self.changes[cid].status,
                "approval_tier": tier, "actions": [self._show(a) for a in clean]}

    def apply_change(self, agent: AgentIdentity, change_id: str) -> dict:
        ch = self._get(change_id)
        if ch.agent != agent.agent_id:
            return self._refuse(ch, ["I5 scope: change was proposed by another agent"],
                                keep_status=True)
        if ch.status != "proposed":
            return {"change_id": change_id, "status": ch.status,
                    "reasons": [f"change is already {ch.status}"]}
        adm = self.admission.admit(agent)
        if not adm.admitted:
            return self._refuse(ch, [f"I6 admission: {r}" for r in adm.reasons])
        if any(a["from_t"] < self.now for a in ch.actions):
            return self._refuse(ch, ["stale: the change starts in the past; propose again"])
        verdict: Verdict = self.arbiter.check(self, agent, ch.actions)
        if not verdict.ok:
            return self._refuse(ch, verdict.reasons)
        ch.previous = {"mid": self.mid_state.copy(), "nr": self.nr_state.copy()}
        for a in ch.actions:
            s, layer = self.cells[a["cell"]]
            arr = self.mid_state if layer == "mid" else self.nr_state
            arr[a["from_t"]:a["until_t"], s] = ASLEEP if a["action"] == "sleep" else AWAKE
        ch.status = "applied"
        return {"change_id": change_id, "status": "applied",
                "receipt": self._receipt(ch, "applied")}

    def get_change_status(self, change_id: str) -> dict:
        ch = self._get(change_id)
        return {"change_id": change_id, "status": ch.status, "reasons": ch.reasons,
                "actions": [self._show(a) for a in ch.actions], "receipts": ch.receipts}

    def rollback(self, agent: AgentIdentity, change_id: str) -> dict:
        ch = self._get(change_id)
        if ch.status != "applied" or ch.previous is None:
            return {"change_id": change_id, "status": ch.status,
                    "reasons": ["only applied changes can be rolled back"]}
        # restore only the future: the past already happened
        self.mid_state[self.now:] = ch.previous["mid"][self.now:]
        self.nr_state[self.now:] = ch.previous["nr"][self.now:]
        ch.status = "rolled_back"
        return {"change_id": change_id, "status": "rolled_back",
                "receipt": self._receipt(ch, "rolled_back", by=agent.agent_id)}

    def advance(self, quarter_hours: int = 1) -> None:
        """Move the clock (harness only; agents cannot move time)."""
        self.now = min(self.w.T - 1, self.now + quarter_hours)

    # ------------------------------------------------------------------ internals
    def _get(self, change_id: str) -> Change:
        if change_id not in self.changes:
            raise ValueError(f"unknown change {change_id!r}")
        return self.changes[change_id]

    def _show(self, a: dict) -> dict:
        return {"cell": a["cell"], "action": a["action"], "from": self.time(a["from_t"]),
                "until": self.time(a["until_t"])}

    def _refuse(self, ch: Change, reasons: list[str], keep_status: bool = False) -> dict:
        if not keep_status:
            ch.status, ch.reasons = "refused", reasons
        return {"change_id": ch.change_id, "status": "refused", "reasons": reasons,
                "receipt": self._receipt(ch, "refused", reasons=reasons)}

    def _receipt(self, ch: Change, outcome: str, **extra: Any) -> dict:
        """Unsigned receipt (JCS-canonical, hashed); DSSE signing arrives with S8."""
        body = {"change_id": ch.change_id, "agent": ch.agent, "outcome": outcome,
                "actions": [self._show(a) for a in ch.actions], "at": self.time(self.now),
                "recorded": datetime.now(UTC).isoformat(timespec="seconds"), **extra}
        rec = {**body, "sha256": hashlib.sha256(rfc8785.dumps(body)).hexdigest(),
               "signature": None}
        ch.receipts.append(rec)
        return rec


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[(start, end)] of consecutive True runs."""
    out, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        if not v and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(mask)))
    return out

