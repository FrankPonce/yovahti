"""TR 38.864 constants match the spec tables, and the break-even logic is sound."""

import pytest

from yovahti.energy import tr38864 as tr


def test_spec_values_category1_set2():
    assert tr.power("deep_sleep") == 1
    assert tr.power("light_sleep") == 25
    assert tr.power("micro_sleep") == 50
    assert tr.power("active_dl") == 200
    assert tr.power("active_ul") == 90


def test_spec_values_category2_set1():
    assert tr.power("micro_sleep", category=2, ref_set=1) == 5.5
    assert tr.power("active_dl", category=2, ref_set=1) == 32
    deep = tr.sleep_state("deep_sleep", category=2)
    assert deep.transition_ms == 10_000 and deep.transition_energy == 17_000


def test_power_ordering_every_config():
    for cat in (1, 2):
        for s in (1, 2, 3):
            p = [tr.power(x, cat, s) for x in
                 ("deep_sleep", "light_sleep", "micro_sleep", "active_ul", "active_dl")]
            assert p == sorted(p), (cat, s, p)


def test_break_even_deep_sleep_category1():
    deep = tr.sleep_state("deep_sleep")  # P=1, T=50 ms, E=1000
    # versus staying in micro sleep (P=50): 1000 / 49 ~ 20.4 ms < T, so T dominates
    assert deep.min_worthwhile_ms(50) == pytest.approx(50)
    # versus a state barely above deep sleep, sleeping is never worth it
    assert deep.min_worthwhile_ms(1) == float("inf")


def test_deep_sleep_saves_most_of_idle_power():
    assert tr.sleep_saving_fraction("deep_sleep") == pytest.approx(0.98)
    assert tr.sleep_saving_fraction("light_sleep") == pytest.approx(0.5)


def test_micro_sleep_is_not_a_choice():
    with pytest.raises(ValueError):
        tr.sleep_state("active_dl")
