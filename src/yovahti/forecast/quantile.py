"""Quantile traffic forecasts per sector and layer, up to 10 hours ahead.

Targets (downlink MB per quarter-hour): ``mid`` (LTE 1800 + NR 2100), ``nr`` (NR 3500) and
``low`` (LTE 700 + 800). One global LightGBM model per target and quantile (P10, P50, P90), on
log1p volume, with horizon as a feature (Tasehinta's set-up).

No hindsight: a forecast issued at quarter-hour ``i`` (before it starts) only uses values up to
``i - 1``. Lags at the *target* time (one day and one week earlier) are allowed only when they
are at or before ``i - 1``; with horizons up to 40 that always holds for one day (96) and a week.
The weekly profile is computed from the training weeks only.

Assumption (FINDINGS G24): the controller knows each layer's demand history even when a radio
slept, as operators can from per-user counters on the coverage cell. Forecasts here are made
from the real, un-slept traffic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd

from yovahti.world.data import WorldData

QUANTILES = (0.1, 0.5, 0.9)
HORIZON = 40
TARGETS = {"mid": ["LTE_1800", "NR_2100"], "nr": ["NR_3500"], "low": ["LTE_700", "LTE_800"]}
FEATURES = ["h", "last", "mean4", "last_dev", "lag1d", "lag7d", "prof", "hour", "dow",
            "sector_level", "day_dev", "week_dev"]
WEEK = 672  # quarter-hours
TZ = "Europe/Bratislava"


def target_series(world: WorldData, target: str) -> np.ndarray:
    """[T,S] log1p(MB) of a target layer."""
    return np.log1p(sum(world.vol[c] for c in TARGETS[target]))


def slot_of_week(times: pd.DatetimeIndex) -> np.ndarray:
    lt = times.tz_convert(TZ)
    return ((lt.day_of_week * 24 + lt.hour) * 4 + lt.minute // 15).to_numpy()


@dataclass
class Forecaster:
    target: str
    profile: np.ndarray = field(repr=False)          # [672, S] mean log1p by local slot
    level: np.ndarray = field(repr=False)            # [S] sector mean log1p
    models: dict[float, lgb.Booster] = field(default_factory=dict, repr=False)
    # log-space shift per quantile and horizon, learned on a calibration window (conformal)
    offsets: dict[float, np.ndarray] = field(default_factory=dict, repr=False)
    _dev: np.ndarray | None = field(default=None, repr=False)  # cache, reset per world
    # F1 (FINDINGS E17): model each sector relative to its own last-7-days mean log level
    level_norm: bool = False
    _cy: np.ndarray | None = field(default=None, repr=False)   # cache: cumsum of y

    def _recent_level(self, y: np.ndarray, issue: np.ndarray, s: np.ndarray) -> np.ndarray:
        """Mean log1p volume over the week before ``issue`` (only past data)."""
        if self._cy is None:
            self._cy = np.vstack([np.zeros((1, y.shape[1])), np.cumsum(y, axis=0)])
        return (self._cy[issue, s] - self._cy[issue - WEEK, s]) / WEEK

    # ---------------------------------------------------------------- features
    def _features(self, y: np.ndarray, slots: np.ndarray, hours: np.ndarray, dows: np.ndarray,
                  issue: np.ndarray, h: np.ndarray, s: np.ndarray) -> np.ndarray:
        tgt = issue + h - 1                     # target index (h = 1 is quarter-hour `issue`)
        last = y[issue - 1, s]
        mean4 = (y[issue - 1, s] + y[issue - 2, s] + y[issue - 3, s] + y[issue - 4, s]) / 4
        last_dev = last - self.profile[slots[issue - 1], s]
        lag1d = y[tgt - 96, s]
        lag7d = y[tgt - WEEK, s]
        prof = self.profile[slots[tgt], s]
        # recent level vs the usual weekly pattern: tracks drift (growth, holidays, seasons)
        dev = y - self.profile[slots][:, :] if self._dev is None else self._dev
        self._dev = dev
        cdev = np.vstack([np.zeros((1, y.shape[1])), np.cumsum(dev, axis=0)])
        day_dev = (cdev[issue, s] - cdev[issue - 96, s]) / 96
        week_dev = (cdev[issue, s] - cdev[issue - WEEK, s]) / WEEK
        if self.level_norm:
            lv = self._recent_level(y, issue, s)
            last, mean4, lag1d, lag7d, prof = (a - lv for a in (last, mean4, lag1d, lag7d, prof))
        return np.column_stack([h, last, mean4, last_dev, lag1d, lag7d, prof, hours[tgt],
                                dows[tgt], self.level[s], day_dev, week_dev]).astype(np.float32)

    @staticmethod
    def _calendar(times: pd.DatetimeIndex):
        lt = times.tz_convert(TZ)
        return slot_of_week(times), lt.hour.to_numpy(), lt.day_of_week.to_numpy()

    # ---------------------------------------------------------------- fit
    @classmethod
    def fit(cls, world: WorldData, target: str, train_end: int, issue_every: int = 8,
            horizons_per_issue: int = 8, seed: int = 0, rounds: int = 300,
            level_norm: bool = False, half_life_days: float | None = None) -> Forecaster:
        """Fit on issue times before ``train_end`` (index into world.times), targets too.

        ``half_life_days`` weights each training row by 0.5 ** (age / half-life), age measured
        from the issue time to ``train_end`` (FINDINGS G28 candidate M1: recent weeks count more).
        """
        y = target_series(world, target)
        slots, hours, dows = cls._calendar(world.times)
        tr = slice(0, train_end)
        prof = np.zeros((WEEK, world.S))
        for k in range(WEEK):
            m = slots[tr] == k
            prof[k] = y[tr][m].mean(axis=0) if m.any() else y[tr].mean(axis=0)
        f = cls(target=target, profile=prof, level=y[tr].mean(axis=0), level_norm=level_norm)
        f._dev = None
        f._cy = None
        rng = np.random.default_rng(seed)
        issues = np.arange(WEEK + 4, train_end - HORIZON, issue_every)
        rows_i, rows_h, rows_s = [], [], []
        for i in issues:
            hs = rng.choice(np.arange(1, HORIZON + 1), horizons_per_issue, replace=False)
            for h in hs:
                rows_i.append(np.full(world.S, i))
                rows_h.append(np.full(world.S, h))
                rows_s.append(np.arange(world.S))
        ii, hh, ss = (np.concatenate(a) for a in (rows_i, rows_h, rows_s))
        x = f._features(y, slots, hours, dows, ii, hh, ss)
        t = y[ii + hh - 1, ss]
        if level_norm:
            t = t - f._recent_level(y, ii, ss)
        params = {"learning_rate": 0.05, "num_leaves": 63, "min_data_in_leaf": 200,
                  "feature_fraction": 0.9, "bagging_fraction": 0.8, "bagging_freq": 1,
                  "verbose": -1, "seed": seed}
        wt = None
        if half_life_days is not None:
            wt = 0.5 ** ((train_end - ii) / (half_life_days * 96))
        for q in QUANTILES:
            ds = lgb.Dataset(x, t, weight=wt, feature_name=FEATURES, free_raw_data=False)
            f.models[q] = lgb.train({**params, "objective": "quantile", "alpha": q}, ds,
                                    num_boost_round=rounds)
        return f

    # ---------------------------------------------------------------- predict
    def predict_issue(self, world: WorldData, issue: int) -> dict[float, np.ndarray]:
        """Forecasts issued before quarter-hour ``issue``: {q: [HORIZON, S] MB}, sorted per q."""
        if self.level_norm:
            out = self.predict_many(world, np.array([issue]))
            return {q: v[0] for q, v in out.items()}
        self._dev = None
        self._cy = None
        y = target_series(world, self.target)
        slots, hours, dows = self._calendar(world.times)
        h = np.repeat(np.arange(1, HORIZON + 1), world.S)
        s = np.tile(np.arange(world.S), HORIZON)
        x = self._features(y, slots, hours, dows, np.full(h.size, issue), h, s)
        out = {q: np.expm1(self.models[q].predict(x)).reshape(HORIZON, world.S).clip(min=0)
               for q in QUANTILES}
        # keep quantiles ordered
        lo, mid, hi = (out[q] for q in QUANTILES)
        mid = np.maximum(mid, lo)
        hi = np.maximum(hi, mid)
        return {QUANTILES[0]: lo, QUANTILES[1]: mid, QUANTILES[2]: hi}

    def predict_log(self, world: WorldData, issues: np.ndarray) -> dict[float, np.ndarray]:
        """Uncalibrated log1p forecasts {q: [n_issues, HORIZON, S]} (absolute level)."""
        self._dev = None
        self._cy = None
        y = target_series(world, self.target)
        slots, hours, dows = self._calendar(world.times)
        n = len(issues)
        ii = np.repeat(issues, HORIZON * world.S)
        hh = np.tile(np.repeat(np.arange(1, HORIZON + 1), world.S), n)
        ss = np.tile(np.arange(world.S), HORIZON * n)
        x = self._features(y, slots, hours, dows, ii, hh, ss)
        add = self._recent_level(y, ii, ss) if self.level_norm else 0.0
        return {q: (self.models[q].predict(x) + add).reshape(n, HORIZON, world.S)
                for q in QUANTILES}

    def predict_many(self, world: WorldData, issues: np.ndarray,
                     calibrated: bool = True) -> dict[float, np.ndarray]:
        """{q: [n_issues, HORIZON, S]} in one batched call (fast)."""
        if self.level_norm:
            logs = self.predict_log(world, issues)
            out = {}
            for q in QUANTILES:
                lp = logs[q]
                if calibrated and q in self.offsets:
                    lp = lp + self.offsets[q][None, :, None]
                out[q] = np.expm1(lp).clip(min=0).astype(np.float32)
            out[0.5] = np.maximum(out[0.5], out[0.1])
            out[0.9] = np.maximum(out[0.9], out[0.5])
            return out
        self._dev = None
        self._cy = None
        y = target_series(world, self.target)
        slots, hours, dows = self._calendar(world.times)
        n = len(issues)
        ii = np.repeat(issues, HORIZON * world.S)
        hh = np.tile(np.repeat(np.arange(1, HORIZON + 1), world.S), n)
        ss = np.tile(np.arange(world.S), HORIZON * n)
        x = self._features(y, slots, hours, dows, ii, hh, ss)
        out = {}
        for q in QUANTILES:
            logp = self.models[q].predict(x).reshape(n, HORIZON, world.S)
            if calibrated and q in self.offsets:
                logp = logp + self.offsets[q][None, :, None]
            out[q] = np.expm1(logp).clip(min=0).astype(np.float32)
        out[0.5] = np.maximum(out[0.5], out[0.1])
        out[0.9] = np.maximum(out[0.9], out[0.5])
        return out


def refit_predict_log(world: WorldData, target: str, fit_end: int, issues: np.ndarray,
                      every: int = WEEK, base: Forecaster | None = None,
                      **fit_kw) -> dict[float, np.ndarray]:
    """Uncalibrated log forecasts with periodic re-fitting (FINDINGS E19).

    Issues in ``[r, r + every)`` come from a model fitted on targets before ``r``, for
    ``r = fit_end, fit_end + every, ...``: every forecast stays out-of-sample, as in production.
    ``base`` (optional) is the model already fitted at ``fit_end``.
    """
    out = {q: np.empty((len(issues), HORIZON, world.S)) for q in QUANTILES}
    r = fit_end
    while r <= issues.max():
        sel = (issues >= r) & (issues < r + every)
        if sel.any():
            f = base if (r == fit_end and base is not None) else \
                Forecaster.fit(world, target, r, **fit_kw)
            lp = f.predict_log(world, issues[sel])
            for q in QUANTILES:
                out[q][sel] = lp[q]
        r += every
    return out


def calibrate(f: Forecaster, world: WorldData, start: int, end: int, every: int = 4) -> None:
    """Conformal shift: per quantile and horizon, move the log forecast so that a share q of
    calibration outcomes falls below it. Uses issues in [start, end - HORIZON]."""
    issues = np.arange(start, end - HORIZON + 1, every)
    raw = f.predict_many(world, issues, calibrated=False)
    y = np.log1p(truth(world, f.target, issues))
    for q in QUANTILES:
        resid = y - np.log1p(raw[q])                       # [n, H, S]
        f.offsets[q] = np.quantile(resid.transpose(1, 0, 2).reshape(HORIZON, -1), q, axis=1)


def seasonal_naive(world: WorldData, target: str, issues: np.ndarray) -> np.ndarray:
    """Same quarter-hour one week earlier: [n_issues, HORIZON, S] MB."""
    v = sum(world.vol[c] for c in TARGETS[target])
    idx = issues[:, None] + np.arange(HORIZON)[None, :] - WEEK
    return v[idx]


def persistence(world: WorldData, target: str, issues: np.ndarray) -> np.ndarray:
    v = sum(world.vol[c] for c in TARGETS[target])
    return np.repeat(v[issues - 1][:, None, :], HORIZON, axis=1)


def truth(world: WorldData, target: str, issues: np.ndarray) -> np.ndarray:
    v = sum(world.vol[c] for c in TARGETS[target])
    return v[issues[:, None] + np.arange(HORIZON)[None, :]]


def pinball(y: np.ndarray, q_pred: np.ndarray, q: float) -> float:
    d = y - q_pred
    return float(np.mean(np.maximum(q * d, (q - 1) * d)))
