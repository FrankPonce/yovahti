"""The deterministic gate between an admitted proposal and the network (ARCHITECTURE §12).

Implemented in this slice: I1 capacity, I2 protected cells, I3 blast radius, I5 scope.
Still to come (S8): I4 dwell/toggle limits, I7 signed receipts, I8 recorded human approval
above a tier, I9 coverage-over-energy conflicts. I6 admission is checked by the caller.

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

    def approval_tier(self, n_cells: int) -> int:
        return 1 if n_cells <= self.tiers[0] else 2 if n_cells <= self.tiers[1] else 3

    def check(self, net: Network, agent: AgentIdentity, actions: list[dict]) -> Verdict:
        reasons: list[str] = []
        # I5 scope and I2 protected
        for a in actions:
            s, layer = net.cells[a["cell"]]
            if layer == "low":
                reasons.append(f"I5 scope: {a['cell']} is a coverage cell and never sleeps")
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
        if reasons:
            return Verdict(False, reasons)
        return Verdict(not (r := self._capacity(net, actions)), r)

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
