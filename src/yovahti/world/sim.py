"""The simulator: replay real traffic while capacity radios sleep.

Each quarter-hour a policy chooses, per sector, whether the mid-band radio (LTE 1800 + NR 2100)
and the NR 3500 radio sleep. The world then:

1. re-routes traffic: NR 3500 -> mid band if it is awake, else -> low band; mid band -> low band
   (converted with each band's measured MB per % per MHz);
2. computes energy per radio from the fitted model (awake) or the 3GPP sleep ratio (asleep),
   plus transition energy for each switch;
3. checks quality on every layer that received traffic: *congested* when average load x the
   peak margin exceeds rho_max, *unserved* traffic above the layer's ceiling;
4. if ``auto_wake`` is on (the watchdog), wakes the sleeping radios of a congested sector from
   the next quarter-hour and keeps them awake for ``hold`` quarter-hours.

Policies only see the previous quarter-hour's observed KPIs (what a real controller sees),
unless they are explicitly given forecasts. The oracle baseline is the only exception and is
labelled as such.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from yovahti.energy import tr38864
from yovahti.world.data import BANDWIDTH, EFFICIENCY, LOW, WorldData

AWAKE, ASLEEP = 0, 1


@dataclass
class WorldConfig:
    rho_max_low: float = 40.0    # % average load on the low band that counts as congested
    ceiling_low: float = 50.0    # % the low band never exceeded in the data (E12)
    rho_max_mid: float = 70.0
    ceiling_mid: float = 100.0
    peak_margin: float = 1.25    # intra-interval peaks above the 15-min average (stated, E12)
    sleep_state: tr38864.State = "deep_sleep"
    category: tr38864.Category = 1
    auto_wake: bool = True
    hold: int = 4                # quarter-hours a watchdog wake-up is held


@dataclass
class Observation:
    """What a controller sees at the start of quarter-hour t (about t-1)."""
    t: int
    util: dict[str, np.ndarray]      # carrier -> [S] observed load (0 for sleeping carriers)
    low_util: np.ndarray             # [S] combined low-band load incl. moved traffic
    mid_util: np.ndarray             # [S] combined mid-band load incl. moved NR 3500 traffic
    mid_state: np.ndarray
    nr_state: np.ndarray
    forced_awake: np.ndarray         # [S] watchdog hold active


Policy = Callable[[Observation], tuple[np.ndarray, np.ndarray]]


@dataclass
class RunResult:
    name: str
    energy: dict[str, np.ndarray]    # unit -> [T,S] Wh
    mid_state: np.ndarray            # [T,S] applied states
    nr_state: np.ndarray
    low_util: np.ndarray             # [T,S] % after re-routing
    mid_util: np.ndarray
    congested: np.ndarray            # [T,S] bool
    unserved_mb: np.ndarray          # [T,S]
    watchdog_wakes: int
    toggles: int
    config: WorldConfig = field(repr=False, default_factory=WorldConfig)

    def total_wh(self) -> np.ndarray:  # [T,S]
        return self.energy["low"] + self.energy["mid"] + self.energy["nr3500"]


def _cap_per_pct(world: WorldData, carriers: list[str]) -> np.ndarray:
    """[S] MB per quarter-hour that 1 % of the layer's combined capacity carries."""
    return sum(world.present[c] * EFFICIENCY[c] * BANDWIDTH[c] for c in carriers)


