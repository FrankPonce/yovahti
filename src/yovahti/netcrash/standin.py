"""Stand-in mode (NETCRASH.md): the production tools, on a small slice of the real network,
with scripted feeds and faults.

A stand-in is a `Network` over the first few sites of a real cluster (validation weeks, real
traffic and forecasts), so tool results stay small and cheap while the numbers stay real.
Faults change what a tool returns, never the tool's name or schema:

* ``kpis_fail``    get_cell_kpis fails for every cell
* ``apply_unknown`` apply_change times out: the change's outcome is ``unknown``
* ``plan_partial`` optimise_plan keeps answering "partial result, call again"
"""

from __future__ import annotations

import numpy as np

from yovahti.forecast.quantile import QUANTILES
from yovahti.mcp_server.network import Network
from yovahti.trust.admission import AgentIdentity
from yovahti.world.faults import Faults

FAULTS = {"kpis_fail", "apply_unknown", "plan_partial", "wide_uncertainty"}
WIDE = ("forecast uncertainty is HIGH tonight: the P10-P90 range is about 4x the median for "
        "these cells, and several sleep windows sit within 5 % of the P90 limit")


class StandIn(Network):
    """``faults`` are tool-level faults (names above); ``world_faults`` are control- and
    measurement-plane faults (`world.faults.Faults`) applied by the closed loop."""

    def __init__(self, *args, faults: tuple[str, ...] = (), kpi_extra: dict | None = None,
                 world_faults: Faults | None = None, tick_on_apply: int = 0, **kw):
        super().__init__(*args, faults=world_faults, **kw)
        unknown = set(faults) - FAULTS
        if unknown:
            raise ValueError(f"unknown faults {unknown}")
        self.tool_faults = set(faults)
        self.tick_on_apply = tick_on_apply
        self.kpi_extra = kpi_extra or {}
        self.calls: dict[str, int] = {}

    def _count(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    def get_cell_kpis(self, cells: list[str], window: int) -> dict:
        self._count("get_cell_kpis")
        if "kpis_fail" in self.tool_faults:
            raise RuntimeError("KPI collector unavailable: no measurements returned for any "
                               "cell (timeout after 30 s)")
        out = super().get_cell_kpis(cells, window)
        for v in out["cells"].values():
            v.update(self.kpi_extra)
        return out

    def optimise_plan(self, cluster: str, horizon: int) -> dict:
        self._count("optimise_plan")
        if "plan_partial" in self.tool_faults:
            return {"cluster": cluster, "status": "partial", "actions": [],
                    "note": "Planner still running: partial result, call optimise_plan again "
                            "to get the plan."}
        out = super().optimise_plan(cluster, horizon)
        if "wide_uncertainty" in self.tool_faults:
            out["uncertainty"] = WIDE
        return out

    def simulate_plan(self, agent: AgentIdentity, actions: list[dict]) -> dict:
        self._count("simulate_plan")
        out = super().simulate_plan(agent, actions)
        if "wide_uncertainty" in self.tool_faults:
            out["uncertainty"] = WIDE
        return out

    def apply_change(self, agent: AgentIdentity, change_id: str) -> dict:
        self._count("apply_change")
        ch = self._get(change_id)
        if "apply_unknown" in self.tool_faults and ch.status == "proposed":
            ch.status = "unknown"
            ch.reasons = ["actuation timed out after 30 s; the outcome is unknown"]
            return {"change_id": change_id, "status": "unknown", "reasons": ch.reasons,
                    "receipt": self._receipt(ch, "unknown", reasons=ch.reasons)}
        out = super().apply_change(agent, change_id)
        if self.tick_on_apply:
            self.advance(self.tick_on_apply)       # time passes while the radios switch
        return out


def standin(base: Network, cluster: str = "C01", n_sites: int = 3,
            **kw) -> StandIn:
    """A stand-in over the first ``n_sites`` sites of ``cluster`` of a real network."""
    sectors, sites = [], []
    for s in sorted({base.cells[c][0] for c in base.cells_in(cluster)}):
        site = base.w.sectors[s].split("/")[0]
        if site not in sites:
            if len(sites) == n_sites:
                continue
            sites.append(site)
        sectors.append(s)
    idx = np.array(sectors)
    fc = {t: {"issues": v["issues"], **{q: v[q][..., idx] for q in QUANTILES}}
          for t, v in base.f.items() if isinstance(v, dict)}
    return StandIn(base.w.subset(idx), fc, now=base.now, issue_offset=base.issue_offset,
                   world_cfg=base.wc, **kw)
