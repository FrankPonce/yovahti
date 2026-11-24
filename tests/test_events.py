"""Event surges: consistent traffic, invisible to forecasts, and costly only if slept through."""

import numpy as np
from test_mcp_server import AGENT, make

from yovahti.agents.evaluate import apply_plan_alone, compare_night
from yovahti.mcp_server.network import Network
from yovahti.world.data import BANDWIDTH, EFFICIENCY
from yovahti.world.events import Event, inject, surge_mb
from yovahti.world.sim import WorldConfig


def test_inject_keeps_vol_and_util_consistent_and_copies():
    net = make()
    ev = Event("match", (0, 2), 20, 28)
    w = inject(net.w, [ev])
    add = surge_mb(net.w, ev, WorldConfig())
    for c, mb in add.items():
        dv = w.vol[c][20, [0, 2]] - net.w.vol[c][20, [0, 2]]
        du = w.util[c][20, [0, 2]] - net.w.util[c][20, [0, 2]]
        np.testing.assert_allclose(dv, mb)
        np.testing.assert_allclose(du, mb / (EFFICIENCY[c] * BANDWIDTH[c]))
    assert (w.vol["NR_3500"][19] == net.w.vol["NR_3500"][19]).all()     # outside the window
    assert net.w.vol["NR_3500"][20, 0] != w.vol["NR_3500"][20, 0]       # original untouched


def test_sleeping_through_the_event_congests_and_keeping_awake_does_not():
    base = make(now=16)
    ev = Event("match", (0,), 18, 26)
    w = inject(base.w, [ev])
    alone = Network(w, base.f, now=16)
    apply_plan_alone(alone, "all", horizon=16)
    aware = Network(w, base.f, now=16)
    plan = aware.optimise_plan("all", 16)
    keep = [{k: a[k] for k in ("cell", "action", "from_qh", "quarter_hours")}
            for a in plan["actions"] if not a["cell"].startswith("s0-1/")]
    ch = aware.propose_change(AGENT, keep[:4], "skip event sector")
    assert aware.apply_change(AGENT, ch["change_id"])["status"] == "applied"
    rows = compare_night({"alone": alone, "aware": aware}, "all", 16, 40)["rows"]
    assert rows["alone"]["congested_qh_per_sector_day"] > 0
    assert rows["aware"]["congested_qh_per_sector_day"] == 0
    assert rows["aware"]["kwh_saved_pct"] > 0


def test_ideal_reader_cuts_only_the_event_window():
    from yovahti.agents.evaluate import _cut
    acts = [{"cell": "s1-1/mid", "action": "sleep", "from_qh": 0, "quarter_hours": 32},
            {"cell": "s2-1/mid", "action": "sleep", "from_qh": 0, "quarter_hours": 32}]
    out = _cut(acts, {"s1-1": (2, 10)})
    assert [(a["cell"], a["from_qh"], a["quarter_hours"]) for a in out] == [
        ("s1-1/mid", 0, 2), ("s1-1/mid", 10, 22), ("s2-1/mid", 0, 32)]
