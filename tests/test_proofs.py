"""Z3 proofs of the arbiter's capacity check, and a numeric check that the formulas the proofs
use are the ones the real planner and simulator use."""

import numpy as np
import pandas as pd
import pytest

from yovahti.arbiter.proofs import prove_all
from yovahti.forecast.quantile import HORIZON, TARGETS
from yovahti.plan.dp import STATES, DPPlanner, PlannerConfig
from yovahti.world.data import BANDWIDTH, EFFICIENCY, WorldData
from yovahti.world.sim import Stepper, WorldConfig


def test_every_proof_holds():
    bad = [str(p) for p in prove_all() if not p.proved]
    assert not bad, bad


def random_world(rng, T, S):  # noqa: N803
    times = pd.date_range("2025-10-26", periods=T, freq="15min", tz="UTC")
    util = {c: rng.uniform(0, hi, (T, S)) for c, hi in
            (("LTE_700", 30), ("LTE_800", 30), ("LTE_1800", 60), ("NR_2100", 60),
             ("NR_3500", 40))}
    present = {c: np.ones(S, dtype=bool) for c in util}
    present["NR_3500"] = rng.random(S) < 0.7
    util["NR_3500"] *= present["NR_3500"]
    vol = {c: util[c] * BANDWIDTH[c] * EFFICIENCY[c] for c in util}
    return WorldData(times=times, sectors=[f"s{i}/1" for i in range(S)], util=util, vol=vol,
                     present=present, gsm_util=np.zeros((T, S)),
                     idle={"low": np.full(S, 70.0), "mid": np.full(S, 40.0),
                           "nr3500": np.full(S, 60.0)},
                     slopes={"low": {"GSM_900": 0.0, "LTE_700": 0.8, "LTE_800": 0.8},
                             "mid": {"LTE_1800": 0.8, "NR_2100": 1.0},
                             "nr3500": {"NR_3500": 1.2}},
                     measured_energy={}, price=np.full(T, 50.0), co2=np.full(T, 20.0))


@pytest.mark.parametrize("seed", range(5))
def test_feasible_at_p90_means_no_congestion_in_the_world(seed):
    """Perfect P90 (= the real traffic): every state the arbiter allows is clean in the world."""
    rng = np.random.default_rng(seed)
    T, S = HORIZON, 400  # noqa: N806
    w = random_world(rng, T, S)
    actual = {t: sum(w.vol[c] for c in TARGETS[t])[None] for t in TARGETS}
    fc = {t: {"issues": np.array([0]), 0.1: actual[t], 0.5: actual[t], 0.9: actual[t]}
          for t in TARGETS}
    cfg = WorldConfig(auto_wake=False)
    cost = DPPlanner(w, fc, PlannerConfig(), cfg).costs(0)            # [H, S, 4]
    allowed = 0
    for state in (1, 2, 3):
        st = Stepper(w, cfg)
        mid, nr = STATES[state]
        for h in range(T):
            out = st.step(np.full(S, mid, np.int8), np.full(S, nr, np.int8))
            ok = np.isfinite(cost[h, :, state])
            allowed += int(ok.sum())
            assert not out.congested[ok].any()
            assert (out.unserved_mb[ok] == 0).all()
    assert allowed > 1000                       # the check is not vacuous
