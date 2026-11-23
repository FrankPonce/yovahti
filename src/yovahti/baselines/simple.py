"""Reference policies: B0 always-on, B1 static thresholds, and a perfect-foresight oracle.

B1 mimics the base station's own cell-sleep logic (CSM): it reacts to what it saw in the last
quarter-hour. Real CSM checks thresholds within seconds; at the data's 15-minute resolution it
can only react one interval late, which is stated wherever B1 appears.

The oracle sees the *current* quarter-hour's true traffic. It is not achievable; it bounds what
any planner could save under the same quality limits.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from yovahti.world.data import BANDWIDTH, EFFICIENCY, LOW, WorldData
from yovahti.world.sim import ASLEEP, AWAKE, Observation, WorldConfig


def always_on(obs: Observation) -> tuple[np.ndarray, np.ndarray]:
    """B0."""
    z = np.zeros_like(obs.mid_state)
    return z, z


@dataclass
class StaticThresholds:
    """B1: sleep a capacity radio when it and the coverage layer are quiet; wake on load."""
    mid_sleep_below: float = 10.0   # % combined mid-band load
    low_sleep_below: float = 15.0   # % combined low-band load
    wake_low_above: float = 30.0    # % low-band load (includes moved traffic while asleep)
    nr_sleep_below: float = 5.0
    mid_room_below: float = 30.0    # NR 3500 may sleep onto the mid band only below this
    wake_mid_above: float = 50.0

    def __call__(self, obs: Observation) -> tuple[np.ndarray, np.ndarray]:
        if obs.t == 0:
            z = np.zeros_like(obs.mid_state)
            return z, z
        ms, ns = obs.mid_state.copy(), obs.nr_state.copy()
        quiet = (obs.mid_util < self.mid_sleep_below) & (obs.low_util < self.low_sleep_below)
        ms = np.where((ms == AWAKE) & quiet, ASLEEP, ms)
        ms = np.where((ms == ASLEEP) & (obs.low_util > self.wake_low_above), AWAKE, ms)
        nr_quiet = ((obs.util["NR_3500"] < self.nr_sleep_below)
                    & (obs.mid_util < self.mid_room_below))
        ns = np.where((ns == AWAKE) & nr_quiet, ASLEEP, ns)
        loaded = (obs.mid_util > self.wake_mid_above) | (obs.low_util > self.wake_low_above)
        ns = np.where((ns == ASLEEP) & loaded, AWAKE, ns)
        return ms.astype(np.int8), ns.astype(np.int8)


class Oracle:
    """Perfect foresight: each quarter-hour, the most energy-saving feasible combination."""

    def __init__(self, world: WorldData, config: WorldConfig | None = None):
        self.w = world
        self.cfg = config or WorldConfig()
        self.cap_low = sum(world.present[c] * EFFICIENCY[c] * BANDWIDTH[c] for c in LOW)
        self.cap_mid = sum(world.present[c] * EFFICIENCY[c] * BANDWIDTH[c]
                           for c in ("LTE_1800", "NR_2100"))

    def __call__(self, obs: Observation) -> tuple[np.ndarray, np.ndarray]:
        t, w, c = obs.t, self.w, self.cfg
        v = {k: w.vol[k][t] for k in w.vol}
        low = v["LTE_700"] + v["LTE_800"]
        mid = v["LTE_1800"] + v["NR_2100"]
        nr = v["NR_3500"]

        def ok_low(extra):
            u = np.divide(low + extra, self.cap_low, out=np.full_like(low, np.inf),
                          where=self.cap_low > 0)
            return u * c.peak_margin <= c.rho_max_low

        def ok_mid(extra):
            u = np.divide(mid + extra, self.cap_mid, out=np.full_like(mid, np.inf),
                          where=self.cap_mid > 0)
            return u * c.peak_margin <= c.rho_max_mid

        both = ok_low(mid + nr)
        mid_only = ok_low(mid)
        nr_only = ok_mid(nr)
        idle_mid, idle_nr = w.idle["mid"], w.idle["nr3500"]
        ms = np.zeros(w.S, dtype=np.int8)
        ns = np.zeros(w.S, dtype=np.int8)
        ms[both] = ASLEEP
        ns[both] = ASLEEP
        rest = ~both
        pick_mid = rest & mid_only & (~nr_only | (idle_mid >= idle_nr))
        pick_nr = rest & nr_only & ~pick_mid
        ms[pick_mid] = ASLEEP
        ns[pick_nr] = ASLEEP
        return ms, ns
