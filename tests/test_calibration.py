"""Conformal calibration hits its target share per group and never peeks at the future."""

import numpy as np
import pytest

from yovahti.forecast import calibration as cal
from yovahti.forecast.quantile import HORIZON, QUANTILES


def fake(n=200, S=5, night_bias=0.0, seed=0):  # noqa: N803
    rng = np.random.default_rng(seed)
    issues = np.arange(n) * 4
    hour = ((issues[:, None] + np.arange(HORIZON)[None, :]) // 4) % 24
    noise = rng.normal(0, 0.3, (n, HORIZON, S))
    ylog = 5 + noise + night_bias * (hour < 6)[..., None]
    logp = {q: np.full((n, HORIZON, S), 5.0) for q in QUANTILES}   # uncalibrated: all median
    return issues, hour, ylog, logp


def share_below(lp, ylog, q):
    return (ylog <= lp[q]).mean()


def test_global_offsets_hit_target_on_calibration_data():
    _, _, ylog, logp = fake()
    lp = cal.apply_global(logp, cal.global_offsets(logp, ylog))
    for q in QUANTILES:
        assert share_below(lp, ylog, q) == pytest.approx(q, abs=0.02)


def test_mondrian_fixes_a_night_only_bias_that_global_misses():
    _, hour, ylog, logp = fake(night_bias=0.8)
    hb = np.broadcast_to(hour[..., None], ylog.shape)
    g = cal.apply_global(logp, cal.global_offsets(logp, ylog))
    m = cal.apply_mondrian(logp, cal.mondrian_offsets(logp, ylog, hour), hour)
    night = hb < 6
    assert (ylog > g[0.9])[night].mean() > 0.3                    # global under-covers nights
    assert (ylog > m[0.9])[night].mean() == pytest.approx(0.1, abs=0.03)


def test_rolling_uses_only_realised_past():
    issues, hour, ylog, logp = fake(n=120)
    ylog_future_poisoned = ylog.copy()
    evm = issues >= 60 * 4
    first_eval = issues[evm].min()
    # poison every outcome that is NOT yet known at the first evaluated issue
    unknown = issues + HORIZON > first_eval
    ylog_future_poisoned[unknown] += 100.0
    a = cal.rolling_mondrian(logp, ylog, hour, issues, evm, start_floor=0)
    b = cal.rolling_mondrian(logp, ylog_future_poisoned, hour, issues, evm, start_floor=0)
    day = issues // 96
    first_day = (day == day[evm].min()) & evm
    for q in QUANTILES:
        np.testing.assert_allclose(a[q][first_day], b[q][first_day])


def test_to_mb_keeps_quantiles_ordered():
    lp = {0.1: np.full((1, HORIZON, 1), 3.0), 0.5: np.full((1, HORIZON, 1), 2.0),
          0.9: np.full((1, HORIZON, 1), 1.0)}
    mb = cal.to_mb(lp)
    assert (mb[0.1] <= mb[0.5]).all() and (mb[0.5] <= mb[0.9]).all()


def test_absent_sectors_do_not_pin_offsets_at_zero():
    _, _, ylog, logp = fake(S=10)
    ylog = ylog.copy()
    ylog[..., 4:] = 0.0                       # 6 of 10 sectors don't have the carrier
    for q in logp:
        logp[q] = logp[q].copy()
        logp[q][..., 4:] = 0.0                # forecast as zero, observed as zero
    present = np.arange(10) < 4
    pinned = cal.global_offsets(logp, ylog)
    fixed = cal.global_offsets(logp, ylog, present)
    assert abs(pinned[0.5]).max() < 1e-9      # the bug: zeros pin the median shift at zero
    bad = cal.apply_global(logp, pinned)
    good = cal.apply_global(logp, fixed)
    miss = lambda lp: (ylog[..., present] > lp[0.9][..., present]).mean()  # noqa: E731
    assert miss(good) == pytest.approx(0.1, abs=0.02)
    assert miss(bad) > 0.2                     # unmasked P90 under-covers real sectors


def test_trend_catches_up_with_steady_growth():
    n = 600                                         # 25 days of issues every 4 QH
    issues, hour, ylog, logp = fake(n=n)
    ylog = ylog + 0.01 * (issues / 96)[:, None, None]          # +1 % a day, uncaptured
    evm = issues >= 20 * 96
    plain = cal.rolling_mondrian(logp, ylog, hour, issues, evm, start_floor=0)
    trend = cal.rolling_mondrian(logp, ylog, hour, issues, evm, start_floor=0, trend=True)
    below = lambda lp: (ylog[evm] < lp[0.5][evm]).mean()       # noqa: E731
    assert below(plain) < 0.45                      # 14-day window lags growth
    assert below(trend) == pytest.approx(0.5, abs=0.03)


def test_trend_and_short_median_use_only_realised_past():
    issues, hour, ylog, logp = fake(n=300)
    evm = issues >= 200 * 4
    first_eval = issues[evm].min()
    poisoned = ylog.copy()
    poisoned[issues + HORIZON > first_eval] += 100.0
    kw = dict(start_floor=0, trend=True, median_window_days=3)
    a = cal.rolling_mondrian(logp, ylog, hour, issues, evm, **kw)
    b = cal.rolling_mondrian(logp, poisoned, hour, issues, evm, **kw)
    first_day = (issues // 96 == (issues[evm] // 96).min()) & evm
    for q in QUANTILES:
        np.testing.assert_allclose(a[q][first_day], b[q][first_day])
