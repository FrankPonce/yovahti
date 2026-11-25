"""Baselines reconstructed from other companies' published methods (verified sources in
docs/SOURCES.md, "Published cell-sleep methods by others"). Each is a *reconstruction from a
public document*, not the company's software; substitutions are named in each docstring.

Shared ground rules, so the comparison is about the method: every policy sees what B2/B3/B4 see
(the previous quarter-hour, the same LightGBM forecasts, history before ``t``), runs in the same
simulator with the same watchdog, and learned methods train on the training weeks only.

* ``ElisaDefaultPlan``  · Elisa WO2022058648A1 / EP4214968B1, the default plan.
* ``ParallelWirelessRule`` · Parallel Wireless US20230127116A1.
* ``EricssonBlogThresholds`` · Ericsson 2023 blog (B2 as described there, "B2b").
* ``NokiaQLearning``    · Nokia EP4175370A2.
* ``ReissClassifier``   · Reiss et al., ICC 2026 / MSWiM 2025 (approach, not their model).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from yovahti.baselines.published import _ForecastAccess
from yovahti.energy import tr38864
from yovahti.world.data import BANDWIDTH, EFFICIENCY, LOW, MID, WorldData
from yovahti.world.sim import ASLEEP, AWAKE, Observation, WorldConfig

TZ = "Europe/Bratislava"


# ------------------------------------------------------------------ shared layer arrays
@dataclass
class Layers:
    """Per-sector layer loads (%) over a whole world, plus what moves where on sleep."""
    low: np.ndarray        # [T,S] coverage load on its own
    mid: np.ndarray        # [T,S] mid-band capacity load
    nr: np.ndarray         # [T,S] NR 3500 load
    low_if_mid: np.ndarray  # [T,S] coverage load if the mid layer sleeps
    mid_if_nr: np.ndarray   # [T,S] mid load if NR 3500 sleeps
    hour: np.ndarray        # [T] local hour
    how: np.ndarray         # [T] local hour of week

    @classmethod
    def of(cls, w: WorldData) -> Layers:
        cap_low = sum(w.present[c] * EFFICIENCY[c] * BANDWIDTH[c] for c in LOW)
        cap_mid = sum(w.present[c] * EFFICIENCY[c] * BANDWIDTH[c] for c in MID)
        cap_nr = w.present["NR_3500"] * EFFICIENCY["NR_3500"] * BANDWIDTH["NR_3500"]

        def u(mb, cap):
            return np.divide(mb, cap, out=np.zeros_like(mb, dtype=float), where=cap > 0)
        low_mb = sum(w.vol[c] for c in LOW)
        mid_mb = sum(w.vol[c] for c in MID)
        nr_mb = w.vol["NR_3500"]
        lt = w.times.tz_convert(TZ)
        def c(x):
            return np.nan_to_num(x, nan=0.0, posinf=0.0)
        return cls(low=c(u(low_mb, cap_low)), mid=c(u(mid_mb, cap_mid)), nr=c(u(nr_mb, cap_nr)),
                   low_if_mid=c(u(low_mb + mid_mb, cap_low)),
                   mid_if_nr=c(u(mid_mb + nr_mb, cap_mid)),
                   hour=lt.hour.to_numpy(), how=(lt.day_of_week * 24 + lt.hour).to_numpy())


def _sleep_ratios(cfg: WorldConfig) -> tuple[float, float]:
    cat = cfg.category
    return (tr38864.power("deep_sleep", cat, 2) / tr38864.power("micro_sleep", cat, 2),
            tr38864.power("deep_sleep", cat, 1) / tr38864.power("micro_sleep", cat, 1))


# ------------------------------------------------------------------ Elisa
@dataclass
class ElisaDefaultPlan:
    """Elisa's *default plan*: full shutdown of the capacity cells for a fixed night window
    (patent: 3-7 h, example 01:00-06:00), applied where the layer is in the patent's 0-10 %
    load range. The patent's alternative, partial shutdown of MIMO antenna branches, is not
    modelled: the power model has no antenna-branch state (reported analytically instead)."""
    world: WorldData
    start_hour: int = 1
    hours: int = 5
    max_load: float = 10.0

    def __post_init__(self):
        h = self.world.times.tz_convert(TZ).hour.to_numpy()
        end = (self.start_hour + self.hours) % 24
        self.in_window = ((h >= self.start_hour) & (h < end)) if end > self.start_hour else \
            ((h >= self.start_hour) | (h < end))

    def __call__(self, obs: Observation) -> tuple[np.ndarray, np.ndarray]:
        if obs.t == 0 or not self.in_window[obs.t]:
            z = np.zeros_like(obs.mid_state)
            return z, z
        ms = np.where((obs.mid_state == ASLEEP) | (obs.mid_util < self.max_load), ASLEEP, AWAKE)
        ns = np.where((obs.nr_state == ASLEEP) | (obs.util["NR_3500"] < self.max_load),
                      ASLEEP, AWAKE)
        return ms.astype(np.int8), ns.astype(np.int8)


# ------------------------------------------------------------------ Parallel Wireless
@dataclass
class ParallelWirelessRule(_ForecastAccess):
    """Power a capacity layer down when its per-cell forecast is near zero for the next two
    hours; re-evaluated every quarter-hour; rolled back for the rest of the night if the
    coverage layer's load rises beyond its normal spread (mean + 2 sd of the training weeks).
    Substitution: our LightGBM P50 forecasts stand in for the patent's LSTM/GRU models."""
    world: WorldData
    forecasts: dict
    issue_offset: int
    low_mean: np.ndarray = None      # [S] coverage load, training weeks
    low_sd: np.ndarray = None
    near_zero: float = 1.0           # % load counted as "no traffic"
    window_qh: int = 8               # two hours

    def __post_init__(self):
        _ForecastAccess.__init__(self, self.world, self.forecasts, self.issue_offset)
        self.blocked = np.zeros(self.w.S, dtype=bool)
        self.hour = self.w.times.tz_convert(TZ).hour.to_numpy()

    def __call__(self, obs: Observation) -> tuple[np.ndarray, np.ndarray]:
        if self.hour[obs.t] == 12:                       # a new night: clear rollbacks
            self.blocked[:] = False
        loc = self.latest(obs.t)
        if loc is None or obs.t == 0:
            z = np.zeros_like(obs.mid_state)
            return z, z
        k, off = loc
        sl = slice(off, off + self.window_qh)
        u_mid = self.util(self.f["mid"][0.5][k][sl].astype(float), self.cap_mid)
        u_nr = self.util(self.f["nr"][0.5][k][sl].astype(float), self.cap_nr)
        asleep = (obs.mid_state == ASLEEP) | (obs.nr_state == ASLEEP)
        self.blocked |= asleep & (obs.low_util > self.low_mean + 2 * self.low_sd)
        ok = ~self.blocked
        ms = np.where(ok & (u_mid < self.near_zero).all(axis=0), ASLEEP, AWAKE)
        ns = np.where(ok & (u_nr < self.near_zero).all(axis=0), ASLEEP, AWAKE)
        return ms.astype(np.int8), ns.astype(np.int8)


