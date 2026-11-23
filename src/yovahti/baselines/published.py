"""Baselines built from published methods, labelled as such.

B2 · Reconstruction of Ericsson's published method (patent WO2024028883A1, "AI based dynamic
cell sleep mode threshold configuration", and Ericsson's 2023 blog). **Not Ericsson's software.**
The base station runs cell sleep mode (CSM): the capacity cell sleeps while its load is below a
sleep threshold and wakes when the coverage cell's load exceeds a wake threshold. The method
chooses the sleep threshold dynamically: from forecast load it estimates the energy with and
without sleep for each candidate threshold, picks the threshold with the largest forecast
energy gain, and invalidates thresholds whose forecast energy with sleep is not lower than
without (the patent's validity check). Here thresholds are re-chosen every hour per sector
from the same forecasts Yövahti uses, so the comparison is about the method, not the data.

B3 · O-RAN SC energy-saving demo rApp (nonrtric-plt-rappmanager, es-demo-rapp): lock the cell
when **all** predicted loads are below 0.04 (read here as 4 % utilisation over the next three
quarter-hours), unlock otherwise. No coverage check, risk margin or neighbour coordination.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from yovahti.energy import tr38864
from yovahti.world.data import BANDWIDTH, EFFICIENCY, LOW, WorldData
from yovahti.world.sim import ASLEEP, AWAKE, Observation, WorldConfig


class _ForecastAccess:
    def __init__(self, world: WorldData, forecasts: dict, issue_offset: int):
        self.w, self.f = world, forecasts
        self.issues = np.asarray(forecasts["mid"]["issues"]) - issue_offset
        self.cap_low = sum(world.present[c] * EFFICIENCY[c] * BANDWIDTH[c] for c in LOW)
        self.cap_mid = sum(world.present[c] * EFFICIENCY[c] * BANDWIDTH[c]
                           for c in ("LTE_1800", "NR_2100"))
        self.cap_nr = world.present["NR_3500"] * EFFICIENCY["NR_3500"] * BANDWIDTH["NR_3500"]

    def latest(self, t: int) -> tuple[int, int] | None:
        """(issue index k, offset of t within that issue's horizon) for the newest issue <= t."""
        k = int(np.searchsorted(self.issues, t, side="right")) - 1
        if k < 0 or t - self.issues[k] >= self.f["mid"][0.5].shape[1]:
            return None
        return k, int(t - self.issues[k])

    @staticmethod
    def util(mb, cap):
        return np.divide(mb, cap, out=np.zeros_like(mb, dtype=float), where=cap > 0)


@dataclass
class PublishedThresholdMethod(_ForecastAccess):
    """B2 (reconstruction)."""
    world: WorldData
    forecasts: dict
    issue_offset: int
    world_cfg: WorldConfig = field(default_factory=WorldConfig)
    grid: tuple[float, ...] = (0, 2, 4, 6, 8, 10, 15, 20)  # candidate sleep thresholds, %
    wake_low_above: float = 30.0       # coverage-cell wake threshold (fixed, as in CSM)
    nr_grid: tuple[float, ...] = (0, 2, 4, 6, 8, 10, 15, 20)
    wake_mid_above: float = 50.0

    def __post_init__(self):
        _ForecastAccess.__init__(self, self.world, self.forecasts, self.issue_offset)
        cat = self.world_cfg.category
        self.r_mid = (tr38864.power("deep_sleep", cat, 2) / tr38864.power("micro_sleep", cat, 2))
        self.r_nr = (tr38864.power("deep_sleep", cat, 1) / tr38864.power("micro_sleep", cat, 1))
        self.theta_mid = np.zeros(self.w.S)
        self.theta_nr = np.zeros(self.w.S)
        self.k_seen = -1

    def _choose(self, k: int) -> None:
        w = self.w
        mid = self.f["mid"][0.5][k].astype(float)
        nr = self.f["nr"][0.5][k].astype(float)
        low = self.f["low"][0.5][k].astype(float)
        u_mid, u_nr = self.util(mid, self.cap_mid), self.util(nr, self.cap_nr)
        low_after = self.util(low + mid, self.cap_low)
        mid_after = self.util(mid + nr, self.cap_mid)
        k_low = sum(w.slopes["low"][c] * w.present[c] for c in LOW) / np.where(
            self.cap_low > 0, self.cap_low, np.inf)
        # forecast energy gain per sleeping quarter-hour (idle saved minus cost on coverage)
        gain_mid = w.idle["mid"] * (1 - self.r_mid) - k_low * mid
        gain_nr = (w.idle["nr3500"] * (1 - self.r_nr)) * w.present["NR_3500"]
        best_m, best_n = np.zeros(w.S), np.full(w.S, -np.inf)
        best_mv = np.zeros(w.S)
        for th in self.grid:
            asleep = (u_mid < th) & (low_after <= self.wake_low_above)  # CSM would stay asleep
            g = (gain_mid * asleep).sum(axis=0)
            better = g > np.maximum(best_n, 0)                        # validity: gain > 0
            best_mv = np.where(better, th, best_mv)
            best_n = np.where(better, g, best_n)
        self.theta_mid = best_mv
        best_n2, best_nv = np.full(w.S, -np.inf), np.zeros(w.S)
        for th in self.nr_grid:
            asleep = (u_nr < th) & (mid_after <= self.wake_mid_above)
            g = (gain_nr * asleep).sum(axis=0)
            better = g > np.maximum(best_n2, 0)
            best_nv = np.where(better, th, best_nv)
            best_n2 = np.where(better, g, best_n2)
        self.theta_nr = best_nv
        del best_m

    def __call__(self, obs: Observation) -> tuple[np.ndarray, np.ndarray]:
        loc = self.latest(obs.t)
        if loc is not None and loc[0] != self.k_seen:
            self.k_seen = loc[0]
            self._choose(loc[0])
        if obs.t == 0:
            z = np.zeros_like(obs.mid_state)
            return z, z
        ms, ns = obs.mid_state.copy(), obs.nr_state.copy()
        # base-station CSM with the chosen thresholds (reacts to the last quarter-hour)
        ms = np.where((ms == AWAKE) & (obs.mid_util < self.theta_mid), ASLEEP, ms)
        ms = np.where((ms == ASLEEP) & (obs.low_util > self.wake_low_above), AWAKE, ms)
        ns = np.where((ns == AWAKE) & (obs.util["NR_3500"] < self.theta_nr), ASLEEP, ns)
        ns = np.where((ns == ASLEEP) & ((obs.mid_util > self.wake_mid_above)
                                        | (obs.low_util > self.wake_low_above)), AWAKE, ns)
        return ms.astype(np.int8), ns.astype(np.int8)


@dataclass
class OranScDemoRapp(_ForecastAccess):
    """B3."""
    world: WorldData
    forecasts: dict
    issue_offset: int
    threshold_pct: float = 4.0
    lookahead: int = 3

    def __post_init__(self):
        _ForecastAccess.__init__(self, self.world, self.forecasts, self.issue_offset)

    def __call__(self, obs: Observation) -> tuple[np.ndarray, np.ndarray]:
        loc = self.latest(obs.t)
        if loc is None:
            z = np.zeros_like(obs.mid_state)
            return z, z
        k, off = loc
        sl = slice(off, off + self.lookahead)
        u_mid = self.util(self.f["mid"][0.5][k][sl].astype(float), self.cap_mid)
        u_nr = self.util(self.f["nr"][0.5][k][sl].astype(float), self.cap_nr)
        ms = np.where((u_mid < self.threshold_pct).all(axis=0), ASLEEP, AWAKE)
        ns = np.where((u_nr < self.threshold_pct).all(axis=0), ASLEEP, AWAKE)
        return ms.astype(np.int8), ns.astype(np.int8)
