"""Event surges: traffic the forecaster can't see coming, announced only in a calendar.

SYNTHETIC, and labelled as such in every result: a surge adds downlink traffic to a few real
sectors for a window (a match ending, a ferry arriving). The forecasts are left untouched (they
were made from the real data and know nothing of the event), so the only way to anticipate it
is to read the calendar entry, which is the unstructured channel an LLM agent adds (E1).

Size: by default a surge is 1.5x what the sector's coverage layer may take at its limit
(rho_max_low / peak margin), so moving it there by sleeping the capacity radios overloads the
low band, while the awake capacity radios carry it comfortably (checked: <= 80 % of their own
limit). Split 60/40 between NR 3500 and the mid band where NR exists (crowds carry 5G phones).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from yovahti.world.data import BANDWIDTH, EFFICIENCY, LOW, MID, WorldData
from yovahti.world.sim import WorldConfig


@dataclass(frozen=True)
class Event:
    title: str
    sectors: tuple[int, ...]     # world sector indices
    start: int                   # quarter-hour index (inclusive)
    end: int                     # exclusive
    scale: float = 1.5           # x the coverage layer's allowed load

    def calendar(self, text: str) -> dict:
        return {"t": self.start, "title": self.title, "text": text}


def _cap(world: WorldData, carriers: list[str]) -> np.ndarray:
    return sum(world.present[c] * EFFICIENCY[c] * BANDWIDTH[c] for c in carriers)


def surge_mb(world: WorldData, ev: Event, cfg: WorldConfig) -> dict[str, np.ndarray]:
    """{carrier: [len(sectors)] MB per quarter-hour added} for an event."""
    s = np.array(ev.sectors)
    allowed_low = _cap(world, LOW)[s] * cfg.rho_max_low / cfg.peak_margin
    total = ev.scale * allowed_low
    has_nr = world.present["NR_3500"][s]
    nr = np.where(has_nr, 0.6 * total, 0.0)
    mid = total - nr
    cap_mid = _cap(world, MID)[s]
    # keep the awake capacity layers well inside their own limits
    mid = np.minimum(mid, 0.8 * cap_mid * cfg.rho_max_mid / cfg.peak_margin)
    out = {}
    w_mid = {c: world.present[c][s] * EFFICIENCY[c] * BANDWIDTH[c] for c in MID}
    tot = sum(w_mid.values())
    for c in MID:
        out[c] = np.divide(mid * w_mid[c], tot, out=np.zeros_like(mid), where=tot > 0)
    out["NR_3500"] = nr
    return out


def inject(world: WorldData, events: list[Event], cfg: WorldConfig | None = None) -> WorldData:
    """A copy of the world with the events' traffic added (vol and util stay consistent)."""
    cfg = cfg or WorldConfig()
    vol = {c: v.copy() for c, v in world.vol.items()}
    util = {c: v.copy() for c, v in world.util.items()}
    for ev in events:
        s = np.array(ev.sectors)
        for c, mb in surge_mb(world, ev, cfg).items():
            vol[c][ev.start:ev.end, s] += mb[None, :]
            util[c][ev.start:ev.end, s] += (mb / (EFFICIENCY[c] * BANDWIDTH[c]))[None, :]
    return replace(world, vol=vol, util=util)
