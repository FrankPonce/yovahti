"""The DP planner is exact, respects feasibility, and B2/B3 follow their published rules."""

import numpy as np
import pytest
from test_world import tiny_world

from yovahti.baselines.published import OranScDemoRapp, PublishedThresholdMethod
from yovahti.baselines.simple import always_on
from yovahti.forecast.quantile import HORIZON
from yovahti.plan.dp import STATES, DPPlanner, PlannerConfig
from yovahti.world.sim import ASLEEP, AWAKE, WorldConfig, run, summarise


def flat_forecasts(world, mid=50.0, nr=20.0, low=50.0, spread=1.0):
    S = world.S  # noqa: N806
    issues = np.arange(0, world.T, 4)

    def block(v):
        base = np.full((len(issues), HORIZON, S), v, dtype=np.float32)
        return {0.1: base / spread, 0.5: base, 0.9: base * spread}
    out = {"mid": block(mid), "nr": block(nr), "low": block(low)}
    for k in out:
        out[k]["issues"] = issues
    return out


def make_planner(world, fc, **kw):
    return DPPlanner(world, fc, PlannerConfig(**kw), WorldConfig())


def test_solve_is_exact_with_switch_cost():
    w = tiny_world(S=1)
    p = make_planner(w, flat_forecasts(w), switch_cost_wh=10.0)
    cost = np.full((HORIZON, 1, 4), 100.0)   # states 1 and 2 are expensive here
    cost[:, :, 0] = 5.0
    cost[:, :, 3] = 4.0          # cheaper by 1 per step: worth switching once over 40 steps
    path = p.solve(cost, np.array([0]))
    assert (path[:, 0] == 3).all()
    cost[:, :, 3] = 4.9          # gains 0.1 x 40 = 4 < switch cost 10: stay
    assert (p.solve(cost, np.array([0]))[:, 0] == 0).all()


def test_infeasible_state_never_chosen():
    w = tiny_world(S=1)
    p = make_planner(w, flat_forecasts(w))
    cost = np.full((HORIZON, 1, 4), 5.0)
    cost[:, :, 2] = np.inf
    cost[:, :, 3] = np.inf
    cost[:, :, 1] = 1.0
    assert (p.solve(cost, np.array([0]))[:, 0] == 1).all()


def test_planner_sleeps_when_quiet_and_saves():
    w = tiny_world(mid_util=3.0, low_util=3.0, T=16)
    fc = flat_forecasts(w, mid=3.0 * 20 * 2.55 + 3.0 * 20 * 4.42, nr=2 * 100 * 4.28,
                        low=3.0 * 10 * 3.03 + 3.0 * 10 * 3.18)
    r = run(w, make_planner(w, fc))
    assert (r.mid_state == ASLEEP).mean() > 0.9
    assert summarise(w, r, run(w, always_on))["kwh_saved_pct"] > 0
    assert not r.congested.any()


def test_planner_stays_awake_when_p90_would_congest():
    w = tiny_world(mid_util=3.0, low_util=3.0, T=8)
    fc = flat_forecasts(w, mid=3000.0, nr=0.0, low=500.0, spread=3.0)   # P90 far too high
    r = run(w, make_planner(w, fc))
    assert (r.mid_state == AWAKE).all()


def test_b3_locks_below_four_percent_only():
    w = tiny_world(T=8)
    quiet = flat_forecasts(w, mid=1.0, nr=1.0)
    r = run(w, OranScDemoRapp(w, quiet, 0))
    assert (r.mid_state == ASLEEP).all()
    busy = flat_forecasts(w, mid=10_000.0, nr=10_000.0)
    assert (run(w, OranScDemoRapp(w, busy, 0)).mid_state == AWAKE).all()


def test_b2_picks_a_threshold_when_sleep_pays():
    w = tiny_world(mid_util=3.0, low_util=3.0, T=8)
    fc = flat_forecasts(w, mid=3.0 * 20 * 2.55 + 3.0 * 20 * 4.42, nr=10.0, low=100.0)
    b2 = PublishedThresholdMethod(w, fc, 0)
    r = run(w, b2)
    assert (b2.theta_mid > 0).all()
    assert (r.mid_state[1:] == ASLEEP).all()


def test_states_table():
    assert STATES.tolist() == [[0, 0], [0, 1], [1, 0], [1, 1]]


@pytest.mark.parametrize("weight", ["energy", "price", "co2"])
def test_weights_shape(weight):
    w = tiny_world(T=8)
    p = make_planner(w, flat_forecasts(w), weight=weight)
    assert p._weights(0).shape == (HORIZON,)
