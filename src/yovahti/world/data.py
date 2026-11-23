"""Build the world's ground-truth arrays from the real Slovak data (Dataset_03).

A *sector* is one (site, sector) pair with a mid-band radio. Every array is [T, S]:
T quarter-hours of a split, S sectors. Values are what the network really carried; the
simulator re-routes that traffic when radios sleep.

Missing loads (G20): a carrier with >90 % missing load on a sector is absent (zero, never
"idle"); other gaps are filled forward/backward up to an hour, then with the sector's median.
The share of imputed values is kept so results can be checked against it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from yovahti.energy.model import SPLITS, UnitTypeModel
from yovahti.paths import PROCESSED, RESULTS

CARRIERS = ["LTE_700", "LTE_800", "LTE_1800", "NR_2100", "NR_3500"]
LOW = ["LTE_700", "LTE_800"]          # coverage layer data carriers (GSM is voice, left as is)
MID = ["LTE_1800", "NR_2100"]
BANDWIDTH = {"LTE_700": 10, "LTE_800": 10, "LTE_1800": 20, "NR_2100": 20, "NR_3500": 100}
# MB of downlink per (% utilisation x MHz), median on the training weeks (FINDINGS E12).
EFFICIENCY = {"LTE_700": 3.03, "LTE_800": 3.18, "LTE_1800": 2.55, "NR_2100": 4.42,
              "NR_3500": 4.28}
ABSENT_IF_MISSING = 0.9


@dataclass
class WorldData:
    times: pd.DatetimeIndex
    sectors: list[str]
    util: dict[str, np.ndarray]           # carrier -> [T,S] % (absent carriers are 0)
    vol: dict[str, np.ndarray]            # carrier -> [T,S] MB downlink per quarter-hour
    present: dict[str, np.ndarray]        # carrier -> [S] bool
    gsm_util: np.ndarray                  # [T,S] GSM time-slot utilisation (affects low energy)
    idle: dict[str, np.ndarray]           # unit type -> [S] Wh per 15 min at zero load
    slopes: dict[str, dict[str, float]]   # unit type -> carrier -> Wh per % load
    measured_energy: dict[str, np.ndarray]  # unit type -> [T,S] Wh measured (NaN if missing)
    price: np.ndarray                     # [T] EUR/MWh
    co2: np.ndarray                       # [T] gCO2/kWh
    imputed_share: dict[str, float] = field(default_factory=dict)

    @property
    def T(self) -> int:  # noqa: N802
        return len(self.times)

    @property
    def S(self) -> int:  # noqa: N802
        return len(self.sectors)

    def subset(self, sectors: np.ndarray) -> WorldData:
        """A world restricted to some sectors (boolean mask or indices)."""
        idx = np.arange(self.S)[sectors]

        def cut(a):
            return a[:, idx] if a.ndim == 2 else a[idx]
        return WorldData(
            times=self.times, sectors=[self.sectors[i] for i in idx],
            util={k: cut(v) for k, v in self.util.items()},
            vol={k: cut(v) for k, v in self.vol.items()},
            present={k: cut(v) for k, v in self.present.items()},
            gsm_util=cut(self.gsm_util),
            idle={k: cut(v) for k, v in self.idle.items()}, slopes=self.slopes,
            measured_energy={k: cut(v) for k, v in self.measured_energy.items()},
            price=self.price, co2=self.co2, imputed_share=self.imputed_share)


def _pivot(df: pd.DataFrame, col: str, times: pd.DatetimeIndex, sectors: list[str]) -> np.ndarray:
    p = df.pivot_table(index="time", columns="unit_id", values=col, aggfunc="first",
                       observed=True, dropna=False)
    return p.reindex(index=times, columns=sectors).to_numpy(dtype="float64")


def _fill(a: np.ndarray) -> tuple[np.ndarray, float]:
    """Fill gaps up to 4 quarter-hours each way, then with the column median."""
    miss = np.isnan(a)
    f = pd.DataFrame(a).ffill(limit=4).bfill(limit=4)
    f = f.fillna(f.median())
    return f.fillna(0.0).to_numpy(), float(miss.mean())


def _series(path: Path, col: str, times: pd.DatetimeIndex) -> np.ndarray:
    s = pd.read_parquet(path).set_index("time")[col].astype(float).sort_index()
    s = s[~s.index.duplicated()]
    return s.reindex(s.index.union(times)).ffill().reindex(times).to_numpy()


def load_world(split: str, root: Path = PROCESSED, models: Path = RESULTS / "energy",
               max_sectors: int | None = None) -> WorldData:
    lo, hi = (pd.Timestamp(x, tz="UTC") for x in SPLITS[split])
    times = pd.date_range(lo, hi, freq="15min", inclusive="left")

    def read(carrier, cols):
        d = pd.read_parquet(root / "slovak" / f"Dataset_03_{carrier}.parquet",
                            columns=["site", "sector", "time", *cols])
        d = d[(d["time"] >= lo) & (d["time"] < hi)]
        d["unit_id"] = d["site"].astype(str) + "/" + d["sector"].astype(str)
        return d

    frames = {c: read(c, ["rb_util_pct", "vol_dl_mb", "ru_energy_wh"]) for c in CARRIERS}
    gsm = read("GSM_900", ["ts_util_pct"])
    sectors = sorted(set(frames["LTE_1800"]["unit_id"]))
    if max_sectors:
        sectors = sectors[:max_sectors]

    util, vol, present, imputed = {}, {}, {}, {}
    for c in CARRIERS:
        u = _pivot(frames[c], "rb_util_pct", times, sectors)
        v = _pivot(frames[c], "vol_dl_mb", times, sectors)
        pres = np.isnan(u).mean(axis=0) <= ABSENT_IF_MISSING
        imputed[c] = float(np.isnan(u[:, pres]).mean()) if pres.any() else 0.0
        u, _ = _fill(u)
        v_missing = np.isnan(v)
        v = np.where(v_missing, u * BANDWIDTH[c] * EFFICIENCY[c], v)
        util[c] = np.where(pres, u, 0.0)
        vol[c] = np.where(pres, v, 0.0)
        present[c] = pres
    gsm_u, imputed["GSM_900"] = _fill(_pivot(gsm, "ts_util_pct", times, sectors))

    idle, slopes, measured = {}, {}, {}
    energy_src = {"low": "LTE_800", "mid": "LTE_1800", "nr3500": "NR_3500"}
    for unit, src in energy_src.items():
        m = UnitTypeModel.from_json(models / f"{unit}.json")
        idle[unit] = np.array([m.idle.get(s, m.idle_default) for s in sectors])
        slopes[unit] = m.slopes
        measured[unit] = _pivot(frames[src], "ru_energy_wh", times, sectors)
    idle["nr3500"] = np.where(present["NR_3500"], idle["nr3500"], 0.0)

    price = _series(root / "prices" / "fi_day_ahead.parquet", "eur_mwh", times)
    co2 = _series(root / "co2" / "fi_consumed_15min.parquet", "g_co2_kwh", times)
    return WorldData(times=times, sectors=sectors, util=util, vol=vol, present=present,
                     gsm_util=gsm_u, idle=idle, slopes=slopes, measured_energy=measured,
                     price=price, co2=co2, imputed_share=imputed)
