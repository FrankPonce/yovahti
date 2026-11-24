"""The deterministic gate between an admitted proposal and the network (ARCHITECTURE §12).

Checked here: I1 capacity, I2 protected cells, I3 blast radius, I4 dwell and toggle limits,
I5 scope, I9 conflicts (coverage holds and watchdog holds beat energy sleeps; no ping-pong).
The caller (`Network.apply_change`) checks I6 admission first, then this verdict, then I8
(changes above ``auto_tier`` wait for a recorded human approval), and writes I7 receipts
signed with the network's key, with a stored rollback for every applied change.

Wakes are never blocked by energy rules (I4 applies to sleeps): safety first.

Unknown is refused: a sleep that reaches past the newest forecast's horizon cannot be checked
against I1, so it is refused rather than assumed safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from yovahti.forecast.quantile import HORIZON
from yovahti.world.sim import ASLEEP, AWAKE

if TYPE_CHECKING:
    from yovahti.mcp_server.network import Network
    from yovahti.trust.admission import AgentIdentity


@dataclass
class Verdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class Arbiter:
    max_cluster_share: float = 0.5     # I3: share of a cluster's capacity cells per change
    tiers: tuple[int, int] = (5, 20)   # cells per change for approval tiers 1 / 2 / 3
    auto_tier: int = 1                 # I8: tiers above this need a recorded human approval
    tier_window: int = 8               # I8: quarter-hours of an agent's changes counted
    min_dwell: int = 4                 # I4: quarter-hours a cell stays asleep / awake
    max_toggles_per_day: int = 8       # I4: state switches per cell in any 24 h window

    def approval_tier(self, n_cells: int) -> int:
        return 1 if n_cells <= self.tiers[0] else 2 if n_cells <= self.tiers[1] else 3

    def check(self, net: Network, agent: AgentIdentity, actions: list[dict]) -> Verdict:
        reasons: list[str] = []
        # I5 scope and I2 protected
        for a in actions:
            s, layer = net.cells[a["cell"]]
            if layer == "low" and a["action"] == "sleep":
                reasons.append(f"I5 scope: {a['cell']} is a coverage cell and never sleeps")
            elif layer == "low":
                reasons.append(f"I5 scope: {a['cell']} is a coverage cell; it is always awake")
            if agent.scope_clusters is not None and net.cluster(s) not in agent.scope_clusters:
                reasons.append(f"I5 scope: {a['cell']} is outside the agent's clusters")
            if a["action"] == "sleep" and not agent.may_sleep:
                reasons.append("I5 scope: agent may not put cells to sleep")
            if a["action"] == "wake" and not agent.may_wake:
                reasons.append("I5 scope: agent may not wake cells")
            if a["action"] == "sleep" and a["cell"] in net.protected:
                reasons.append(f"I2 protected: {a['cell']} never sleeps")
        # I3 blast radius
        by_cluster: dict[str, set[str]] = {}
        for a in actions:
            by_cluster.setdefault(net.cluster(net.cells[a["cell"]][0]), set()).add(a["cell"])
        for cl, cells in by_cluster.items():
            total = sum(1 for c in net.cells_in(cl) if net.cells[c][1] != "low")
            limit = max(1, int(self.max_cluster_share * total))
            if len(cells) > limit:
                reasons.append(f"I3 blast radius: {len(cells)} capacity cells in {cl} in one "
                               f"change (limit {limit})")
        reasons += self._conflicts(net, agent, actions)
        reasons += self._dwell(net, actions)
        if reasons:
            return Verdict(False, reasons)
        return Verdict(not (r := self._capacity(net, actions)), r)

    # ------------------------------------------------------------------ I9 conflicts
    @staticmethod
    def _conflicts(net: Network, agent: AgentIdentity, actions: list[dict]) -> list[str]:
        out = []
        for a in actions:
            if a["action"] != "sleep":
                continue
            s, _ = net.cells[a["cell"]]
            for h in net.holds:
                if h["sector"] == s and h["from_t"] < a["until_t"] and a["from_t"] < h["until_t"]:
                    out.append(f"I9 conflict: {a['cell']} is held awake by coverage change "
                               f"{h['change_id']} ({h['agent']}) until {net.time(h['until_t'])}")
                    break
            if net.watchdog_hold(s) >= a["from_t"]:
                out.append(f"I9 conflict: the watchdog holds {a['cell']} awake until "
                           f"{net.time(net.watchdog_hold(s) + 1)} after congestion")
        return out

    # ------------------------------------------------------------------ I4 dwell / toggles
    def _dwell(self, net: Network, actions: list[dict]) -> list[str]:
        out = []
        for cell in dict.fromkeys(a["cell"] for a in actions):
            mine = [a for a in actions if a["cell"] == cell]
            if not any(a["action"] == "sleep" for a in mine):
                continue                            # wakes are never blocked by energy rules
            seq = net.timeline(cell)                # actual past + scheduled future, int8 [T]
            for a in mine:
                seq[a["from_t"]:a["until_t"]] = ASLEEP if a["action"] == "sleep" else AWAKE
            for a in mine:
                if a["action"] != "sleep":
                    continue
                f, u = a["from_t"], min(a["until_t"], len(seq))
                run_lo, run_hi = f, u               # the whole sleep run this action joins
                while run_lo > 0 and seq[run_lo - 1] == ASLEEP:
                    run_lo -= 1
                while run_hi < len(seq) and seq[run_hi] == ASLEEP:
                    run_hi += 1
                if run_hi - run_lo < self.min_dwell and run_hi < len(seq):
                    out.append(f"I4 dwell: {cell} would sleep only {run_hi - run_lo} "
                               f"quarter-hours (minimum {self.min_dwell})")
                for gap, where in ((_awake_gap_before(seq, run_lo), "before"),
                                   (_awake_gap_after(seq, run_hi), "after")):
                    if gap is not None and 0 < gap < self.min_dwell:
                        out.append(f"I4 dwell: {cell} would be awake only {gap} quarter-hours "
                                   f"{where} this sleep (ping-pong; minimum {self.min_dwell})")
            lo = max(0, min(a["from_t"] for a in mine) - 96)
            hi = min(len(seq), max(a["until_t"] for a in mine) + 96)
            switches = (np.diff(seq[lo:hi]) != 0).astype(int)
            most = int(np.convolve(switches, np.ones(96, dtype=int), mode="valid").max()
                       if len(switches) >= 96 else switches.sum())
            if most > self.max_toggles_per_day:
                out.append(f"I4 toggles: {cell} would switch {most} times in 24 h "
                           f"(maximum {self.max_toggles_per_day})")
        return out

    @staticmethod
    def _capacity(net: Network, actions: list[dict]) -> list[str]:
        """I1: with the change applied, every sleeping state stays feasible at P90."""
        sleeps = [a for a in actions if a["action"] == "sleep"]
        if not sleeps:
            return []
        k = net.latest_issue()
        issue = int(net.f["mid"]["issues"][k]) - net.issue_offset
        t0 = min(a["from_t"] for a in sleeps)
        t1 = max(a["until_t"] for a in sleeps)
        if t1 - issue > HORIZON:
            return [f"I1 capacity: sleep until {net.time(t1)} reaches past the forecast "
                    f"horizon ({net.time(issue + HORIZON)}); cannot verify, refused"]
        sectors = sorted({net.cells[a["cell"]][0] for a in sleeps})
        mid = net.mid_state[t0:t1][:, sectors].copy()
        nr = net.nr_state[t0:t1][:, sectors].copy()
        col = {s: j for j, s in enumerate(sectors)}
        for a in actions:
            s, layer = net.cells[a["cell"]]
            if s not in col:
                continue
            arr = mid if layer == "mid" else nr
            lo, hi = max(a["from_t"], t0) - t0, min(a["until_t"], t1) - t0
            arr[lo:hi, col[s]] = ASLEEP if a["action"] == "sleep" else AWAKE
        state = 2 * mid.astype(int) + nr.astype(int)                 # [t, s] planner index
        cost = net.costs(k)[t0 - issue:t1 - issue][:, sectors]      # [t, s, 4]
        bad = np.isinf(np.take_along_axis(cost, state[..., None], axis=2)[..., 0]) & (state > 0)
        from yovahti.mcp_server.network import cell_id

        out = []
        for j in np.where(bad.any(axis=0))[0]:
            first = int(np.argmax(bad[:, j]))
            sec = cell_id(net.w.sectors[sectors[j]], "").rstrip("/")
            out.append(f"I1 capacity: sector {sec} would overload the "
                       f"receiving layer at P90 from {net.time(t0 + first)} "
                       f"({int(bad[:, j].sum())} of {bad.shape[0]} quarter-hours)")
        return out


def _awake_gap_before(seq: np.ndarray, i: int) -> int | None:
    """Awake quarter-hours between an earlier sleep and index ``i`` (None if no earlier sleep)."""
    k = i - 1
    while k >= 0 and seq[k] == AWAKE:
        k -= 1
    return None if k < 0 else i - 1 - k


def _awake_gap_after(seq: np.ndarray, i: int) -> int | None:
    """Awake quarter-hours from ``i`` to the next sleep (None if no later sleep)."""
    k = i
    while k < len(seq) and seq[k] == AWAKE:
        k += 1
    return None if k >= len(seq) else k - i
