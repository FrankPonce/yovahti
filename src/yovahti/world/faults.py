"""Control- and measurement-plane faults (S3, I33): what goes wrong between an operator's
decision and the radio, and between the radio and the KPIs the operator sees.

The physics stays in `sim.Stepper`; faults sit in front of it. A scheduled state reaches the
radio late (``actuation_delay``) or never (``stuck``), an apply's acknowledgement can be lost
so its outcome is ``unknown`` until the network can tell (``ack_loss``), and KPIs can lag
(``kpi_lag``) or go missing (``kpi_dropout``). All draws are seeded and reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Faults:
    actuation_delay: int = 0          # quarter-hours between a scheduled switch and the radio
    stuck: frozenset[int] = field(default_factory=frozenset)   # sectors ignoring commands
    ack_loss: float = 0.0             # chance an apply's acknowledgement is lost
    ack_applied: float = 0.5          # chance a change with a lost ack was carried out anyway
    resolve_after: int = 2            # quarter-hours until an unknown outcome can be observed
    kpi_lag: int = 0                  # quarter-hours the KPI feed lags behind the clock
    kpi_dropout: float = 0.0          # chance a single KPI value is missing
    seed: int = 0

    @property
    def any(self) -> bool:
        return bool(self.actuation_delay or self.stuck or self.ack_loss or self.kpi_lag
                    or self.kpi_dropout)

    def dropout_mask(self, T: int, S: int) -> np.ndarray | None:  # noqa: N803
        """[T, S] True where a KPI value is missing (same for every layer of a sector)."""
        if not self.kpi_dropout:
            return None
        return np.random.default_rng(self.seed + 17).random((T, S)) < self.kpi_dropout

    def commanded(self, schedule: np.ndarray, t: int, current: np.ndarray) -> np.ndarray:
        """State the radios actually take at ``t``: the schedule ``actuation_delay`` earlier,
        and stuck sectors keep what they had."""
        src = t - self.actuation_delay
        want = schedule[src] if src >= 0 else np.zeros_like(schedule[0])
        if self.stuck:
            want = want.copy()
            idx = np.fromiter(self.stuck, dtype=np.int64)
            want[idx] = current[idx]
        return want
