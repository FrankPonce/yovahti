"""Data-quality and structure report for Slovak Dataset_03 (the primary data).

Run: uv run python scripts/slovak_quality.py
Prints findings that decide how the world and energy model are built:
coverage, missing data, which carriers share a radio unit's energy reading,
day/night load per layer, and how much radio-unit energy is fixed vs load-driven.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from yovahti.paths import PROCESSED

S = PROCESSED / "slovak"
FILES = ["GSM_900", "LTE_700", "LTE_800", "LTE_1800", "NR_2100", "NR_3500"]
KEY = ["site", "sector", "time"]


def load(name: str, cols: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(S / f"Dataset_03_{name}.parquet", columns=cols)


def main() -> None:
    expected = None
    print("== Coverage and missing data")
    for f in FILES:
        d = load(f)
        t = d["time"]
        n_int = t.nunique()
        expected = expected or int((t.max() - t.min()) / pd.Timedelta("15min")) + 1
        util = "ts_util_pct" if f.startswith("GSM") else "rb_util_pct"
        ss = d.groupby(["site", "sector"]).size()
        print(f"{f:9s} rows {len(d):>9,} | site-sectors {len(ss):>4} | intervals {n_int}/{expected}"
              f" | rows/site-sector median {int(ss.median())} | missing util "
              f"{100 * d[util].isna().mean():.1f}% | missing RU energy "
              f"{100 * d['ru_energy_wh'].isna().mean():.1f}% | RU energy == 0 "
              f"{100 * (d['ru_energy_wh'] == 0).mean():.1f}%")

    print("\n== Do carriers share one radio unit's energy reading? (same site, sector, time)")
    e = {f: load(f, KEY + ["ru_energy_wh"]).set_index(KEY)["ru_energy_wh"] for f in FILES}
    for i, a in enumerate(FILES):
        for b in FILES[i + 1:]:
            j = pd.concat([e[a], e[b]], axis=1, join="inner").dropna()
            if len(j) == 0:
                continue
            same = (np.isclose(j.iloc[:, 0], j.iloc[:, 1])).mean()
            print(f"{a:9s} vs {b:9s}: {len(j):>9,} joint rows, identical {100 * same:5.1f}%")

    print("\n== Is baseband energy shared by all sectors of a site?")
    bb = load("LTE_1800", KEY + ["bb_energy_wh"]).dropna()
    per = bb.groupby(["site", "time"])["bb_energy_wh"].nunique()
    print(f"site-times with one baseband value across sectors: {100 * (per == 1).mean():.1f}%")

    print("\n== Median load by local hour (Europe/Bratislava), % of the layer's peak hour")
    for f in FILES:
        util = "ts_util_pct" if f.startswith("GSM") else "rb_util_pct"
        d = load(f, ["time", util]).dropna()
        h = d["time"].dt.tz_convert("Europe/Bratislava").dt.hour
        med = d.groupby(h)[util].median()
        print(f"{f:9s} peak {med.max():5.1f}% at {med.idxmax():02d}h | trough {med.min():5.2f}% at "
              f"{med.idxmin():02d}h | trough/peak {med.min() / med.max():.2f}")

    print("\n== Radio-unit energy vs own-carrier load (robust: median energy per load decile)")
    for f in ["NR_3500", "LTE_1800", "LTE_800"]:
        d = load(f, ["site", "rb_util_pct", "ru_energy_wh"]).dropna()
        d = d[d["ru_energy_wh"] > 0]
        d["dec"] = pd.qcut(d["rb_util_pct"].rank(method="first"), 10, labels=False)
        g = d.groupby("dec").agg(util=("rb_util_pct", "median"), wh=("ru_energy_wh", "median"))
        lo, hi = g.iloc[0], g.iloc[-1]
        print(f"{f:9s} lowest-decile util {lo.util:5.2f}% -> {lo.wh:6.1f} Wh/15min | "
              f"highest-decile util {hi.util:5.1f}% -> {hi.wh:6.1f} Wh/15min | "
              f"idle share {lo.wh / hi.wh:.2f}")


if __name__ == "__main__":
    main()
