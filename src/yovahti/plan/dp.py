"""Risk-, price- and switch-aware sleep planner (B4): exact dynamic programming per sector.

Every hour, for each sector, choose a state for each of the next 40 quarter-hours from
{both awake, NR 3500 asleep, mid asleep, both asleep}, minimising

    sum_t  weight_t * expected_energy(state_t)  +  switch_cost * [state_t != state_{t-1}]

subject to: the layer that receives moved traffic stays under its limit at the **risk
quantile** of the forecast (P90 by default, D16). Infeasible states get infinite cost.

Within a sector this is a shortest path over 4 states x 40 steps, solved exactly and
vectorised over all sectors at once (D27). Constraints that span sectors (blast radius) are
left to the arbiter.

The planner's energy model is the twin's (the fitted model with averaged per-MB slopes), so it
is deliberately not identical to the world (D5).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from yovahti.energy import tr38864
from yovahti.forecast.quantile import HORIZON
from yovahti.world.data import BANDWIDTH, EFFICIENCY, LOW, WorldData
from yovahti.world.sim import ASLEEP, AWAKE, Observation, WorldConfig

# state index -> (mid, nr)
STATES = np.array([[AWAKE, AWAKE], [AWAKE, ASLEEP], [ASLEEP, AWAKE], [ASLEEP, ASLEEP]])


@dataclass
class PlannerConfig:
    risk_q: float = 0.9          # forecast quantile that must respect the limits
    weight: str = "energy"       # "energy" | "price" | "co2"
    switch_cost_wh: float = 8.0  # discourages flapping (hardware wear, signalling)
    replan_every: int = 4        # quarter-hours between plans (hourly)
    margin: float = 1.0          # extra multiplier on the risk quantile
    # adaptive per-sector margin (E42, Samsung US20240422667A1's idea): a sector the watchdog
    # had to wake gets its margin multiplied by adaptive_step (capped), decaying daily to 1.0.
    # 1.0 = off, the published method (D36).
    adaptive_step: float = 1.0
    adaptive_cap: float = 2.0
    adaptive_decay: float = 0.97
    # per-user throughput floor (E44; Ericsson's 2023 blog and Reiss et al. constrain a KPI
    # directly): a sleep state is feasible only if the layer receiving the users would still
    # give each active user at least this many Mbit/s (users forecast = same quarter-hour a
    # week earlier). 0 = off, the published method (D36).
    min_user_mbps: float = 0.0


class DPPlanner:
    """Policy for the world: re-plans hourly from forecasts issued at that time."""

    def __init__(self, world: WorldData, forecasts: dict[str, dict], cfg: PlannerConfig,
                 world_cfg: WorldConfig, issue_offset: int = 0, users: dict | None = None,
                 user_offset: int = 0):
        """``forecasts[target]`` = {"issues": [n], 0.1/0.5/0.9: [n, H, S]} indexed in the
        world this planner runs on (``issue_offset`` maps world index -> issue index)."""
        self.w, self.f, self.c, self.wc = world, forecasts, cfg, world_cfg
        self.issue_offset = issue_offset
        self.users, self.user_offset = users, user_offset   # carrier -> [T_users, S] active
        self.issue_pos = {int(i) - issue_offset: k
                          for k, i in enumerate(forecasts["mid"]["issues"])}
        self.cap_low = sum(world.present[c] * EFFICIENCY[c] * BANDWIDTH[c] for c in LOW)
        self.cap_mid = sum(world.present[c] * EFFICIENCY[c] * BANDWIDTH[c]
                           for c in ("LTE_1800", "NR_2100"))
        sl = world.slopes
        # Wh per MB on each radio (planner's simplified view of the energy model)
        self.k_low = sum(sl["low"][c] * world.present[c] for c in LOW) / np.where(
            self.cap_low > 0, self.cap_low, np.inf)
        self.k_mid = 0.5 * (sl["mid"]["LTE_1800"] / (EFFICIENCY["LTE_1800"] * 20)
                            + sl["mid"]["NR_2100"] / (EFFICIENCY["NR_2100"] * 20))
        self.k_nr = sl["nr3500"]["NR_3500"] / (EFFICIENCY["NR_3500"] * 100)
        cat = world_cfg.category
        self.r_mid = (tr38864.power(world_cfg.sleep_state, cat, 2)
                      / tr38864.power("micro_sleep", cat, 2))
        self.r_nr = (tr38864.power(world_cfg.sleep_state, cat, 1)
                     / tr38864.power("micro_sleep", cat, 1))
        self.margin_s = np.ones(world.S)      # per-sector factor (adaptive margin)
        self._was_forced = np.zeros(world.S, dtype=bool)
        self._noon = world.times.tz_convert("Europe/Bratislava").hour.to_numpy() == 12
        self.plan: np.ndarray | None = None   # [H, S] state index
        self.plan_t0 = 0
        self.last_state = np.zeros(world.S, dtype=np.int64)

    def _weights(self, t0: int) -> np.ndarray:
        idx = np.clip(np.arange(t0, t0 + HORIZON), 0, self.w.T - 1)
        if self.c.weight == "price":
            p = np.maximum(self.w.price[idx], 0.0)
            return p / max(np.nanmean(self.w.price), 1e-9)
        if self.c.weight == "co2":
            return self.w.co2[idx] / np.nanmean(self.w.co2)
        return np.ones(HORIZON)

    def costs(self, k: int) -> np.ndarray:
        """[H, S, 4] expected Wh per state, inf where infeasible at the risk quantile."""
        w, c, wc = self.w, self.c, self.wc
        p50 = {t: self.f[t][0.5][k].astype(float) for t in ("mid", "nr", "low")}
        m = c.margin * self.margin_s
        risk = {t: self.f[t][c.risk_q][k].astype(float) * m for t in ("mid", "nr", "low")}
        idle_m, idle_n = w.idle["mid"][None], w.idle["nr3500"][None]
        has_nr = w.present["NR_3500"][None]
        nr_mb = np.where(has_nr, p50["nr"], 0.0)

        on_mid = idle_m + self.k_mid * p50["mid"]
        on_nr = np.where(has_nr, idle_n + self.k_nr * nr_mb, 0.0)
        off_mid = idle_m * self.r_mid
        off_nr = np.where(has_nr, idle_n * self.r_nr, 0.0)
        kl = self.k_low[None]
        cost = np.empty(p50["mid"].shape + (4,))
        cost[..., 0] = on_mid + on_nr
        cost[..., 1] = on_mid + self.k_mid * nr_mb + off_nr
        cost[..., 2] = off_mid + on_nr + kl * p50["mid"]
        cost[..., 3] = off_mid + off_nr + kl * (p50["mid"] + nr_mb)

        def util(mb, cap):
            return np.divide(mb, cap[None], out=np.full_like(mb, np.inf), where=cap[None] > 0)

        r_nr = np.where(has_nr, risk["nr"], 0.0)
        ok1 = util(risk["mid"] + r_nr, self.cap_mid) * wc.peak_margin <= wc.rho_max_mid
        ok2 = util(risk["low"] + risk["mid"], self.cap_low) * wc.peak_margin <= wc.rho_max_low
        ok3 = util(risk["low"] + risk["mid"] + r_nr, self.cap_low) * wc.peak_margin \
            <= wc.rho_max_low
        if c.min_user_mbps > 0 and self.users is not None:
            f1, f2, f3 = self._rate_ok(k, p50["mid"].shape[0])
            ok1, ok2, ok3 = ok1 & f1, ok2 & f2, ok3 & f3
        cost[..., 1] = np.where(ok1 & has_nr, cost[..., 1], np.inf)
        cost[..., 2] = np.where(ok2, cost[..., 2], np.inf)
        cost[..., 3] = np.where(ok3 & has_nr, cost[..., 3], np.inf)
        return cost * self._weights(self.issue_t(k))[:, None, None]

    def _rate_ok(self, k: int, H: int):  # noqa: N803
        """Per-user rate on the receiving layer >= the floor, for NR asleep / mid asleep /
        both asleep. Users forecast: the same quarter-hours one week earlier."""
        u = self.users
        t0 = self.issue_t(k) - self.issue_offset
        idx = np.clip(np.arange(t0, t0 + H) + self.user_offset - 672, 0,
                      len(u["LTE_700"]) - 1)
        u_low = u["LTE_700"][idx] + u["LTE_800"][idx]
        u_mid = u["LTE_1800"][idx] + u["NR_2100"][idx]
        u_nr = u["NR_3500"][idx]
        mbps_low = (self.cap_low * 100 * 8 / 900)[None]
        mbps_mid = (self.cap_mid * 100 * 8 / 900)[None]
        floor = self.c.min_user_mbps

        def ok(mbps, users, moved):
            return (moved < 0.05) | (mbps / np.maximum(users, 1e-3) >= floor)
        return (ok(mbps_mid, u_mid + u_nr, u_nr), ok(mbps_low, u_low + u_mid, u_mid),
                ok(mbps_low, u_low + u_mid + u_nr, u_mid + u_nr))

    def issue_t(self, k: int) -> int:
        return int(self.f["mid"]["issues"][k])

    def solve(self, cost: np.ndarray, start: np.ndarray) -> np.ndarray:
        """Exact shortest path over [H, S, 4] costs from each sector's current state."""
        H, S, N = cost.shape  # noqa: N806
        sw = self.c.switch_cost_wh * (1 - np.eye(N))          # [4,4] from->to
        acc = cost[0] + sw[start]                              # [S,4]
        back = np.zeros((H, S, N), dtype=np.int8)
        for h in range(1, H):
            tot = acc[:, :, None] + sw[None]                   # [S, from, to]
            back[h] = np.argmin(tot, axis=1)
            acc = np.min(tot, axis=1) + cost[h]
        path = np.zeros((H, S), dtype=np.int64)
        path[-1] = np.argmin(acc, axis=1)
        for h in range(H - 1, 0, -1):
            path[h - 1] = back[h, np.arange(S), path[h]]
        return path

    def _adapt(self, obs: Observation) -> None:
        c = self.c
        new = obs.forced_awake & ~self._was_forced
        self._was_forced = obs.forced_awake.copy()
        if new.any():
            self.margin_s[new] = np.minimum(self.margin_s[new] * c.adaptive_step, c.adaptive_cap)
        if self._noon[obs.t] and obs.t % 4 == 0:
            self.margin_s[:] = np.maximum(1.0, self.margin_s * c.adaptive_decay)

    def __call__(self, obs: Observation) -> tuple[np.ndarray, np.ndarray]:
        t = obs.t
        if self.c.adaptive_step > 1.0:
            self._adapt(obs)
        cur = np.where(obs.mid_state == ASLEEP, 2, 0) + np.where(obs.nr_state == ASLEEP, 1, 0)
        if t in self.issue_pos and (self.plan is None or t - self.plan_t0 >= self.c.replan_every
                                    or obs.forced_awake.any()):
            k = self.issue_pos[t]
            self.plan = self.solve(self.costs(k), cur)
            self.plan_t0 = t
        if self.plan is None or t - self.plan_t0 >= HORIZON:
            z = np.zeros_like(obs.mid_state)
            return z, z
        s = self.plan[t - self.plan_t0]
        return STATES[s, 0].astype(np.int8), STATES[s, 1].astype(np.int8)
