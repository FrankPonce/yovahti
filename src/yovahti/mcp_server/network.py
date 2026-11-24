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

The loop is closed (I30): the world is stepped quarter-hour by quarter-hour as the clock
moves, so KPIs show the traffic as it was actually carried (including traffic moved by the
agent's own sleeps), the states the radios really took, and watchdog wake-ups (which also
raise an alarm). Control- and measurement-plane faults (`world.faults`) sit in between:
late or ignored switches, lost acknowledgements (outcome ``unknown``, I33), KPI lag and gaps.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
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
from yovahti.trust.signing import new_key, public_part, sign_envelope, verify_envelope
from yovahti.world.data import BANDWIDTH, EFFICIENCY, WorldData
from yovahti.world.faults import Faults
from yovahti.world.sim import ASLEEP, AWAKE, Stepper, WorldConfig

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
    status: str = "proposed"   # proposed | applied | refused | rolled_back | unknown | failed
    reasons: list[str] = field(default_factory=list)
    receipts: list[dict] = field(default_factory=list)
    previous: dict | None = None      # schedule before apply, for rollback (I7)
    applied_at: int | None = None
    carried_out: bool | None = None   # hidden truth behind an ``unknown`` outcome
    watchdog_overrides: int = 0
    role: str = "energy"


class Network:
    """Agent-facing view over a world, its forecasts and a sleep schedule."""

    def __init__(self, world: WorldData, forecasts: dict[str, dict], *, now: int = 0,
                 issue_offset: int = 0, world_cfg: WorldConfig | None = None,
                 protected: set[str] | None = None, admission: Admission | None = None,
                 arbiter: Arbiter | None = None, alarms: list[dict] | None = None,
                 events: list[dict] | None = None, faults: Faults | None = None,
                 receipt_key: dict | None = None,
                 approver: Callable[[Change, int], str | None] | None = None,
                 clusters: dict[str, str] | None = None):
        self.w, self.f = world, forecasts
        # I7: receipts are DSSE envelopes signed with the network's key
        self.receipt_key = receipt_key or new_key()
        # I8: who approves changes above the arbiter's auto tier. None = a human must call
        # approve(); a callable is a *simulated* operator (returns approver name or None)
        self.approver = approver
        self.approvals: dict[str, dict] = {}
        self.holds: list[dict] = []          # I9 coverage holds
        self.wc = world_cfg or WorldConfig()
        self.now = now
        self.issue_offset = issue_offset
        self.protected = protected or set()
        self.admission = admission or AllowListAdmission()
        self.arbiter = arbiter or Arbiter()
        self.alarms = list(alarms or [])
        self.faults = faults or Faults()
        self._rng = np.random.default_rng(self.faults.seed)
        self._dropout = self.faults.dropout_mask(world.T, world.S)
        self.events = events or []
        self.cells: dict[str, tuple[int, str]] = {}
        for s, sec in enumerate(world.sectors):
            for layer, carriers in LAYERS.items():
                if any(world.present[c][s] for c in carriers):
                    self.cells[cell_id(sec, layer)] = (s, layer)
        sites = sorted({sec.split("/")[0] for sec in world.sectors},
                       key=lambda x: int(re.sub(r"\D", "", x) or 0))
        self.cluster_of_site = clusters or {site: f"C{i // SITES_PER_CLUSTER + 1:02d}"
                                            for i, site in enumerate(sites)}
        # scheduled states per quarter-hour and sector (what the operator has committed to)
        self.mid_state = np.full((world.T, world.S), AWAKE, dtype=np.int8)
        self.nr_state = np.full((world.T, world.S), AWAKE, dtype=np.int8)
        self.changes: dict[str, Change] = {}
        self.planner = DPPlanner(world, forecasts, PlannerConfig(), self.wc,
                                 issue_offset=issue_offset)
        self._cost_cache: dict[int, np.ndarray] = {}
        self._reset_sim()

    # ------------------------------------------------------------------ closed loop (I30)
    def _reset_sim(self) -> None:
        self.sim = Stepper(self.w, self.wc)          # the world under the schedule
        self.base = Stepper(self.w, self.wc)         # always-on counterfactual, for reports
        self._awake = np.zeros(self.w.S, dtype=np.int8)

    def _sync(self) -> None:
        """Step the world up to (not including) ``now``; rebuild if the clock went back."""
        if self.sim.t > self.now:
            self._reset_sim()
        f = self.faults
        while self.sim.t < min(self.now, self.w.T):
            t = self.sim.t
            ms = f.commanded(self.mid_state, t, self.sim.prev_mid)
            ns = f.commanded(self.nr_state, t, self.sim.prev_nr)
            st = self.sim.step(ms, ns)
            self.base.step(self._awake, self._awake)
            for s in np.where(st.woken)[0]:
                self._watchdog(t, int(s))

    def timeline(self, cell: str) -> np.ndarray:
        """[T] int8: what the radio actually did before now, then what is scheduled."""
        self._sync()
        s, layer = self.cells[cell]
        if layer == "low":
            return np.full(self.w.T, AWAKE, dtype=np.int8)
        sched = (self.mid_state if layer == "mid" else self.nr_state)[:, s].copy()
        past = (self.sim.mid_s if layer == "mid" else self.sim.nr_s)[:self.now, s]
        sched[:self.now] = past
        return sched

    def watchdog_hold(self, s: int) -> int:
        """Last quarter-hour the watchdog keeps sector ``s`` awake (-1 if none)."""
        self._sync()
        return int(self.sim.hold_until[s])

    def receipt_jwks(self) -> dict:
        return {"keys": [public_part(self.receipt_key)]}

    def approve(self, change_id: str, approver: str, note: str = "") -> dict:
        """I8: record a human approval (operator side; never an agent tool)."""
        ch = self._get(change_id)
        rec = {"change_id": change_id, "approver": approver, "note": note,
               "at": self.time(self.now),
               "actions_sha256": hashlib.sha256(rfc8785.dumps(ch.actions)).hexdigest()}
        self.approvals[change_id] = rec
        self._receipt(ch, "approved", approval=rec)
        return rec

    def _watchdog(self, t: int, s: int) -> None:
        """A watchdog wake-up raises an alarm and is noted on the change that caused it."""
        site = cell_id(self.w.sectors[s], "").rstrip("/")
        low = self.sim.low_u[t, s] * self.wc.peak_margin > self.wc.rho_max_low
        cell = cell_id(self.w.sectors[s], "low" if low else "mid")
        self.alarms.append({
            "t": t + 1, "cluster": self.cluster(s), "severity": "major", "source": "watchdog",
            "cell": cell,
            "text": f"Watchdog: {cell} congested while capacity radios slept; capacity radios "
                    f"of {site} woken and held awake for {self.wc.hold} quarter-hours"})
        for ch in self.changes.values():
            if ch.status != "applied":
                continue
            if any(self.cells[a["cell"]][0] == s and a["action"] == "sleep"
                   and a["from_t"] <= t + 1 < a["until_t"] for a in ch.actions):
                ch.watchdog_overrides += 1
                self._receipt(ch, "watchdog_override",
                              reasons=[f"watchdog woke {site} at {self.time(t + 1)} after "
                                       "congestion"])

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
        """Columnar: the quarter-hour start times once, then per cell one list per field."""
        self._sync()
        window = int(np.clip(window, 1, 96))
        t1 = max(0, self.now - self.faults.kpi_lag)      # values up to now - 1 (minus lag)
        t0 = max(0, t1 - window)
        out: dict[str, dict] = {}
        sim, drop = self.sim, self._dropout
        for c, s, layer in self.resolve(cells):
            carriers = [x for x in LAYERS[layer] if self.w.present[x][s]]
            cap = sum(EFFICIENCY[x] * BANDWIDTH[x] for x in carriers)
            src = {"low": sim.low_mb, "mid": sim.mid_mb, "nr3500": sim.nr_mb}[layer]
            ts = range(t0, t1)
            mb = [float(src[t, s]) for t in ts]
            actual = [self.actual(t, s, layer) for t in ts]
            gone = [bool(drop is not None and drop[t, s]) for t in ts]
            row = {"load_pct": [None if g else (round(v / cap, 2) if cap else 0.0)
                                for v, g in zip(mb, gone, strict=True)],
                   "dl_mb": [None if g else round(v, 1) for v, g in zip(mb, gone, strict=True)],
                   "state": [None if g else a for a, g in zip(actual, gone, strict=True)]}
            sched = [self.state(t, s, layer) for t in ts]
            if sched != actual:
                row["scheduled"] = sched
            out[c] = row
        note = ("15-min averages per quarter-hour starting at each time, as carried: traffic "
                "moved off a sleeping layer shows on the layer that took it; state is what "
                "the radio did")
        if self.faults.kpi_lag:
            note += f"; the KPI feed lags {self.faults.kpi_lag} quarter-hours behind the clock"
        if drop is not None:
            note += "; null = no measurement (unknown, not zero)"
        return {"now": self.time(self.now), "data_until": self.time(t1 - 1) if t1 else None,
                "times": [self.time(t) for t in range(t0, t1)], "note": note, "cells": out}

    def actual(self, t: int, s: int, layer: str) -> str:
        """State the radio really had at ``t`` (stepped world, ``t`` < now)."""
        if layer == "low":
            return "awake"
        arr = self.sim.mid_s if layer == "mid" else self.sim.nr_s
        return "asleep" if arr[t, s] == ASLEEP else "awake"

    def get_energy_report(self, cluster: str, window: int) -> dict:
        """Measured outcome over the last ``window`` quarter-hours vs always-on."""
        self._sync()
        t1 = self.now
        t0 = max(0, t1 - int(np.clip(window, 1, 96 * 7)))
        sectors = sorted({self.cells[c][0] for c in self.cells_in(cluster)})

        def kwh(st: Stepper) -> float:
            return float(sum(st.e[k][t0:t1][:, sectors].sum() for k in st.e) / 1e3)

        used, ref = kwh(self.sim), kwh(self.base)
        return {"cluster": cluster, "from": self.time(t0),
                "until": self.time(t1 - 1) if t1 else None,
                "kwh_used": round(used, 2), "kwh_always_on": round(ref, 2),
                "kwh_saved": round(ref - used, 2),
                "saved_pct": round(100 * (1 - used / ref), 2) if ref else 0.0,
                "congested_sector_qh": int(self.sim.cong[t0:t1][:, sectors].sum()),
                "watchdog_wakes": int(self.sim.woken[t0:t1][:, sectors].sum()),
                "unserved_mb": round(float(self.sim.unserved[t0:t1][:, sectors].sum()), 1),
                "scope": "all radios of the cluster's sectors, as measured in the world (not "
                         "the planner's twin); always-on = same traffic, nothing asleep"}

    def get_alarms(self, cluster: str, window: int) -> dict:
        self._sync()
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
        """Columnar: target times once, then per cell P10/P50/P90 MB and P90 load lists."""
        k = self.latest_issue()
        issue = int(self.f["mid"]["issues"][k]) - self.issue_offset
        lag = self.now - issue                         # quarter-hours since issue
        horizon = int(np.clip(horizon, 1, HORIZON - lag))
        hs = range(lag, lag + horizon)
        out: dict[str, dict] = {}
        for c, s, layer in self.resolve(cells):
            tgt = FORECAST_TARGET[layer]
            carriers = [x for x in LAYERS[layer] if self.w.present[x][s]]
            cap = sum(EFFICIENCY[x] * BANDWIDTH[x] for x in carriers)
            q = {f"p{int(qq * 100)}_mb": [round(float(self.f[tgt][qq][k][h, s]), 1) for h in hs]
                 for qq in (0.1, 0.5, 0.9)}
            q["p90_load_pct"] = [round(v / cap, 2) if cap else 0.0 for v in q["p90_mb"]]
            out[c] = q
        return {"issued_at": self.time(issue), "model": "LightGBM quantile, rolling Mondrian "
                "calibration (D30)", "times": [self.time(issue + h) for h in hs], "cells": out}

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
                for a, b in _dwell_ok(_runs(asleep), self.arbiter.min_dwell,
                                      self.arbiter.max_toggles_per_day // 2,
                                      continues=bool(self.timeline(c)[self.now - 1] == ASLEEP)
                                      if self.now > 0 else False):
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

    def simulate_plan(self, agent: AgentIdentity, actions: list[dict]) -> dict:
        """Dry run in the twin (D5): would the arbiter accept these actions now, and what do
        they do to expected energy and P90 risk? Nothing is registered or changed."""
        clean = self._clean(actions)
        verdict = self.arbiter.check(self, agent, clean)
        tier = self._tier(agent.agent_id, clean)
        k, lag, horizon = self._horizon_window(HORIZON)
        sectors = sorted({self.cells[a["cell"]][0] for a in clean})
        cost = self.costs(k)[lag:lag + horizon][:, sectors]                # [h, s, 4]
        span = slice(self.now, self.now + horizon)
        mid = self.mid_state[span][:, sectors].copy()
        nr = self.nr_state[span][:, sectors].copy()
        before = 2 * mid.astype(int) + nr.astype(int)
        col = {s: j for j, s in enumerate(sectors)}
        for a in clean:
            s, layer = self.cells[a["cell"]]
            if layer == "low":
                continue
            arr = mid if layer == "mid" else nr
            lo, hi = a["from_t"] - self.now, min(a["until_t"] - self.now, horizon)
            arr[max(lo, 0):max(hi, 0), col[s]] = ASLEEP if a["action"] == "sleep" else AWAKE
        after = 2 * mid.astype(int) + nr.astype(int)

        def wh(state: np.ndarray) -> tuple[float, int]:
            c = np.take_along_axis(cost, state[..., None], axis=2)[..., 0]
            bad = np.isinf(c)
            return float(np.where(bad, cost[..., 0], c).sum()), int(bad.sum())

        (wh0, _), (wh1, risky) = wh(before), wh(after)
        wh_on = float(cost[..., 0].sum())
        beyond = [a["cell"] for a in clean if a["until_t"] - self.now > horizon]
        return {"would_apply": verdict.ok and tier <= self.arbiter.auto_tier,
                "arbiter_ok": verdict.ok, "reasons": verdict.reasons, "approval_tier": tier,
                "needs_human_approval": tier > self.arbiter.auto_tier,
                "expected_kwh_saved_vs_now": round((wh0 - wh1) / 1000, 3),
                "expected_kwh_saved_vs_always_on": round((wh_on - wh1) / 1000, 3),
                "note": "vs_now compares with what is already scheduled (0 if these actions "
                        "are already applied); vs_always_on is these sectors' total saving",
                "p90_overload_sector_qh": risky,
                "beyond_forecast": beyond,
                "scope": f"twin over the next {horizon} quarter-hours (forecast horizon): "
                         "P50 energy, P90 risk; nothing was changed"}

    # ------------------------------------------------------------------ act tools
    def _tier(self, agent_id: str, actions: list[dict], exclude: str | None = None) -> int:
        """I8 tier of a change, counting every cell the same agent changed (applied,
        unknown or waiting) in the last ``arbiter.tier_window`` quarter-hours: splitting a
        big change into small ones does not get it under the approval threshold (salami)."""
        cells = {a["cell"] for a in actions}
        lo = self.now - self.arbiter.tier_window
        for ch in self.changes.values():
            if ch.agent != agent_id or ch.change_id == exclude or ch.change_id in self.approvals:
                continue
            if ch.status in ("applied", "unknown") and (ch.applied_at or 0) >= lo:
                cells |= {a["cell"] for a in ch.actions}
        return self.arbiter.approval_tier(len(cells))

    def _clean(self, actions: list[dict]) -> list[dict]:
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
        return clean

    def propose_change(self, agent: AgentIdentity, actions: list[dict], rationale: str) -> dict:
        clean = self._clean(actions)
        body = {"agent": agent.agent_id, "actions": clean, "rationale": rationale,
                "proposed_at": self.now}
        cid = "chg-" + hashlib.sha256(rfc8785.dumps(body)).hexdigest()[:12]
        if cid not in self.changes:
            self.changes[cid] = Change(cid, agent.agent_id, clean, rationale,
                                       self.time(self.now), role=agent.role)
        tier = self._tier(agent.agent_id, clean)
        return {"change_id": cid, "status": self.changes[cid].status,
                "approval_tier": tier, "actions": [self._show(a) for a in clean]}

    def apply_change(self, agent: AgentIdentity, change_id: str) -> dict:
        ch = self._get(change_id)
        if ch.agent != agent.agent_id:
            return self._refuse(ch, ["I5 scope: change was proposed by another agent"],
                                keep_status=True)
        if ch.status == "unknown":
            return {"change_id": change_id, "status": "unknown",
                    "reasons": ["outcome unknown: applying again could act twice. Check "
                                "get_change_status or the KPIs, or roll back"]}
        if ch.status not in ("proposed", "awaiting_approval"):
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
        # I8: above the auto tier, a recorded human approval of exactly these actions
        tier = self._tier(ch.agent, ch.actions, exclude=ch.change_id)
        if tier > self.arbiter.auto_tier and change_id not in self.approvals:
            who = self.approver(ch, tier) if self.approver else None
            if who is None:
                ch.status = "awaiting_approval"
                ch.reasons = [f"I8 approval: a tier {tier} change ({len(ch.actions)} actions) "
                              "needs a recorded human approval; it waits, unchanged, until an "
                              "operator approves it. Smaller changes need none"]
                return {"change_id": change_id, "status": ch.status, "reasons": ch.reasons,
                        "receipt": self._receipt(ch, "awaiting_approval", reasons=ch.reasons)}
            self.approve(change_id, who, note="simulated operator policy")
        ch.previous = {"mid": self.mid_state.copy(), "nr": self.nr_state.copy()}
        ch.applied_at = self.now
        f = self.faults
        if f.ack_loss and self._rng.random() < f.ack_loss:
            # the command went out but no acknowledgement came back (I33)
            ch.carried_out = bool(self._rng.random() < f.ack_applied)
            if ch.carried_out:
                self._write(ch)
            ch.status = "unknown"
            ch.reasons = ["no acknowledgement from the radios within 30 s; the change may or "
                          "may not have been carried out. Do not apply it again: check "
                          "get_change_status or the cells' KPIs"]
            return {"change_id": change_id, "status": "unknown", "reasons": ch.reasons,
                    "receipt": self._receipt(ch, "unknown", reasons=ch.reasons)}
        self._write(ch)
        ch.status = "applied"
        return {"change_id": change_id, "status": "applied",
                "receipt": self._receipt(ch, "applied")}

    def _write(self, ch: Change) -> None:
        for a in ch.actions:
            s, layer = self.cells[a["cell"]]
            arr = self.mid_state if layer == "mid" else self.nr_state
            arr[a["from_t"]:a["until_t"], s] = ASLEEP if a["action"] == "sleep" else AWAKE
            if a["action"] == "wake" and ch.role == "coverage":
                # I9: a coverage wake is a hold; it overrides energy sleeps on the sector
                self.holds.append({"sector": s, "from_t": a["from_t"], "until_t": a["until_t"],
                                   "agent": ch.agent, "change_id": ch.change_id})
                other = self.mid_state if layer == "nr3500" else self.nr_state
                other[a["from_t"]:a["until_t"], s] = AWAKE
                for o in self.changes.values():
                    if o is ch or o.status != "applied":
                        continue
                    if any(self.cells[b["cell"]][0] == s and b["action"] == "sleep"
                           and b["from_t"] < a["until_t"] and a["from_t"] < b["until_t"]
                           for b in o.actions):
                        self._receipt(o, "overridden", reasons=[
                            f"I9 conflict: coverage change {ch.change_id} ({ch.agent}) holds "
                            f"{cell_id(self.w.sectors[s], '').rstrip('/')} awake"])

    def get_change_status(self, change_id: str) -> dict:
        ch = self._get(change_id)
        self._sync()
        if (ch.status == "unknown" and ch.carried_out is not None
                and self.now - (ch.applied_at or 0) >= self.faults.resolve_after):
            # enough time has passed to see what the radios did
            if ch.carried_out:
                ch.status, ch.reasons = "applied", ["confirmed from observed radio states "
                                                    "after a lost acknowledgement"]
            else:
                ch.status, ch.reasons = "failed", ["not carried out: the radios never took "
                                                   "the commanded states"]
            self._receipt(ch, ch.status, reasons=ch.reasons)
        out = {"change_id": change_id, "status": ch.status, "reasons": ch.reasons,
               "actions": [self._show(a) for a in ch.actions], "receipts": ch.receipts}
        if ch.status == "applied":
            out["observed"] = self._observed(ch)
        if ch.watchdog_overrides:
            out["watchdog_overrides"] = ch.watchdog_overrides
        return out

    def _observed(self, ch: Change) -> list[dict]:
        """Per action, over the quarter-hours already past: did the radio do it?"""
        out = []
        for a in ch.actions:
            s, layer = self.cells[a["cell"]]
            lo, hi = a["from_t"], min(a["until_t"], self.now)
            want = "asleep" if a["action"] == "sleep" else "awake"
            ok = sum(self.actual(t, s, layer) == want for t in range(lo, hi))
            out.append({"cell": a["cell"], "elapsed_qh": max(0, hi - lo), "complied_qh": ok})
        return out

    def rollback(self, agent: AgentIdentity, change_id: str) -> dict:
        ch = self._get(change_id)
        if ch.status not in ("applied", "unknown") or ch.previous is None:
            return {"change_id": change_id, "status": ch.status,
                    "reasons": ["only applied changes can be rolled back"]}
        # restore only the future, and only this change's cells: the past already happened,
        # and later changes on other cells stay (a whole-schedule restore would undo them)
        for a in ch.actions:
            s, layer = self.cells[a["cell"]]
            lo, hi = max(a["from_t"], self.now), a["until_t"]
            if hi <= lo or layer == "low":
                continue
            layers = ("mid", "nr") if ch.role == "coverage" else (
                ("mid",) if layer == "mid" else ("nr",))
            for key in layers:
                arr = self.mid_state if key == "mid" else self.nr_state
                arr[lo:hi, s] = ch.previous[key][lo:hi, s]
        ch.status = "rolled_back"
        self.holds = [h for h in self.holds if h["change_id"] != ch.change_id]
        return {"change_id": change_id, "status": "rolled_back",
                "receipt": self._receipt(ch, "rolled_back", by=agent.agent_id)}

    def advance(self, quarter_hours: int = 1) -> None:
        """Move the clock (harness only; agents cannot move time)."""
        self.now = min(self.w.T - 1, self.now + quarter_hours)
        self._sync()

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
        """I7: JCS-canonical receipt body, its sha256, and a DSSE envelope over the body
        signed with the network's key (verify with `verify_receipt` and `receipt_jwks`)."""
        body = {"change_id": ch.change_id, "agent": ch.agent, "outcome": outcome,
                "actions": [self._show(a) for a in ch.actions], "at": self.time(self.now),
                "recorded": datetime.now(UTC).isoformat(timespec="seconds"), **extra}
        raw = rfc8785.dumps(body)
        rec = {**body, "sha256": hashlib.sha256(raw).hexdigest(),
               "signature": sign_envelope(raw, RECEIPT_TYPE, self.receipt_key)}
        ch.receipts.append(rec)
        return rec


