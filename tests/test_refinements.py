"""Planner options (adaptive margin, throughput floor), the guarantee monitor, the demo network."""

import numpy as np
from test_mcp_server import forecasts
from test_world import tiny_world

from yovahti.forecast.bound import Scores
from yovahti.forecast.monitor import daily_checks
from yovahti.mcp_server.demo import BUSY, demo_network
from yovahti.plan.dp import DPPlanner, PlannerConfig
from yovahti.trust.admission import AgentIdentity
from yovahti.world.sim import WorldConfig


def _scores(scale_from_day=None, factor=1.0, days=14, seed=0):
    rng = np.random.default_rng(seed)
    n = days * 96 * 50
    t = np.repeat(np.arange(days * 96), 50)
    s = np.tile(np.arange(50), days * 96)
    r = rng.uniform(0, 1 / 0.9, n)                     # P(r > 1) = 0.10 exactly in law
    if scale_from_day is not None:
        r = np.where(t // 96 >= scale_from_day, r * factor, r)
    hour = (t % 96) // 4
    return Scores(t, s, r, (hour >= 22) | (hour < 6))


def test_monitor_quiet_on_clean_scores_and_alarms_on_drift():
    clean = daily_checks(_scores(), current_margin=1.0, alpha=0.10)
    assert clean and not any(c.alarm for c in clean)
    drift = daily_checks(_scores(scale_from_day=7, factor=1.2), current_margin=1.0, alpha=0.10)
    assert drift[-1].alarm and drift[-1].suggested_margin > 1.05


def _planner(**kw):
    w = tiny_world(T=200, S=4)
    fc = forecasts([100.0, 100.0, 100.0, 100.0])
    return w, DPPlanner(w, fc, PlannerConfig(**kw), WorldConfig(), **{
        k: v for k, v in kw.items() if k in ("users",)})


def test_options_off_change_nothing():
    w = tiny_world(T=200, S=4)
    fc = forecasts([100.0] * 4)
    a = DPPlanner(w, fc, PlannerConfig(), WorldConfig()).costs(0)
    b = DPPlanner(w, fc, PlannerConfig(adaptive_step=1.0, min_user_mbps=0.0), WorldConfig()
                  ).costs(0)
    assert np.array_equal(a, b)


def test_throughput_floor_removes_sleep_states_where_users_would_get_too_little():
    w = tiny_world(T=200, S=4)
    fc = forecasts([100.0] * 4)
    many = {c: np.full((w.T, w.S), 500.0) for c in ("LTE_700", "LTE_800", "LTE_1800",
                                                      "NR_2100", "NR_3500")}
    free = DPPlanner(w, fc, PlannerConfig(), WorldConfig()).costs(0)
    floor = DPPlanner(w, fc, PlannerConfig(min_user_mbps=50.0), WorldConfig(), users=many
                      ).costs(0)
    assert np.isfinite(free[..., 2]).any()             # mid could sleep without the floor
    assert not np.isfinite(floor[..., 1:]).any()        # with 500 users each, no sleep state
    assert np.isfinite(floor[..., 0]).all()             # staying awake is always allowed


def test_demo_network_refuses_the_busy_sector_and_applies_the_plan():
    net = demo_network()
    agent = AgentIdentity("energy-agent")
    busy = [c for c, (s, layer) in net.cells.items() if s == BUSY and layer != "low"]
    p = net.propose_change(agent, [{"cell": c, "action": "sleep", "from_qh": 0,
                                    "quarter_hours": 8} for c in busy], "try busy")
    res = net.apply_change(agent, p["change_id"])
    assert res["status"] == "refused" and any("I1" in r for r in res["reasons"])
    plan = net.optimise_plan("C01", 32)
    assert plan["actions"] and plan["expected_kwh_saved"] > 0