def run(world: WorldData, policy: Policy, name: str = "policy",
        config: WorldConfig | None = None) -> RunResult:
    cfg = config or WorldConfig()
    T, S = world.T, world.S  # noqa: N806
    cap_low = _cap_per_pct(world, LOW)
    cap_mid = _cap_per_pct(world, ["LTE_1800", "NR_2100"])
    has_nr = world.present["NR_3500"]
    has_low = cap_low > 0

    ratio_mid = (tr38864.power(cfg.sleep_state, cfg.category, 2)
                 / tr38864.power("micro_sleep", cfg.category, 2))
    ratio_nr = (tr38864.power(cfg.sleep_state, cfg.category, 1)
                / tr38864.power("micro_sleep", cfg.category, 1))
    # transition energy per switch, as Wh: idle W x (E / P_micro) ms
    st_mid = tr38864.sleep_state(cfg.sleep_state, cfg.category, 2)
    st_nr = tr38864.sleep_state(cfg.sleep_state, cfg.category, 1)
    tr_mid = (world.idle["mid"] * 4) * (st_mid.transition_energy
                                        / tr38864.power("micro_sleep", cfg.category, 2)) / 3.6e6
    tr_nr = (world.idle["nr3500"] * 4) * (st_nr.transition_energy
                                          / tr38864.power("micro_sleep", cfg.category, 1)) / 3.6e6

    e = {k: np.zeros((T, S)) for k in ("low", "mid", "nr3500")}
    mid_s = np.zeros((T, S), dtype=np.int8)
    nr_s = np.zeros((T, S), dtype=np.int8)
    low_u = np.zeros((T, S))
    mid_u = np.zeros((T, S))
    cong = np.zeros((T, S), dtype=bool)
    unserved = np.zeros((T, S))
    hold_until = np.full(S, -1)
    wakes = 0
    prev_mid = np.zeros(S, dtype=np.int8)
    prev_nr = np.zeros(S, dtype=np.int8)
    obs = Observation(t=0, util={c: world.util[c][0] * 0 for c in world.util},
                      low_util=np.zeros(S), mid_util=np.zeros(S), mid_state=prev_mid,
                      nr_state=prev_nr, forced_awake=np.zeros(S, dtype=bool))
    sl = world.slopes

    for t in range(T):
        want_mid, want_nr = policy(obs)
        forced = hold_until >= t
        ms = np.where(forced | ~has_low, AWAKE, want_mid).astype(np.int8)
        ns = np.where(forced | ~has_nr, AWAKE, want_nr).astype(np.int8)

        v = {c: world.vol[c][t] for c in world.vol}
        nr_mb = v["NR_3500"]
        to_mid = np.where((ns == ASLEEP) & (ms == AWAKE), nr_mb, 0.0)
        mid_mb = v["LTE_1800"] + v["NR_2100"] + to_mid
        to_low = np.where(ms == ASLEEP, mid_mb, 0.0) + np.where(
            (ns == ASLEEP) & (ms == ASLEEP), nr_mb, 0.0)
        low_mb = v["LTE_700"] + v["LTE_800"] + to_low

        lu = np.divide(low_mb, cap_low, out=np.zeros(S), where=cap_low > 0)
        mu = np.where(ms == AWAKE, np.divide(mid_mb, cap_mid, out=np.zeros(S),
                                             where=cap_mid > 0), 0.0)
        low_u[t], mid_u[t] = lu, mu

        # per-carrier loads after re-routing, for the energy model
        add_low = np.divide(to_low, cap_low, out=np.zeros(S), where=cap_low > 0)
        u700 = world.util["LTE_700"][t] + add_low * world.present["LTE_700"]
        u800 = world.util["LTE_800"][t] + add_low * world.present["LTE_800"]
        e["low"][t] = (world.idle["low"] + sl["low"]["GSM_900"] * world.gsm_util[t]
                       + sl["low"]["LTE_700"] * u700 + sl["low"]["LTE_800"] * u800)
        add_2100 = np.divide(to_mid, EFFICIENCY["NR_2100"] * BANDWIDTH["NR_2100"])
        mid_on = (world.idle["mid"] + sl["mid"]["LTE_1800"] * world.util["LTE_1800"][t]
                  + sl["mid"]["NR_2100"] * (world.util["NR_2100"][t] + add_2100))
        e["mid"][t] = np.where(ms == AWAKE, mid_on, world.idle["mid"] * ratio_mid)
        nr_on = world.idle["nr3500"] + sl["nr3500"]["NR_3500"] * world.util["NR_3500"][t]
        e["nr3500"][t] = np.where(has_nr, np.where(ns == AWAKE, nr_on,
                                                   world.idle["nr3500"] * ratio_nr), 0.0)
        e["mid"][t] += (ms != prev_mid) * tr_mid
        e["nr3500"][t] += (ns != prev_nr) * tr_nr

        c_low = lu * cfg.peak_margin > cfg.rho_max_low
        c_mid = mu * cfg.peak_margin > cfg.rho_max_mid
        cong[t] = (c_low & (to_low > 0)) | (c_mid & (to_mid > 0))
        # only traffic pushed beyond a layer's ceiling by sleeping counts as unserved: the
        # layer's own traffic was carried in reality, whatever our capacity estimate says
        over_low = np.maximum(0.0, low_mb - np.maximum(cap_low * cfg.ceiling_low, low_mb - to_low))
        over_mid = np.maximum(0.0, mid_mb - np.maximum(cap_mid * cfg.ceiling_mid, mid_mb - to_mid))
        unserved[t] = over_low + over_mid * (ms == AWAKE)

        if cfg.auto_wake:
            trigger = cong[t] & ((ms == ASLEEP) | (ns == ASLEEP))
            wakes += int(trigger.sum())
            hold_until = np.where(trigger, t + cfg.hold, hold_until)

        mid_s[t], nr_s[t] = ms, ns
        obs = Observation(
            t=t + 1,
            util={c: (world.util[c][t] if c not in ("LTE_1800", "NR_2100", "NR_3500") else
                      world.util[c][t] * ((ms if c != "NR_3500" else ns) == AWAKE))
                  for c in world.util},
            low_util=lu, mid_util=mu, mid_state=ms, nr_state=ns,
            forced_awake=hold_until >= t + 1)
        prev_mid, prev_nr = ms, ns

    toggles = int((np.diff(mid_s, axis=0) != 0).sum() + (np.diff(nr_s, axis=0) != 0).sum())
    return RunResult(name=name, energy=e, mid_state=mid_s, nr_state=nr_s, low_util=low_u,
                     mid_util=mid_u, congested=cong, unserved_mb=unserved,
                     watchdog_wakes=wakes, toggles=toggles, config=cfg)


