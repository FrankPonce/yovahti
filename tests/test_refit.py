"""Periodic re-fitting stays out-of-sample: each segment equals a model fitted before it."""

import numpy as np
from test_world import tiny_world

from yovahti.forecast.quantile import QUANTILES, WEEK, Forecaster, refit_predict_log


def noisy_world(T, S=3, seed=0):  # noqa: N803
    w = tiny_world(T=T, S=S)
    rng = np.random.default_rng(seed)
    for c in w.vol:
        w.vol[c] = w.vol[c] * rng.lognormal(0, 0.5, (T, S))
    return w


def test_refit_segments_match_models_fitted_before_them():
    w = noisy_world(T=2 * WEEK + 300)
    fit_end, every = WEEK + 100, 96
    issues = np.arange(fit_end, fit_end + 3 * every, 8)
    out = refit_predict_log(w, "mid", fit_end, issues, every=every, rounds=5)
    for k in range(3):
        r = fit_end + k * every
        sel = (issues >= r) & (issues < r + every)
        ref = Forecaster.fit(w, "mid", r, rounds=5).predict_log(w, issues[sel])
        for q in QUANTILES:
            np.testing.assert_allclose(out[q][sel], ref[q])


def test_refit_ignores_data_after_each_segment_start():
    w = noisy_world(T=2 * WEEK + 300)
    fit_end, every = WEEK + 100, 96
    issues = np.arange(fit_end + every, fit_end + 2 * every, 8)   # second segment only
    a = refit_predict_log(w, "mid", fit_end, issues, every=every, rounds=5)
    late = fit_end + 2 * every + 40                                # beyond any target used
    for c in w.vol:
        w.vol[c][late:] *= 50.0
    b = refit_predict_log(w, "mid", fit_end, issues, every=every, rounds=5)
    for q in QUANTILES:
        np.testing.assert_allclose(a[q], b[q])