# ------------------------------------------------------------------ Ericsson (blog)
@dataclass
class EricssonBlogThresholds(_ForecastAccess):
    """B2 as the 2023 blog describes it ("B2b"): per-cell sleep thresholds on PRB utilisation
    *and* connected users, chosen once a day by grid search on the day-ahead forecast to
    maximise sleep hours subject to a KPI constraint (here: the coverage cell stays under its
    wake threshold in every forecast quarter-hour asleep). At run time the cell sleeps when
    both observed PRB load and users are below threshold and wakes on coverage overload.
    Substitutions: active users stand in for RRC connections; users are forecast as the same
    quarter-hour a day earlier (the blog does not say how)."""
    world: WorldData
    forecasts: dict
    issue_offset: int
    users: dict = None               # carrier -> [T_full, S] active users, full period
    user_offset: int = 0             # index of world t=0 in the users arrays
    prb_grid: tuple[float, ...] = (0, 2, 4, 6, 8, 10, 15, 20)
    user_grid: tuple[float, ...] = (1, 2, 3, 5, 8, 12, 20)
    wake_low_above: float = 30.0
    wake_mid_above: float = 50.0
    choose_hour: int = 22

    def __post_init__(self):
        _ForecastAccess.__init__(self, self.world, self.forecasts, self.issue_offset)
        S = self.w.S  # noqa: N806
        self.th = {"mid": (np.zeros(S), np.zeros(S)), "nr": (np.zeros(S), np.zeros(S))}
        self.hour = self.w.times.tz_convert(TZ).hour.to_numpy()
        self.day_seen = -1
        u = self.users
        self.u_mid = u["LTE_1800"] + u["NR_2100"]
        self.u_nr = u["NR_3500"]

    def _grid(self, load, users_pred, after, wake):
        best_n = np.full(self.w.S, -1)
        best_p, best_u = np.zeros(self.w.S), np.zeros(self.w.S)
        for p in self.prb_grid:
            for q in self.user_grid:
                asleep = (load < p) & (users_pred < q)
                feasible = ~((asleep & (after > wake)).any(axis=0))     # the KPI constraint
                n = np.where(feasible, asleep.sum(axis=0), -1)
                better = n > best_n
                best_n = np.where(better, n, best_n)
                best_p = np.where(better, p, best_p)
                best_u = np.where(better, q, best_u)
        return best_p, best_u

    def _choose(self, k: int, t: int) -> None:
        H = self.f["mid"][0.5].shape[1]  # noqa: N806
        mid = self.f["mid"][0.5][k].astype(float)
        nr = self.f["nr"][0.5][k].astype(float)
        low = self.f["low"][0.5][k].astype(float)
        i0 = t + self.user_offset - 96                    # same quarter-hours yesterday
        um = self.u_mid[i0:i0 + H]
        un = self.u_nr[i0:i0 + H]
        n = min(len(um), H)
        self.th["mid"] = self._grid(self.util(mid, self.cap_mid)[:n], um[:n],
                                    self.util(low + mid, self.cap_low)[:n], self.wake_low_above)
        self.th["nr"] = self._grid(self.util(nr, self.cap_nr)[:n], un[:n],
                                   self.util(mid + nr, self.cap_mid)[:n], self.wake_mid_above)

    def __call__(self, obs: Observation) -> tuple[np.ndarray, np.ndarray]:
        loc = self.latest(obs.t)
        day = obs.t // 96
        if loc is not None and self.hour[obs.t] == self.choose_hour and day != self.day_seen:
            self.day_seen = day
            self._choose(loc[0], obs.t)
        if obs.t == 0:
            z = np.zeros_like(obs.mid_state)
            return z, z
        i = obs.t - 1 + self.user_offset
        (pm, qm), (pn, qn) = self.th["mid"], self.th["nr"]
        ms, ns = obs.mid_state.copy(), obs.nr_state.copy()
        ms = np.where((ms == AWAKE) & (obs.mid_util < pm) & (self.u_mid[i] < qm), ASLEEP, ms)
        ms = np.where((ms == ASLEEP) & (obs.low_util > self.wake_low_above), AWAKE, ms)
        ns = np.where((ns == AWAKE) & (obs.util["NR_3500"] < pn) & (self.u_nr[i] < qn),
                      ASLEEP, ns)
        ns = np.where((ns == ASLEEP) & ((obs.mid_util > self.wake_mid_above)
                                        | (obs.low_util > self.wake_low_above)), AWAKE, ns)
        return ms.astype(np.int8), ns.astype(np.int8)


