"""Ideas borrowed from other published methods, tried on Yövahti's planner (validation only).

* ``AdaptiveMarginPlanner`` · Samsung US20240422667A1's adaptive QoS threshold, as feedback:
  a sector whose radios the watchdog had to wake gets a higher planning margin (x ``step``,
  capped), decaying back towards 1.0 every day it stays clean.
* ``NightRollback`` · Parallel Wireless US20230127116A1's rollback: once the watchdog wakes a
  sector, it stays awake for the rest of that night (until local noon).

An idea only counts as an improvement if it beats the uniform margin dial (B4 at margin 1.15,
1.3, ...) at matched congestion; otherwise it is the same trade-off by another route.
"""

from __future__ import annotations

import numpy as np

from yovahti.plan.dp import DPPlanner
from yovahti.world.sim import AWAKE, Observation

TZ = "Europe/Bratislava"


class AdaptiveMarginPlanner(DPPlanner):
    def __init__(self, *a, step: float = 1.15, cap: float = 2.0, decay: float = 0.97, **kw):
        super().__init__(*a, **kw)
        self.margin = np.ones(self.w.S)
        self.step, self.cap, self.decay = step, cap, decay
        self.was_forced = np.zeros(self.w.S, dtype=bool)
        self.hour = self.w.times.tz_convert(TZ).hour.to_numpy()
        self.c.margin = self.margin                    # costs() multiplies by c.margin

    def __call__(self, obs: Observation) -> tuple[np.ndarray, np.ndarray]:
        new = obs.forced_awake & ~self.was_forced
        self.was_forced = obs.forced_awake.copy()
        if new.any():
            self.margin[new] = np.minimum(self.margin[new] * self.step, self.cap)
        if self.hour[obs.t] == 12 and obs.t % 4 == 0:
            self.margin[:] = np.maximum(1.0, self.margin * self.decay)
        self.c.margin = self.margin
        return super().__call__(obs)


class NightRollback:
    """Wraps any policy: a sector the watchdog woke stays awake until local noon."""

    def __init__(self, inner, world):
        self.inner = inner
        self.blocked = np.zeros(world.S, dtype=bool)
        self.hour = world.times.tz_convert(TZ).hour.to_numpy()

    def __call__(self, obs: Observation) -> tuple[np.ndarray, np.ndarray]:
        if self.hour[obs.t] == 12:
            self.blocked[:] = False
        self.blocked |= obs.forced_awake
        ms, ns = self.inner(obs)
        ms = np.where(self.blocked, AWAKE, ms).astype(np.int8)
        ns = np.where(self.blocked, AWAKE, ns).astype(np.int8)
        return ms, ns