def planner_operator(net: Network, name: str = "simulated operator (approves the "
                     "risk-checked plan)") -> Callable[[Change, int], str | None]:
    """A *simulated* human for I8: approves a change only if every sleep in it is inside the
    planner's current risk-checked plan for that cluster (recomputed when asked). Used for
    evaluation arms and NetCrash; labelled as simulated in every approval record."""
    def approve(ch: Change, tier: int) -> str | None:
        clusters = {net.cluster(net.cells[a["cell"]][0]) for a in ch.actions}
        allowed = set()
        for cl in clusters:
            for a in net.optimise_plan(cl, HORIZON)["actions"]:
                t0 = net.now + a["from_qh"]
                allowed |= {(a["cell"], t) for t in range(t0, t0 + a["quarter_hours"])}
        ok = all((a["cell"], t) in allowed for a in ch.actions if a["action"] == "sleep"
                 for t in range(a["from_t"], a["until_t"]))
        return name if ok else None
    return approve


RECEIPT_TYPE = "application/vnd.yovahti.receipt+json"


def verify_receipt(rec: dict, jwks: dict) -> dict:
    """Check a receipt's DSSE signature and that the signed body is the receipt shown."""
    env = rec.get("signature")
    if not env:
        return {"ok": False, "reason": "unsigned receipt"}
    v = verify_envelope(env, jwks, RECEIPT_TYPE)
    if not v["ok"]:
        return v
    body = {k: x for k, x in rec.items() if k not in ("sha256", "signature")}
    if v["payload"] != rfc8785.dumps(body):
        return {"ok": False, "reason": "signed body differs from the receipt shown"}
    if hashlib.sha256(v["payload"]).hexdigest() != rec.get("sha256"):
        return {"ok": False, "reason": "sha256 does not match the signed body"}
    return {"ok": True, "receipt": json.loads(v["payload"]), "keyid": v["keyid"]}


def _dwell_ok(runs: list[tuple[int, int]], dwell: int, max_runs: int,
              continues: bool = False) -> list[tuple[int, int]]:
    """Keep only sleep windows the arbiter's I4 accepts: at least ``dwell`` quarter-hours long
    (a run starting at 0 that continues a current sleep counts its past), at least ``dwell``
    awake between windows (the later one is dropped: fewer sleeps is always safe), and at
    most ``max_runs`` windows (the longest kept)."""
    out: list[tuple[int, int]] = []
    for a, b in runs:
        if b - a < dwell and not (a == 0 and continues):
            continue
        if out and a - out[-1][1] < dwell:
            continue
        out.append((a, b))
    if len(out) > max_runs:
        keep = sorted(sorted(out, key=lambda r: r[0] - r[1])[:max_runs])
        out = keep
    return out


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