# ------------------------------------------------------------------ Nokia (Q-learning)
LOAD_BINS = np.array([0.5, 1, 2, 5, 10, 20])                  # capacity layer load, %
AFTER_BINS = {"mid": np.array([10, 20, 25, 30, 35, 40]),      # coverage load if mid sleeps
              "nr": np.array([20, 40, 50, 60, 70])}           # mid load if NR sleeps
LIMIT = {"mid": 40.0, "nr": 70.0}                             # receiving layer's limit (sim)
FREEZE = 2                                                    # quarter-hours (30 min)


def _qstate(layer: str, load, after, on, frozen):
    a = np.digitize(load, LOAD_BINS)
    b = np.digitize(after, AFTER_BINS[layer])
    nb = len(AFTER_BINS[layer]) + 1
    return ((a * nb + b) * 2 + on) * 2 + frozen


def train_q(layers: Layers, lo: int, hi: int, cfg: WorldConfig, weight: float,
            seed: int = 0, epochs: int = 3, alpha: float = 0.1, gamma: float = 0.9,
            eps: float = 0.1) -> dict:
    """Tabular Q-learning on the training weeks (rows lo..hi of ``layers``), vectorised over
    sectors. State: load bucket, receiving-layer-after-move bucket, on/off, frozen. Actions:
    0 do nothing, 1 switch off, 2 switch on. Reward: -(normalised power) - weight x (the
    receiving layer congests), the patent's throughput-versus-power trade-off with the
    operator weight as a dial."""
    rng = np.random.default_rng(seed)
    r_mid, r_nr = _sleep_ratios(cfg)
    out = {}
    for layer, ratio, load_a, after_a in (("mid", r_mid, layers.mid, layers.low_if_mid),
                                          ("nr", r_nr, layers.nr, layers.mid_if_nr)):
        nstates = (len(LOAD_BINS) + 1) * (len(AFTER_BINS[layer]) + 1) * 4
        q = np.zeros((nstates, 3))
        S = load_a.shape[1]  # noqa: N806
        for _ in range(epochs):
            on = np.ones(S, dtype=int)
            freeze = np.zeros(S, dtype=int)
            for t in range(lo + 1, hi - 1):
                s = _qstate(layer, load_a[t - 1], after_a[t - 1], on, (freeze > 0).astype(int))
                greedy = q[s].argmax(axis=1)
                act = np.where(rng.random(S) < eps, rng.integers(0, 3, S), greedy)
                act = np.where(freeze > 0, 0, act)
                new_on = np.where(act == 1, 0, np.where(act == 2, 1, on))
                switched = new_on != on
                freeze = np.where(switched, FREEZE, np.maximum(freeze - 1, 0))
                cong = (new_on == 0) & (after_a[t] * 1.25 > LIMIT[layer])
                reward = -np.where(new_on == 1, 1.0, ratio) - weight * cong
                s2 = _qstate(layer, load_a[t], after_a[t], new_on, (freeze > 0).astype(int))
                target = reward + gamma * q[s2].max(axis=1)
                # many sectors share a state: average their targets, then one update per
                # (state, action), so 749 identical updates don't add up (they diverged)
                cell = s * 3 + act
                n = np.bincount(cell, minlength=q.size)
                tot = np.bincount(cell, weights=target, minlength=q.size)
                hit = n > 0
                flat = q.reshape(-1)
                flat[hit] += alpha * (tot[hit] / n[hit] - flat[hit])
                on = new_on
        out[layer] = q
    return out


