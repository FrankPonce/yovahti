"""Conformal calibration of quantile forecasts in log space.

Three variants (FINDINGS E17):

* ``global``   one shift per quantile and horizon, from a fixed calibration window
* ``mondrian`` one shift per quantile, horizon bucket and **local clock hour of the target**
               (group-conditional / Mondrian conformal; fixes the night-time misses)
* ``rolling``  Mondrian shifts re-estimated every day from the last ``window_days`` of
               *realised* forecasts before the issue (only past outcomes; follows drift)

A shift for quantile q is the q-quantile of (log1p(actual) - log forecast) in a group, so that
a share q of calibration outcomes falls below the shifted forecast.
"""

from __future__ import annotations

import numpy as np

from yovahti.forecast.quantile import HORIZON, QUANTILES

H_BUCKETS = 4  # horizon buckets of 10 quarter-hours


def _hbucket() -> np.ndarray:
    return np.minimum(np.arange(HORIZON) * H_BUCKETS // HORIZON, H_BUCKETS - 1)


def _shift(resid: np.ndarray, q: float) -> float:
    return float(np.quantile(resid, q)) if resid.size else 0.0


def _sel(a: np.ndarray, sectors: np.ndarray | None) -> np.ndarray:
    return a if sectors is None else a[..., sectors]


def global_offsets(logp: dict, ylog: np.ndarray,
                   sectors: np.ndarray | None = None) -> dict[float, np.ndarray]:
    """{q: [HORIZON]} from calibration arrays [n, H, S].

    ``sectors`` restricts calibration to sectors where the layer exists (G27): absent
    carriers forecast as zero and observed as zero would otherwise pin every shift at zero.
    """
    y = _sel(ylog, sectors)
    return {q: np.quantile((y - _sel(logp[q], sectors)).transpose(1, 0, 2).reshape(HORIZON, -1),
                           q, axis=1) for q in QUANTILES}


def mondrian_offsets(logp: dict, ylog: np.ndarray, hour: np.ndarray,
                     sectors: np.ndarray | None = None) -> dict[float, np.ndarray]:
    """{q: [24, H_BUCKETS]}; ``hour`` is [n, H] local clock hour of each target."""
    hb = np.broadcast_to(_hbucket()[None, :], hour.shape)
    out = {}
    for q in QUANTILES:
        r = _sel(ylog, sectors) - _sel(logp[q], sectors)
        tab = np.zeros((24, H_BUCKETS))
        for hr in range(24):
            for b in range(H_BUCKETS):
                m = (hour == hr) & (hb == b)
                tab[hr, b] = _shift(r[m], q)
        out[q] = tab
    return out


def apply_global(logp: dict, off: dict) -> dict:
    return {q: logp[q] + off[q][None, :, None] for q in QUANTILES}


def apply_mondrian(logp: dict, off: dict, hour: np.ndarray) -> dict:
    hb = np.broadcast_to(_hbucket()[None, :], hour.shape)
    return {q: logp[q] + off[q][hour, hb][:, :, None] for q in QUANTILES}


def rolling_mondrian(logp: dict, ylog: np.ndarray, hour: np.ndarray, issues: np.ndarray,
                     eval_mask: np.ndarray, start_floor: int, window_days: int = 14,
                     min_issues: int = 48, sectors: np.ndarray | None = None) -> dict:
    """Calibrate each evaluated issue with Mondrian shifts from realised forecasts only.

    For an issue at index i, calibration uses issues j with ``start_floor <= j`` (no in-sample
    residuals), ``j >= i - window_days*96`` and ``j + HORIZON <= i`` (outcome already known).
    Shifts are recomputed once per day. Issues before enough history use what exists.
    """
    out = {q: logp[q].copy() for q in QUANTILES}
    day = issues // 96
    for d in np.unique(day[eval_mask]):
        first = issues[(day == d) & eval_mask].min()
        cal = (issues >= max(start_floor, first - window_days * 96)) & (issues + HORIZON <= first)
        if cal.sum() < min_issues:
            cal = (issues >= start_floor) & (issues + HORIZON <= first)
        sel = (day == d) & eval_mask
        off = mondrian_offsets({q: logp[q][cal] for q in QUANTILES}, ylog[cal], hour[cal],
                               sectors)
        hb = np.broadcast_to(_hbucket()[None, :], hour[sel].shape)
        for q in QUANTILES:
            out[q][sel] = logp[q][sel] + off[q][hour[sel], hb][:, :, None]
    return out


def to_mb(logp: dict) -> dict[float, np.ndarray]:
    out = {q: np.expm1(logp[q]).clip(min=0).astype(np.float32) for q in QUANTILES}
    out[0.5] = np.maximum(out[0.5], out[0.1])
    out[0.9] = np.maximum(out[0.9], out[0.5])
    return out
