"""Closed loop (I30) and control-plane faults (I33): the MCP view is the world as it happened."""

import numpy as np
from test_mcp_server import AGENT, S, T, act, forecasts
from test_world import tiny_world

from yovahti.mcp_server.network import Network
from yovahti.world.faults import Faults

LIGHT = [100.0, 5000.0, 100.0, 100.0]       # sector 0 looks safe to sleep at P90


def make(now=10, mid_util=5.0, low_util=5.0, **kw):
    w = tiny_world(mid_util=mid_util, low_util=low_util, T=T, S=S)
    return Network(w, forecasts(LIGHT), now=now, **kw)


def kpi(net, cell, n=1):
    return net.get_cell_kpis([cell], n)["cells"][cell]


def test_untouched_network_shows_measured_traffic():
    net = make()
    s = net.cells["s0-1/low"][0]
    got = net.get_cell_kpis(["s0-1/low"], 4)["cells"]["s0-1/low"]["dl_mb"]
    want = [round(float(net.w.vol["LTE_700"][t, s] + net.w.vol["LTE_800"][t, s]), 1)
            for t in range(6, 10)]
    assert got == want


def test_sleeping_moves_traffic_onto_the_coverage_layer():
    net = make()
    before = kpi(net, "s0-1/low")["dl_mb"][0]
    assert act(net, "s0-1/mid")["status"] == "applied"
    net.advance(2)
    mid, low = kpi(net, "s0-1/mid"), kpi(net, "s0-1/low")
    assert mid["state"] == ["asleep"] and mid["dl_mb"] == [0.0]
    assert low["dl_mb"][0] > before
    rep = net.get_energy_report("all", 2)
    assert rep["kwh_saved"] > 0 and rep["congested_sector_qh"] == 0


def test_watchdog_wakes_raise_an_alarm_and_mark_the_change():
    # the forecast says light, the real traffic is heavy: the arbiter allows, the world objects
    net = make(mid_util=60.0, low_util=25.0)
    cid = act(net, "s0-1/mid")["change_id"]
    net.advance(3)
    alarms = net.get_alarms("all", 8)["alarms"]
    assert any(a["source"] == "watchdog" for a in alarms)
    st = net.get_change_status(cid)
    assert st["watchdog_overrides"] >= 1
    assert any(r["outcome"] == "watchdog_override" for r in st["receipts"])
    assert net.get_energy_report("all", 3)["watchdog_wakes"] >= 1


def test_actuation_delay_shows_scheduled_vs_actual():
    net = make(faults=Faults(actuation_delay=2))
    cid = act(net, "s0-1/mid", n=8)["change_id"]
    net.advance(4)
    k = kpi(net, "s0-1/mid", 4)
    assert k["state"] == ["awake", "awake", "asleep", "asleep"]
    assert k["scheduled"] == ["asleep"] * 4
    obs = net.get_change_status(cid)["observed"][0]
    assert obs == {"cell": "s0-1/mid", "elapsed_qh": 4, "complied_qh": 2}


def test_stuck_radio_never_complies():
    net = make(faults=Faults(stuck=frozenset({0})))
    cid = act(net, "s0-1/mid", n=8)["change_id"]
    net.advance(3)
    assert kpi(net, "s0-1/mid", 3)["state"] == ["awake"] * 3
    assert net.get_change_status(cid)["observed"][0]["complied_qh"] == 0


def test_lost_ack_is_unknown_then_resolves_to_failed():
    net = make(faults=Faults(ack_loss=1.0, ack_applied=0.0))
    r = act(net, "s0-1/mid")
    assert r["status"] == "unknown"
    again = net.apply_change(AGENT, r["change_id"])
    assert again["status"] == "unknown" and "applying again" in again["reasons"][0]
    net.advance(2)
    assert net.get_change_status(r["change_id"])["status"] == "failed"
    assert kpi(net, "s0-1/mid", 2)["state"] == ["awake", "awake"]


def test_lost_ack_can_hide_a_change_that_happened():
    net = make(faults=Faults(ack_loss=1.0, ack_applied=1.0))
    r = act(net, "s0-1/mid")
    net.advance(1)
    assert net.get_change_status(r["change_id"])["status"] == "unknown"
    assert kpi(net, "s0-1/mid")["state"] == ["asleep"]          # the KPIs already tell
    net.advance(1)
    assert net.get_change_status(r["change_id"])["status"] == "applied"


def test_unknown_change_can_be_rolled_back():
    net = make(faults=Faults(ack_loss=1.0, ack_applied=1.0))
    r = act(net, "s0-1/mid", n=8)
    assert net.rollback(AGENT, r["change_id"])["status"] == "rolled_back"
    net.advance(2)
    assert kpi(net, "s0-1/mid", 2)["state"] == ["awake", "awake"]


def test_kpi_lag_and_dropout_are_visible():
    lag = make(now=20, faults=Faults(kpi_lag=3)).get_cell_kpis(["s0-1/mid"], 2)
    net = make(now=20)
    assert lag["data_until"] == net.time(16)
    gone = make(now=20, faults=Faults(kpi_dropout=1.0)).get_cell_kpis(["s0-1/mid"], 2)
    assert gone["cells"]["s0-1/mid"]["load_pct"] == [None, None] and "null" in gone["note"]


def test_clock_going_back_rebuilds_the_world():
    net = make()
    act(net, "s0-1/mid")
    net.advance(4)
    net.now = 5
    k = net.get_cell_kpis(["s0-1/mid"], 2)
    assert k["data_until"] == net.time(4) and np.all(net.sim.mid_s[:5] == 0)
