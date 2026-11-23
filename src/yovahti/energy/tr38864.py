"""3GPP TR 38.864 V18.1.0 base-station power model (Rel-18 network energy saving study).

Values are copied from the spec (clause 5.1, Tables 5.1-1 to 5.1-5), fetched from the 3GPP
archive (38864-i10.zip). Power is *relative* to deep sleep (= 1), so the model is vendor-neutral.
Transition energy E is in "relative power x ms", added on top of the sleep power when a state is
entered and left; T is the total time to enter and leave the state.

Reference configurations (Table 5.1-1):
    Set 1 FR1: TDD, 100 MHz, 30 kHz SCS, 64 TX/RX RUs, 55 dBm  (e.g. NR 3.5 GHz massive MIMO)
    Set 2 FR1: FDD,  20 MHz, 15 kHz SCS, 32 TX/RX RUs, 49 dBm  (e.g. LTE/NR 1800/2100)
    Set 3 FR2: TDD, 100 MHz, 120 kHz SCS, 2 TX/RX RUs, 33 dBm  (mmWave)

BS Category 1 and 2 are two vendor-neutral hardware assumptions in the study. Category 2 has a
much lower active-to-sleep ratio and much slower deep sleep (10 s vs 50 ms).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Category = Literal[1, 2]
RefSet = Literal[1, 2, 3]
State = Literal["deep_sleep", "light_sleep", "micro_sleep", "active_dl", "active_ul"]

# Table 5.1-3: relative power P (deep sleep = 1). Sleep states are the same for every set.
_POWER: dict[Category, dict[State, tuple[float, float, float]]] = {
    1: {
        "deep_sleep": (1, 1, 1),
        "light_sleep": (25, 25, 25),
        "micro_sleep": (55, 50, 38),
        "active_dl": (280, 200, 152),
        "active_ul": (110, 90, 80),
    },
    2: {
        "deep_sleep": (1, 1, 1),
        "light_sleep": (2.1, 2.1, 2.1),
        "micro_sleep": (5.5, 5, 3),
        "active_dl": (32, 26, 17.6),
        "active_ul": (6.5, 5.8, 4.2),
    },
}

# Table 5.1-4: total transition time T in milliseconds (enter + leave).
_TRANSITION_MS: dict[Category, dict[State, float]] = {
    1: {"deep_sleep": 50, "light_sleep": 6, "micro_sleep": 0},
    2: {"deep_sleep": 10_000, "light_sleep": 640, "micro_sleep": 0},
}

# Table 5.1-5: additional transition energy E (relative power x ms).
_TRANSITION_ENERGY: dict[Category, dict[State, float]] = {
    1: {"deep_sleep": 1000, "light_sleep": 90, "micro_sleep": 0},
    2: {"deep_sleep": 17_000, "light_sleep": 1088, "micro_sleep": 0},
}

SLEEP_STATES: tuple[State, ...] = ("deep_sleep", "light_sleep", "micro_sleep")


@dataclass(frozen=True)
class SleepState:
    name: State
    relative_power: float
    transition_ms: float
    transition_energy: float  # relative power x ms

    def min_worthwhile_ms(self, idle_power: float) -> float:
        """Shortest sleep that saves energy vs staying in a state drawing `idle_power`.

        Sleeping for t ms costs P_sleep * t + E; staying costs P_idle * t. Break-even at
        t = E / (P_idle - P_sleep). The sleep must also last at least the transition time T.
        """
        gap = idle_power - self.relative_power
        if gap <= 0:
            return float("inf")
        return max(self.transition_ms, self.transition_energy / gap)


def power(state: State, category: Category = 1, ref_set: RefSet = 2) -> float:
    """Relative power of a state for a BS category and reference configuration."""
    return float(_POWER[category][state][ref_set - 1])


def sleep_state(state: State, category: Category = 1, ref_set: RefSet = 2) -> SleepState:
    if state not in SLEEP_STATES:
        raise ValueError(f"{state} is not a sleep state")
    return SleepState(
        name=state,
        relative_power=power(state, category, ref_set),
        transition_ms=float(_TRANSITION_MS[category][state]),
        transition_energy=float(_TRANSITION_ENERGY[category][state]),
    )


def sleep_saving_fraction(state: State, category: Category = 1, ref_set: RefSet = 2) -> float:
    """Fraction of *micro-sleep* (idle but on) power saved by going to a deeper sleep state.

    An empty but switched-on carrier sits mostly in micro sleep between its mandatory
    broadcast signals; this is the share a deeper state removes, before transition costs.
    """
    idle = power("micro_sleep", category, ref_set)
    return 1.0 - power(state, category, ref_set) / idle
