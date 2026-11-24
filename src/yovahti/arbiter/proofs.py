"""Z3 proofs for the linear part of the arbiter (S8, stretch tier 2).

I1 refuses a sleep state unless the receiving layer stays under its limit at the P90
forecast (`plan.dp.DPPlanner.costs`). The world (`world.sim.Stepper`) flags congestion and
unserved traffic with its own formulas. These proofs connect the two, for *every* traffic
value, capacity and configuration, not just the ones in the data:

* ``no_congestion``: if the arbiter's check passes for a state and the real traffic of every
  layer is at most its P90 forecast, the world cannot flag that sector congested.
* ``no_unserved``: under the same conditions, no traffic is pushed past a layer's ceiling,
  provided the configured limit is below the ceiling (rho_max <= ceiling).
* ``needs_coverage``: drop the "real traffic <= P90" premise and Z3 finds a counterexample;
  so the guarantee is exactly as good as the forecast's coverage (80-84 % measured, E17),
  which is what the conformal bound (`forecast.bound`) turns into a number.

The formulas below are transcribed from the two modules; `tests/test_proofs.py` also checks
them numerically against the real code on random inputs, so a drift in either is caught.
"""

from __future__ import annotations

from dataclasses import dataclass

import z3

STATES = {1: "NR 3500 asleep", 2: "mid asleep", 3: "both asleep"}


@dataclass
class Proof:
    name: str
    state: int
    proved: bool
    counterexample: dict | None = None

    def __str__(self) -> str:
        tag = "proved" if self.proved else f"counterexample {self.counterexample}"
        return f"{self.name} [{STATES[self.state]}]: {tag}"


def _vars():
    r = z3.Reals("low mid nr p_low p_mid p_nr cap_low cap_mid peak rho_low rho_mid "
                 "ceil_low ceil_mid margin")
    v = dict(zip(["low", "mid", "nr", "p_low", "p_mid", "p_nr", "cap_low", "cap_mid", "peak",
                  "rho_low", "rho_mid", "ceil_low", "ceil_mid", "margin"], r, strict=True))
    has_nr = z3.Bool("has_nr")
    base = [v[k] >= 0 for k in ("low", "mid", "nr", "p_low", "p_mid", "p_nr")]
    base += [v["cap_low"] > 0, v["cap_mid"] > 0, v["peak"] >= 1, v["margin"] >= 1,
             v["rho_low"] > 0, v["rho_mid"] > 0,
             z3.Implies(z3.Not(has_nr), z3.And(v["nr"] == 0, v["p_nr"] == 0))]
    return v, has_nr, base


def _arbiter_ok(v, has_nr, state: int):
    """`DPPlanner.costs` feasibility (ok1 / ok2 / ok3), risk = P90 x margin."""
    r_low, r_mid = v["p_low"] * v["margin"], v["p_mid"] * v["margin"]
    r_nr = z3.If(has_nr, v["p_nr"] * v["margin"], 0)
    if state == 1:
        return z3.And(has_nr, (r_mid + r_nr) / v["cap_mid"] * v["peak"] <= v["rho_mid"])
    if state == 2:
        return (r_low + r_mid) / v["cap_low"] * v["peak"] <= v["rho_low"]
    return z3.And(has_nr, (r_low + r_mid + r_nr) / v["cap_low"] * v["peak"] <= v["rho_low"])


def _world(v, state: int):
    """`Stepper.step` re-routing, congestion and unserved traffic for a fixed state."""
    mid_asleep, nr_asleep = state in (2, 3), state in (1, 3)
    to_mid = v["nr"] if (nr_asleep and not mid_asleep) else 0
    mid_mb = v["mid"] + to_mid
    to_low = (mid_mb if mid_asleep else 0) + (v["nr"] if (nr_asleep and mid_asleep) else 0)
    low_mb = v["low"] + to_low
    lu, mu = low_mb / v["cap_low"], (0 if mid_asleep else mid_mb / v["cap_mid"])
    c_low = z3.And(lu * v["peak"] > v["rho_low"], to_low > 0) if not isinstance(to_low, int) \
        else z3.BoolVal(False)
    c_mid = z3.And(mu * v["peak"] > v["rho_mid"], to_mid > 0) if not isinstance(to_mid, int) \
        else z3.BoolVal(False)
    over_low = z3.If(low_mb - z3.If(v["cap_low"] * v["ceil_low"] >= low_mb - to_low,
                                    v["cap_low"] * v["ceil_low"], low_mb - to_low) > 0,
                     low_mb - z3.If(v["cap_low"] * v["ceil_low"] >= low_mb - to_low,
                                    v["cap_low"] * v["ceil_low"], low_mb - to_low), 0)
    over_mid = 0
    if not mid_asleep:
        cap = v["cap_mid"] * v["ceil_mid"]
        floor = z3.If(cap >= mid_mb - to_mid, cap, mid_mb - to_mid)
        over_mid = z3.If(mid_mb - floor > 0, mid_mb - floor, 0)
    return z3.Or(c_low, c_mid), over_low + over_mid


def _prove(name: str, state: int, premises, claim) -> Proof:
    s = z3.Solver()
    s.add(*premises, z3.Not(claim))
    res = s.check()
    if res == z3.unsat:
        return Proof(name, state, True)
    m = s.model()
    cx = {str(d): str(m[d]) for d in m.decls()}
    return Proof(name, state, False, cx)


def prove_all() -> list[Proof]:
    out = []
    for state in STATES:
        v, has_nr, base = _vars()
        covered = [v["low"] <= v["p_low"] * v["margin"], v["mid"] <= v["p_mid"] * v["margin"],
                   v["nr"] <= v["p_nr"] * v["margin"]]
        cong, unserved = _world(v, state)
        ok = _arbiter_ok(v, has_nr, state)
        out.append(_prove("no_congestion", state, base + covered + [ok], z3.Not(cong)))
        out.append(_prove("no_unserved", state,
                          base + covered + [ok, v["rho_low"] <= v["ceil_low"],
                                            v["rho_mid"] <= v["ceil_mid"]],
                          unserved == 0))
        p = _prove("needs_coverage", state, base + [ok], z3.Not(cong))
        out.append(Proof(p.name, state, not p.proved, p.counterexample))  # expect a cx
    return out


if __name__ == "__main__":
    for p in prove_all():
        print(p.name, STATES[p.state], "OK" if p.proved else "FAILED", flush=True)
