"""Arbiter invariants I4, I7, I8, I9 (S8): unit tests, then Hypothesis property tests."""

import copy

import numpy as np
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from test_mcp_server import AGENT, S, T, act, forecasts
from test_world import tiny_world

from yovahti.arbiter.core import Arbiter
from yovahti.mcp_server.network import Network, verify_receipt
from yovahti.trust.admission import AgentIdentity
from yovahti.trust.signing import new_key, public_part

LIGHT = [100.0, 5000.0, 100.0, 100.0]       # sector 1 is too busy to sleep at P90
COVER = AgentIdentity("coverage-agent", may_sleep=False, role="coverage")


def make(now=10, mid_util=5.0, low_util=5.0, **kw):
    w = tiny_world(mid_util=mid_util, low_util=low_util, T=T, S=S)
    return Network(w, forecasts(LIGHT), now=now, **kw)


def reasons(r):
    return " | ".join(r.get("reasons", []))


# ------------------------------------------------------------------ I4 dwell and toggles
def test_i4_sleep_shorter_than_dwell_is_refused():
    r = act(make(), "s0-1/mid", n=2)
    assert r["status"] == "refused" and "I4 dwell" in reasons(r)


def test_i4_ping_pong_is_refused_but_a_proper_gap_is_fine():
    net = make()
    assert act(net, "s0-1/mid", start=0, n=8)["status"] == "applied"
    r = act(net, "s0-1/mid", start=10, n=8)                # awake only 2 QH in between
    assert r["status"] == "refused" and "ping-pong" in reasons(r)
    assert act(net, "s0-1/mid", start=12, n=8)["status"] == "applied"


def test_i4_extending_a_sleep_is_not_ping_pong():
    net = make()
    act(net, "s0-1/mid", start=0, n=8)
    assert act(net, "s0-1/mid", start=8, n=4)["status"] == "applied"


def test_i4_toggle_cap_per_day():
    net = make(arbiter=Arbiter(min_dwell=1, max_toggles_per_day=4))
    assert act(net, "s0-1/mid", start=0, n=2)["status"] == "applied"     # 2 switches
    assert act(net, "s0-1/mid", start=4, n=2)["status"] == "applied"     # 4
    r = act(net, "s0-1/mid", start=8, n=2)                               # 6 > 4
    assert r["status"] == "refused" and "I4 toggles" in reasons(r)


def test_i4_never_blocks_a_wake():
    net = make()
    act(net, "s0-1/mid", start=0, n=8)
    assert act(net, "s0-1/mid", action="wake", start=1, n=1)["status"] == "applied"


# ------------------------------------------------------------------ I7 signed receipts
def test_i7_receipts_are_signed_and_tamper_evident():
    net = make()
    rec = act(net, "s0-1/mid")["receipt"]
    assert verify_receipt(rec, net.receipt_jwks())["ok"]
    bad = copy.deepcopy(rec)
    bad["outcome"] = "refused"
    assert not verify_receipt(bad, net.receipt_jwks())["ok"]
    other = {"keys": [public_part(new_key())]}
    assert not verify_receipt(rec, other)["ok"]


def test_i7_rollback_only_undoes_its_own_cells():
    net = make()
    a = act(net, "s0-1/mid")["change_id"]
    act(net, "s2-1/mid")
    net.rollback(AGENT, a)
    s0, s2 = net.cells["s0-1/mid"][0], net.cells["s2-1/mid"][0]
    assert (net.mid_state[10:18, s0] == 0).all() and (net.mid_state[10:18, s2] == 1).all()


# ------------------------------------------------------------------ I8 approval
def big(net, agent=AGENT):
    cells = ["s0-1/mid", "s2-1/mid", "s3-1/mid"]
    return net.propose_change(agent, [{"cell": c, "action": "sleep", "from_qh": 0,
                                       "quarter_hours": 8} for c in cells], "three cells")


def test_i8_tier_two_waits_for_a_human_then_applies():
    net = make(arbiter=Arbiter(tiers=(2, 20)))
    cid = big(net)["change_id"]
    r = net.apply_change(AGENT, cid)
    assert r["status"] == "awaiting_approval" and "I8 approval" in reasons(r)
    assert (net.mid_state == 0).all()                      # nothing happened yet
    net.approve(cid, "operator:night-shift")
    assert net.apply_change(AGENT, cid)["status"] == "applied"
    outcomes = [x["outcome"] for x in net.get_change_status(cid)["receipts"]]
    assert outcomes == ["awaiting_approval", "approved", "applied"]


def test_i8_simulated_operator_is_recorded_as_such():
    net = make(arbiter=Arbiter(tiers=(2, 20)), approver=lambda ch, tier: "sim-operator")
    cid = big(net)["change_id"]
    assert net.apply_change(AGENT, cid)["status"] == "applied"
    assert net.approvals[cid]["note"] == "simulated operator policy"


# ------------------------------------------------------------------ I9 conflicts
def test_i9_coverage_hold_beats_energy_sleep():
    net = make()
    energy = act(net, "s0-1/mid", n=8)["change_id"]
    assert act(net, "s0-1/mid", action="wake", n=8, agent=COVER)["status"] == "applied"
    assert (net.mid_state[10:18, 0] == 0).all()
    outcomes = [x["outcome"] for x in net.get_change_status(energy)["receipts"]]
    assert "overridden" in outcomes
    r = act(net, "s0-1/nr3500", n=4)
    assert r["status"] == "refused" and "I9 conflict" in reasons(r)