@dataclass
class NokiaQLearning:
    """Greedy policy from ``train_q``. Substitution: the observed load of the previous
    quarter-hour stands in for the patent's separate load-prediction model."""
    layers: Layers
    offset: int                      # index of world t=0 in ``layers``
    tables: dict = field(default_factory=dict)

    def __post_init__(self):
        self.freeze = {"mid": None, "nr": None}

    def _layer(self, layer, t, state):
        L = self.layers  # noqa: N806
        load, after = (L.mid, L.low_if_mid) if layer == "mid" else (L.nr, L.mid_if_nr)
        i = t - 1 + self.offset
        if self.freeze[layer] is None:
            self.freeze[layer] = np.zeros(len(state), dtype=int)
        on = (state == AWAKE).astype(int)
        fr = self.freeze[layer]
        s = _qstate(layer, load[i], after[i], on, (fr > 0).astype(int))
        act = np.where(fr > 0, 0, self.tables[layer][s].argmax(axis=1))
        new_on = np.where(act == 1, 0, np.where(act == 2, 1, on))
        self.freeze[layer] = np.where(new_on != on, FREEZE, np.maximum(fr - 1, 0))
        return np.where(new_on == 1, AWAKE, ASLEEP).astype(np.int8)

    def __call__(self, obs: Observation) -> tuple[np.ndarray, np.ndarray]:
        if obs.t == 0:
            z = np.zeros_like(obs.mid_state)
            return z, z
        return self._layer("mid", obs.t, obs.mid_state), self._layer("nr", obs.t, obs.nr_state)


