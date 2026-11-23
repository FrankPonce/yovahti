"""Process the Slovak live-RAN PM counters (Lehoczký et al., Sci Data 2026) into Parquet.

One tidy table per carrier file, with a common schema across 2G/4G/5G:

    site, sector, time (UTC), dataset, baseband, tech (GSM/LTE/NR), band_mhz, bandwidth_mhz,
    ru_energy_wh, bb_energy_wh   (Wh over the 15-minute interval, per radio unit / baseband)
    rb_util_pct, rrc_users, rrc_users_max, active_dl, active_ul, active_dl_max, active_ul_max,
    vol_dl_mb, vol_ul_mb, cqi_r1..cqi_r4, mimo_rank_dl              (LTE / NR)
    ts_available, ts_used, ts_util_pct                              (GSM)

Usage:
    uv run python -m yovahti.data.slovak            # all CSVs under data/raw/slovakia
    uv run python -m yovahti.data.slovak --delete-raw   # also remove CSVs and zips afterwards

Missing values and outliers are kept as published (the descriptor keeps them on purpose).
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

import pandas as pd

from yovahti.paths import PROCESSED, RAW

SRC = RAW / "slovakia"
OUT = PROCESSED / "slovak"

# Table 1 of the data descriptor: channel bandwidth by technology and band (MHz).
BANDWIDTH_MHZ = {
    ("LTE", 700): 10, ("LTE", 800): 10, ("LTE", 1800): 20, ("LTE", 2100): 20,
    ("NR", 700): 10, ("NR", 1800): 20, ("NR", 2100): 20, ("NR", 3500): 100,
}

_COMMON = {
    "Base station": "site",
    "Sector": "sector",
    "Timestamp": "time",
    "Radio unit energy consumption": "ru_energy_wh",
    "Baseband energy consumption": "bb_energy_wh",
}
_CELL = {
    "RB utilization": "rb_util_pct",
    "RRC users": "rrc_users",
    "max RRC users": "rrc_users_max",
    "active users DL": "active_dl",
    "active users UL": "active_ul",
    "max active users DL": "active_dl_max",
    "max active users UL": "active_ul_max",
    "data volume DL": "vol_dl_mb",
    "data volume UL": "vol_ul_mb",
    "CQI rank 1": "cqi_r1",
    "CQI rank 2": "cqi_r2",
    "CQI rank 3": "cqi_r3",
    "CQI rank 4": "cqi_r4",
    "MIMO rank DL": "mimo_rank_dl",
}
_GSM = {"TS available": "ts_available", "TS used": "ts_used", "TS utilization": "ts_util_pct"}

_FILE = re.compile(r"(Dataset_\d+)_(GSM|LTE|NR)_(\d+)\.csv$")


def rename_columns(columns: list[str]) -> dict[str, str]:
    """Map published column names to the common schema; unknown columns raise."""
    out = {}
    for c in columns:
        if c in _COMMON:
            out[c] = _COMMON[c]
            continue
        m = re.match(r"^(2G|4G|5G) (.+)$", c)
        key = m.group(2) if m else None
        if key in _CELL:
            out[c] = _CELL[key]
        elif key in _GSM:
            out[c] = _GSM[key]
        else:
            raise ValueError(f"Unknown column {c!r}")
    return out


SOURCE_TZ = "Europe/Bratislava"


def local_to_utc(t: pd.Series) -> pd.Series:
    """The published timestamps are local wall-clock time, not UTC (FINDINGS G26).

    Proof: the weekday morning traffic ramp stays at 07:00 in the raw stamps before and after
    daylight saving ended on 26 Oct 2025; in UTC it would have moved by an hour. The data has
    no repeated quarter-hours in the ambiguous hour, so that hour is read as standard time,
    leaving a one-hour gap in UTC that the world fills like any other gap.
    """
    naive = t.dt.tz_localize(None) if t.dt.tz is not None else t
    return naive.dt.tz_localize(SOURCE_TZ, ambiguous=False,
                                nonexistent="shift_forward").dt.tz_convert("UTC")


def migrate_timezone(root: Path = OUT) -> None:
    """Fix Parquet files written before G26 (stored stamps were local time labelled UTC)."""
    marker = root / ".tz_local_fixed"
    if marker.exists():
        print("time zone already fixed")
        return
    for f in sorted(root.glob("*.parquet")):
        df = pd.read_parquet(f)
        df["time"] = local_to_utc(df["time"])
        df.to_parquet(f, index=False, compression="zstd")
        print(f"{f.name}: re-stamped {len(df):,} rows", flush=True)
    marker.write_text("timestamps converted from local time to UTC (G26)" + chr(10))


def process_file(path: Path) -> pd.DataFrame:
    m = _FILE.search(path.name)
    if not m:
        raise ValueError(f"Unexpected file name {path.name}")
    dataset, tech, band = m.group(1), m.group(2), int(m.group(3))
    df = pd.read_csv(path, engine="pyarrow")
    df = df.rename(columns=rename_columns(list(df.columns)))
    df["time"] = local_to_utc(pd.to_datetime(df["time"]))
    for c in df.columns:
        if c not in ("site", "sector", "time"):
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float32")
    df["site"] = df["site"].astype("string")
    df["sector"] = df["sector"].astype("int8")
    df.insert(3, "dataset", dataset)
    df.insert(4, "baseband", path.parent.name)
    df.insert(5, "tech", tech)
    df.insert(6, "band_mhz", band)
    df.insert(7, "bandwidth_mhz", BANDWIDTH_MHZ.get((tech, band), pd.NA))
    for c in ("dataset", "baseband", "tech"):
        df[c] = df[c].astype("category")
    return df.sort_values(["site", "sector", "time"], ignore_index=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--delete-raw", action="store_true",
                   help="delete the CSVs and zips after a successful conversion")
    p.add_argument("--fix-timezone", action="store_true",
                   help="re-stamp Parquet files written before the G26 fix, then exit")
    a = p.parse_args(argv)
    if a.fix_timezone:
        migrate_timezone()
        return 0
    files = sorted(SRC.rglob("*.csv"))
    if not files:
        print(f"No CSVs under {SRC}; run: uv run python -m yovahti.data.download slovak")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    for f in files:
        out = OUT / f.name.replace(".csv", ".parquet")
        if out.exists():
            print(f"{f.name}: done earlier")
            continue
        df = process_file(f)
        df.to_parquet(out, index=False, compression="zstd")
        (OUT / ".tz_local_fixed").write_text("written with local-time handling (G26)" + chr(10))
        print(f"{f.name}: {len(df):,} rows, {df['site'].nunique()} sites, "
              f"{out.stat().st_size / 1e6:.0f} MB", flush=True)
    if a.delete_raw:
        for d in SRC.glob("Dataset_*"):
            if d.is_dir():
                shutil.rmtree(d)
        for z in SRC.glob("*.zip"):
            z.unlink()
        print("raw CSVs and zips deleted (re-download with: download slovak)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