def test_i9_no_sleep_during_a_watchdog_hold():
    net = make(mid_util=60.0, low_util=25.0)              # forecast light, world heavy
    act(net, "s0-1/mid", n=8)
    net.advance(2)                                         # watchdog fires
    r = act(net, "s0-1/nr3500", n=4)
    assert r["status"] == "refused" and "watchdog holds" in reasons(r)


# ------------------------------------------------------------------ properties
CELLS = ["s0-1/mid", "s0-1/nr3500", "s2-1/mid", "s2-1/nr3500", "s3-1/mid", "s3-1/nr3500",
         "s1-1/mid", "s0-1/low"]
op = st.one_of(
    st.tuples(st.just("act"), st.sampled_from(CELLS), st.sampled_from(["sleep", "wake"]),
              st.integers(0, 12), st.integers(1, 12), st.booleans()),
    st.tuples(st.just("advance"), st.integers(1, 6)),
    st.tuples(st.just("rollback"), st.integers(0, 20)),
    st.tuples(st.just("approve"), st.integers(0, 20)),
)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ops=st.lists(op, min_size=1, max_size=25), heavy=st.booleans())
def test_invariants_hold_for_any_sequence(ops, heavy):
    net = make(mid_util=60.0 if heavy else 5.0, low_util=25.0 if heavy else 5.0,
               protected={"s3-1/mid"}, arbiter=Arbiter(tiers=(2, 20)))
    jwks = net.receipt_jwks()
    for o in ops:
        if net.now >= T - 40:
            break
        before = (net.mid_state.copy(), net.nr_state.copy())
        past = (net.sim.mid_s[:net.now].copy(), net.sim.nr_s[:net.now].copy())
        if o[0] == "act":
            _, cell, action, start, n, cover = o
            agent = COVER if cover else AGENT
            if cover and action == "sleep":
                agent = AgentIdentity("coverage-agent", may_sleep=False, role="coverage")
            r = act(net, cell, action=action, start=start, n=n, agent=agent)
            if r["status"] in ("refused", "awaiting_approval"):
                # a refusal or a wait changes nothing
                assert (net.mid_state == before[0]).all() and (net.nr_state == before[1]).all()
        elif o[0] == "advance":
            net.advance(o[1])
        elif o[0] in ("rollback", "approve") and net.changes:
            ch = list(net.changes.values())[o[1] % len(net.changes)]
            if o[0] == "rollback":
                net.rollback(AGENT, ch.change_id)
            elif ch.status == "awaiting_approval":
                net.approve(ch.change_id, "prop-operator")
        net._sync()
        # the past never changes
        n0 = len(past[0])
        assert (net.sim.mid_s[:n0] == past[0]).all() and (net.sim.nr_s[:n0] == past[1]).all()
        fut = slice(net.now, None)
        # I2: protected cells are never scheduled asleep; I5: coverage cells have no state
        assert (net.mid_state[fut, 3] == 0).all()
        # I9: no capacity radio is scheduled asleep inside an active coverage hold
        for h in net.holds:
            lo, hi = max(h["from_t"], net.now), h["until_t"]
            if hi > lo:
                assert (net.mid_state[lo:hi, h["sector"]] == 0).all()
                assert (net.nr_state[lo:hi, h["sector"]] == 0).all()
        # I1: the busy sector never sleeps (its P90 does not fit on the low band)
        assert (net.mid_state[:, 1] == 0).all()
        # I7: every receipt verifies; I8: nothing above tier 1 applied without approval
        for ch in net.changes.values():
            for rec in ch.receipts:
                assert verify_receipt(rec, jwks)["ok"]
            if ch.status in ("applied", "unknown", "rolled_back") and len(
                    {a["cell"] for a in ch.actions}) > 2:
                assert ch.change_id in net.approvals
        # watchdog alarms only come from real congestion
        assert np.all(net.sim.cong[net.sim.woken])


def test_i8_salami_split_does_not_dodge_approval():
    net = make(arbiter=Arbiter(tiers=(2, 20)))
    first = net.propose_change(AGENT, [{"cell": c, "action": "sleep", "from_qh": 0,
                                        "quarter_hours": 8} for c in ("s0-1/mid", "s2-1/mid")],
                               "part 1")
    assert net.apply_change(AGENT, first["change_id"])["status"] == "applied"
    second = net.propose_change(AGENT, [{"cell": "s3-1/mid", "action": "sleep", "from_qh": 0,
                                         "quarter_hours": 8}], "part 2")
    assert second["approval_tier"] == 2
    r = net.apply_change(AGENT, second["change_id"])
    assert r["status"] == "awaiting_approval"
    net.advance(9)                                         # outside the window: fresh count
    third = net.propose_change(AGENT, [{"cell": "s3-1/nr3500", "action": "sleep",
                                        "from_qh": 0, "quarter_hours": 8}], "later")
    assert third["approval_tier"] == 1