# ------------------------------------------------------------------ Reiss et al. (classifier)
LAGS = (1, 2, 4, 96, 672)


def _features(layers: Layers, idx: np.ndarray, layer: str) -> np.ndarray:
    """Rows = (t, sector) pairs flattened; known before t only."""
    load, after = (layers.mid, layers.low_if_mid) if layer == "mid" else \
        (layers.nr, layers.mid_if_nr)
    S = load.shape[1]  # noqa: N806
    cols = []
    how = layers.how[idx]
    ang = 2 * np.pi * how / 168
    cols += [np.repeat(np.sin(ang), S), np.repeat(np.cos(ang), S)]
    for lag in LAGS:
        cols += [load[idx - lag].ravel(), after[idx - lag].ravel()]
    cols.append(np.tile(np.arange(S), len(idx)).astype(float))   # sector id (categorical-ish)
    return np.column_stack(cols)


def train_classifier(layers: Layers, lo: int, hi: int, seed: int = 0) -> dict:
    """Per layer, P(switching the layer off at t keeps the receiving layer within its limit)."""
    import lightgbm as lgb
    rng = np.random.default_rng(seed)
    models = {}
    for layer in ("mid", "nr"):
        after = layers.low_if_mid if layer == "mid" else layers.mid_if_nr
        idx = np.arange(max(lo, 673), hi)
        idx = np.sort(rng.choice(idx, size=min(len(idx), 1500), replace=False))
        x = _features(layers, idx, layer)
        y = (after[idx] * 1.25 <= LIMIT[layer]).ravel().astype(int)
        m = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05, num_leaves=63,
                               random_state=seed, verbose=-1)
        m.fit(x, y)
        models[layer] = m
    return models


@dataclass
class ReissClassifier:
    """Switch a capacity layer off whenever the classifier's probability that the QoS
    constraint holds is at least ``tau`` (their run-time tunable threshold). Substitution:
    gradient-boosted trees on lagged loads instead of their LSTM (their earlier paper uses
    XGBoost); the constraint is our congestion limit, not their throughput/outage targets."""
    layers: Layers
    offset: int
    models: dict
    tau: float = 0.9

    def __call__(self, obs: Observation) -> tuple[np.ndarray, np.ndarray]:
        if obs.t == 0:
            z = np.zeros_like(obs.mid_state)
            return z, z
        idx = np.array([obs.t + self.offset])
        out = []
        for layer in ("mid", "nr"):
            p = self.models[layer].predict_proba(_features(self.layers, idx, layer))[:, 1]
            out.append(np.where(p >= self.tau, ASLEEP, AWAKE).astype(np.int8))
        return out[0], out[1]
