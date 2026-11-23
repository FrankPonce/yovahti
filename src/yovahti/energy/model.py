"""Radio-unit energy model fitted on real operator data (Slovak Dataset_03).

Each sector has radio units that serve several carriers and report one energy value (E10):

    low     GSM 900 + LTE 700 + LTE 800     coverage layer, never sleeps (D24)
    mid     LTE 1800 + NR 2100              capacity layer, can sleep
    nr3500  NR 3500 (massive MIMO)          capacity layer, can sleep

Model per radio unit i at time t (Wh per 15 minutes):

    E_it = idle_i + sum_c slope_{type,c} * util_{c,it} + noise

``idle_i`` is the unit's own fingerprint (its energy at zero load), ``slope`` is shared by all
units of a type. Fitted by within-unit least squares on the **training split only** (D23).

Sleep (TR 38.864): a sleeping unit draws ``idle_i * sleep_ratio`` where sleep_ratio is the
spec's sleep power over its micro-sleep (empty but on) power. Category 1 is optimistic,
Category 2 conservative; both are reported.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from yovahti.energy import tr38864
from yovahti.paths import PROCESSED

RADIO_UNITS: dict[str, list[str]] = {
    "low": ["GSM_900", "LTE_700", "LTE_800"],
    "mid": ["LTE_1800", "NR_2100"],
    "nr3500": ["NR_3500"],
}
SLEEPABLE = ("mid", "nr3500")
# TR 38.864 reference set that best matches each sleepable unit (Table 5.1-1).
REF_SET = {"mid": 2, "nr3500": 1}

SPLITS = {  # D23, UTC, end exclusive
    "train": ("2025-08-31", "2025-10-26"),
    "validation": ("2025-10-26", "2025-11-09"),
    "test": ("2025-11-09", "2025-11-23"),
}
KEY = ["site", "sector", "time"]
ABSENT_IF_MISSING = 0.9  # a carrier with >90 % missing load on a unit is treated as absent


def util_col(carrier: str) -> str:
    return "ts_util_pct" if carrier.startswith("GSM") else "rb_util_pct"


def load_unit_table(unit: str, split: str | None = None,
                    root: Path = PROCESSED / "slovak") -> pd.DataFrame:
    """One row per (site, sector, time) of a radio unit: energy plus each carrier's load."""
    frames = []
    for i, carrier in enumerate(RADIO_UNITS[unit]):
        cols = KEY + [util_col(carrier)] + (["ru_energy_wh"] if i == 0 else [])
        d = pd.read_parquet(root / f"Dataset_03_{carrier}.parquet", columns=cols)
        frames.append(d.rename(columns={util_col(carrier): f"u_{carrier}"}).set_index(KEY))
    df = pd.concat(frames, axis=1, join="inner").reset_index()
    if split:
        lo, hi = (pd.Timestamp(x, tz="UTC") for x in SPLITS[split])
        df = df[(df["time"] >= lo) & (df["time"] < hi)]
    df["unit_id"] = df["site"].astype(str) + "/" + df["sector"].astype(str)
    return df.reset_index(drop=True)


def _absent_carriers(df: pd.DataFrame, carriers: list[str]) -> pd.DataFrame:
    """Per unit: True where a carrier's load is (almost) always missing, i.e. not configured."""
    miss = df.groupby("unit_id")[[f"u_{c}" for c in carriers]].apply(lambda g: g.isna().mean())
    return miss > ABSENT_IF_MISSING


def _prepare(df: pd.DataFrame, carriers: list[str]) -> pd.DataFrame:
    """Absent carriers count as zero load; rows still missing a present carrier are dropped."""
    absent = _absent_carriers(df, carriers)
    out = df.copy()
    for c in carriers:
        col = f"u_{c}"
        is_absent = out["unit_id"].map(absent[col]).fillna(False).astype(bool)
        out.loc[is_absent, col] = 0.0
    return out.dropna(subset=["ru_energy_wh"] + [f"u_{c}" for c in carriers])


@dataclass
class UnitTypeModel:
    unit: str
    carriers: list[str]
    slopes: dict[str, float]                      # Wh per 15 min per % utilisation
    idle: dict[str, float] = field(repr=False)    # unit_id -> Wh per 15 min at zero load
    idle_default: float = 0.0                     # median idle, for units unseen in training
    train_rows: int = 0
    fit_r2_within: float = float("nan")

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        base = df["unit_id"].map(self.idle).fillna(self.idle_default).to_numpy(float)
        for c in self.carriers:
            base = base + self.slopes[c] * df[f"u_{c}"].to_numpy(float)
        return base

    def sleep_ratio(self, state: tr38864.State = "deep_sleep",
                    category: tr38864.Category = 1) -> float:
        ref = REF_SET.get(self.unit, 2)
        return tr38864.power(state, category, ref) / tr38864.power("micro_sleep", category, ref)

    def sleep_energy(self, unit_id: str, state: tr38864.State = "deep_sleep",
                     category: tr38864.Category = 1) -> float:
        """Wh per 15 min while asleep (transition energy is negligible at 15-min scale)."""
        return self.idle.get(unit_id, self.idle_default) * self.sleep_ratio(state, category)

    def to_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path) -> UnitTypeModel:
        return cls(**json.loads(path.read_text(encoding="utf-8")))


def fit(unit: str, train: pd.DataFrame) -> UnitTypeModel:
    carriers = RADIO_UNITS[unit]
    d = _prepare(train, carriers)
    xcols = [f"u_{c}" for c in carriers]
    # within-unit demeaning removes each unit's fingerprint, leaving the shared slopes
    means = d.groupby("unit_id")[["ru_energy_wh", *xcols]].transform("mean")
    y = (d["ru_energy_wh"] - means["ru_energy_wh"]).to_numpy(float)
    x = (d[xcols] - means[xcols]).to_numpy(float)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    r2 = 1 - resid.var() / y.var() if y.var() > 0 else float("nan")
    slopes = {c: float(b) for c, b in zip(carriers, beta, strict=True)}
    unit_means = d.groupby("unit_id")[["ru_energy_wh", *xcols]].mean()
    idle = unit_means["ru_energy_wh"] - sum(slopes[c] * unit_means[f"u_{c}"] for c in carriers)
    idle = idle.clip(lower=0)
    return UnitTypeModel(unit=unit, carriers=carriers, slopes=slopes,
                         idle={k: float(v) for k, v in idle.items()},
                         idle_default=float(idle.median()), train_rows=len(d),
                         fit_r2_within=float(r2))


def evaluate(model: UnitTypeModel, df: pd.DataFrame) -> dict[str, float]:
    d = _prepare(df, model.carriers)
    y = d["ru_energy_wh"].to_numpy(float)
    p = model.predict(d)
    err = p - y
    return {
        "rows": float(len(d)),
        "mae_wh": float(np.abs(err).mean()),
        "mape_pct": float(100 * np.abs(err / np.where(y == 0, np.nan, y))[~np.isnan(y)].mean()),
        "bias_wh": float(err.mean()),
        "r2": float(1 - err.var() / y.var()),
        "mean_wh": float(y.mean()),
        "idle_share": float(np.mean([model.idle.get(u, model.idle_default)
                                     for u in d["unit_id"]]) / y.mean()),
    }
