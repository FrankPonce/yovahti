"""Conformal congestion bound (stretch, Research posting): the planning margin as a dial with a
stated guarantee.

The Z3 proof (`arbiter.proofs`) shows the world can flag congestion on a sleeping sector only
if the traffic that lands on the receiving layer exceeds the P90-based amount the arbiter
checked. So bound that miss: for every (issue, horizon, sector) where a sleep is *allowed* at
the planner's check, take the score

    r = max over sleep states of  actual receiving traffic / P90 receiving traffic

(low + mid for "mid asleep", low + mid + NR for "both asleep", mid + NR for "NR asleep").
Split conformal: on a calibration set, the margin m_alpha is the ceil((n+1)(1-alpha))-th
smallest score. Planning with ``PlannerConfig(margin=m_alpha)`` then gives, for exchangeable
sector-quarter-hours,

    P(congestion | the planner let it sleep) <= P(r > m_alpha) <= alpha  (+ 1/(n+1)),

hence expected congested quarter-hours per sector-day <= alpha x slept quarter-hours per
sector-day. Selection uses forecasts only (never the actuals), so it does not break the
exchangeability the guarantee needs. Mondrian groups (night / day) keep it from hiding a bad
night behind good days. Marginal, not per-sector: a statement about the fleet, said as such.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from yovahti.forecast.quantile import TARGETS
from yovahti.world.data import BANDWIDTH, EFFICIENCY, LOW, WorldData
from yovahti.world.sim import WorldConfig


@dataclass
class Scores:
    t: np.ndarray          # world quarter-hour of each point
    s: np.ndarray          # sector
    r: np.ndarray          # nonconformity score (actual / P90 receiving traffic)
    night: np.ndarray      # Mondrian group: local 22:00-06:00


def scores(world: WorldData, fc: dict, issue_offset: int, cfg: WorldConfig | None = None,
           lead: int = 8) -> Scores:
    """Scores for points the planner may sleep, ``lead`` quarter-hours after each issue (the
    plan a re-planning controller actually executes)."""
    cfg = cfg or WorldConfig()
    cap_low = sum(world.present[c] * EFFICIENCY[c] * BANDWIDTH[c] for c in LOW)
    cap_mid = sum(world.present[c] * EFFICIENCY[c] * BANDWIDTH[c] for c in ("LTE_1800",
                                                                         "NR_2100"))
    has_nr = world.present["NR_3500"]
    actual = {k: sum(world.vol[c] for c in TARGETS[k]) for k in TARGETS}
    ts, ss, rs = [], [], []
    for k, issue in enumerate(np.asarray(fc["mid"]["issues"]) - issue_offset):
        for h in range(lead):
            t = int(issue + h)
            if t < 0 or t >= world.T:
                continue
            p = {x: fc[x][0.9][k][h].astype(float) for x in ("low", "mid", "nr")}
            p["nr"] = np.where(has_nr, p["nr"], 0.0)
            a = {x: actual[x][t] for x in ("low", "mid", "nr")}
            ok2 = (p["low"] + p["mid"]) / np.where(cap_low > 0, cap_low, np.inf) \
                * cfg.peak_margin <= cfg.rho_max_low
            ok3 = (p["low"] + p["mid"] + p["nr"]) / np.where(cap_low > 0, cap_low, np.inf) \
                * cfg.peak_margin <= cfg.rho_max_low
            ok1 = has_nr & ((p["mid"] + p["nr"]) / np.where(cap_mid > 0, cap_mid, np.inf)
                            * cfg.peak_margin <= cfg.rho_max_mid)
            r = np.full(world.S, -np.inf)
            with np.errstate(divide="ignore", invalid="ignore"):
                r = np.where(ok2, np.maximum(r, (a["low"] + a["mid"]) / (p["low"] + p["mid"])),
                             r)
                r = np.where(ok3 & has_nr, np.maximum(
                    r, (a["low"] + a["mid"] + a["nr"]) / (p["low"] + p["mid"] + p["nr"])), r)
                r = np.where(ok1, np.maximum(r, (a["mid"] + a["nr"]) / (p["mid"] + p["nr"])), r)
            keep = np.isfinite(r)
            ts.append(np.full(keep.sum(), t))
            ss.append(np.where(keep)[0])
            rs.append(r[keep])
    t = np.concatenate(ts)
    hour = world.times[t].tz_convert("Europe/Bratislava").hour
    return Scores(t, np.concatenate(ss), np.concatenate(rs),
                  np.asarray((hour >= 22) | (hour < 6)))


def margin(r: np.ndarray, alpha: float) -> float:
    """Split-conformal quantile: the ceil((n+1)(1-alpha))-th smallest score."""
    n = len(r)
    k = int(np.ceil((n + 1) * (1 - alpha)))
    if k > n:
        return float("inf")
    return float(max(1.0, np.sort(r)[k - 1]))


def mondrian_margin(sc: Scores, mask: np.ndarray, alpha: float) -> dict[str, float]:
    return {g: margin(sc.r[mask & (sc.night == (g == "night"))], alpha)
            for g in ("night", "day")}
