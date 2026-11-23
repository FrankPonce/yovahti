"""The simulator moves traffic, counts energy and congestion, and the watchdog wakes radios."""

import numpy as np
import pandas as pd
import pytest

from yovahti.baselines.simple import Oracle, StaticThresholds, always_on
from yovahti.world.data import BANDWIDTH, EFFICIENCY, WorldData
from yovahti.world.sim import ASLEEP, AWAKE, WorldConfig, run, summarise


def tiny_world(mid_util=5.0, low_util=5.0, T=8, S=2, nr=True):  # noqa: N803
    times = pd.date_range("2025-10-26", periods=T, freq="15min", tz="UTC")
    util = {
        "LTE_700": np.full((T, S), low_util), "LTE_800": np.full((T, S), low_util),
        "LTE_1800": np.full((T, S), mid_util), "NR_2100": np.full((T, S), mid_util),
        "NR_3500": np.full((T, S), 2.0 if nr else 0.0),
    }
    vol = {c: util[c] * BANDWIDTH[c] * EFFICIENCY[c] for c in util}
    present = {c: np.ones(S, dtype=bool) for c in util}
    present["NR_3500"] = np.full(S, nr)
    return WorldData(
        times=times, sectors=[f"s{i}/1" for i in range(S)], util=util, vol=vol, present=present,
        gsm_util=np.zeros((T, S)),
        idle={"low": np.full(S, 70.0), "mid": np.full(S, 40.0), "nr3500": np.full(S, 60.0 * nr)},
        slopes={"low": {"GSM_900": 0.0, "LTE_700": 0.8, "LTE_800": 0.8},
                "mid": {"LTE_1800": 0.8, "NR_2100": 1.0}, "nr3500": {"NR_3500": 1.2}},
        measured_energy={}, price=np.full(T, 50.0), co2=np.full(T, 20.0))


def sleep_mid(obs):
    return np.full_like(obs.mid_state, ASLEEP), np.zeros_like(obs.nr_state)


def test_b0_energy_is_the_model():
    w = tiny_world()
    r = run(w, always_on)
    assert r.energy["mid"][0, 0] == pytest.approx(40 + 0.8 * 5 + 1.0 * 5)
    assert r.energy["nr3500"][0, 0] == pytest.approx(60 + 1.2 * 2)
    assert not r.congested.any()


def test_sleeping_mid_moves_traffic_and_saves():
    w = tiny_world()
    b0 = run(w, always_on)
    r = run(w, sleep_mid, config=WorldConfig(category=1))
    assert (r.mid_state == ASLEEP).all()
    assert (r.low_util > b0.low_util).all()          # moved traffic lands on the low band
    assert r.energy["mid"][1, 0] == pytest.approx(40 / 50)   # deep sleep, Category 1
    s = summarise(w, r, b0)
    assert s["kwh_saved_pct"] > 0
    assert r.toggles == 0


def test_watchdog_wakes_a_congested_sector_and_holds():
    w = tiny_world(mid_util=40.0, low_util=30.0)     # moving mid traffic overloads the low band
    r = run(w, sleep_mid, config=WorldConfig(hold=3))
    assert r.congested[0].all()
    assert (r.mid_state[1:4] == AWAKE).all()          # held awake for 3 quarter-hours
    assert r.watchdog_wakes >= 2


def test_oracle_never_congests_and_b1_reacts():
    w = tiny_world(mid_util=3.0, low_util=3.0)
    o = run(w, Oracle(w))
    assert not o.congested.any() and (o.mid_state == ASLEEP).all()
    b1 = run(w, StaticThresholds())
    assert (b1.mid_state[0] == AWAKE).all()          # nothing observed yet at t=0
    assert (b1.mid_state[1:] == ASLEEP).all()


def test_sector_without_nr_never_sleeps_nr():
    w = tiny_world(nr=False)
    r = run(w, lambda o: (np.zeros_like(o.mid_state), np.ones_like(o.nr_state)))
    assert (r.nr_state == AWAKE).all() and (r.energy["nr3500"] == 0).all()
