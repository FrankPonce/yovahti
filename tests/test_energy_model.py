"""The radio-unit energy model recovers known slopes and fingerprints; absent carriers work."""

import numpy as np
import pandas as pd
import pytest

from yovahti.energy.model import evaluate, fit


def synthetic(units=6, steps=400, seed=0, absent_nr_on=None):
    rng = np.random.default_rng(seed)
    rows = []
    t0 = pd.Timestamp("2025-09-01", tz="UTC")
    for u in range(units):
        idle = 30 + 5 * u
        for k in range(steps):
            lte = rng.uniform(0, 40)
            nr = rng.uniform(0, 20)
            if absent_nr_on is not None and u == absent_nr_on:
                nr_val = np.nan
                e = idle + 0.8 * lte + rng.normal(0, 0.5)
            else:
                nr_val = nr
                e = idle + 0.8 * lte + 1.2 * nr + rng.normal(0, 0.5)
            rows.append({"site": f"S{u}", "sector": 1, "time": t0 + pd.Timedelta(minutes=15 * k),
                         "ru_energy_wh": e, "u_LTE_1800": lte, "u_NR_2100": nr_val})
    df = pd.DataFrame(rows)
    df["unit_id"] = df["site"] + "/" + df["sector"].astype(str)
    return df


def test_recovers_slopes_and_fingerprints():
    m = fit("mid", synthetic())
    assert m.slopes["LTE_1800"] == pytest.approx(0.8, abs=0.02)
    assert m.slopes["NR_2100"] == pytest.approx(1.2, abs=0.02)
    for u in range(6):
        assert m.idle[f"S{u}/1"] == pytest.approx(30 + 5 * u, abs=0.3)
    ev = evaluate(m, synthetic(seed=1))
    assert ev["r2"] > 0.99 and abs(ev["bias_wh"]) < 0.2


def test_absent_carrier_counts_as_zero_not_dropped():
    m = fit("mid", synthetic(absent_nr_on=2))
    assert m.idle["S2/1"] == pytest.approx(40, abs=0.3)  # the unit without NR is still fitted
    assert m.slopes["NR_2100"] == pytest.approx(1.2, abs=0.03)


def test_sleep_energy_uses_spec_ratios():
    m = fit("mid", synthetic())
    idle = m.idle["S0/1"]
    assert m.sleep_energy("S0/1", "deep_sleep", 1) == pytest.approx(idle * 1 / 50)
    assert m.sleep_energy("S0/1", "deep_sleep", 2) == pytest.approx(idle * 1 / 5)
    assert m.sleep_energy("unknown/9") == pytest.approx(m.idle_default / 50)


def test_json_roundtrip(tmp_path):
    m = fit("mid", synthetic())
    m.to_json(tmp_path / "mid.json")
    m2 = type(m).from_json(tmp_path / "mid.json")
    assert m2.slopes == m.slopes and m2.idle == m.idle