def summarise(world: WorldData, r: RunResult, ref: RunResult | None = None) -> dict[str, float]:
    """Totals, and savings against a reference run (normally B0, always awake)."""
    wh = r.total_wh()
    eur = (wh / 1e6 * world.price[:, None]).sum()
    kg = (wh / 1e3 * world.co2[:, None]).sum() / 1e3
    days = world.T / 96
    out = {
        "kwh": float(wh.sum() / 1e3),
        "eur": float(eur),
        "kg_co2": float(kg),
        "sleep_share_mid": float((r.mid_state == ASLEEP).mean()),
        "sleep_share_nr": float((r.nr_state == ASLEEP)[:, world.present["NR_3500"]].mean())
        if world.present["NR_3500"].any() else 0.0,
        "congested_qh": int(r.congested.sum()),
        "congested_qh_per_sector_day": float(r.congested.sum() / world.S / days),
        "unserved_gb": float(r.unserved_mb.sum() / 1e3),
        "watchdog_wakes": r.watchdog_wakes,
        "toggles_per_sector_day": float(r.toggles / world.S / days),
    }
    if ref is not None:
        base = ref.total_wh()
        b_eur = (base / 1e6 * world.price[:, None]).sum()
        b_kg = (base / 1e3 * world.co2[:, None]).sum() / 1e3
        out["kwh_saved_pct"] = float(100 * (1 - wh.sum() / base.sum()))
        out["eur_saved_pct"] = float(100 * (1 - eur / b_eur))
        out["co2_saved_pct"] = float(100 * (1 - kg / b_kg))
        out["kwh_saved_per_sector_day"] = float((base.sum() - wh.sum()) / 1e3 / world.S / days)
        cap = ref.energy["mid"] + ref.energy["nr3500"]
        cap_now = r.energy["mid"] + r.energy["nr3500"]
        out["capacity_radio_saved_pct"] = float(100 * (1 - cap_now.sum() / cap.sum()))
    return out
