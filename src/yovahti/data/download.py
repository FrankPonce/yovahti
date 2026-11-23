"""Download the public datasets into data/raw and data/processed.

Usage:
    uv run python -m yovahti.data.download itu
    uv run python -m yovahti.data.download grid
    uv run python -m yovahti.data.download prices --start 2025-10-01 --end 2026-11-22
    uv run python -m yovahti.data.download slovak
    uv run python -m yovahti.data.download milan [--days 3]

Every download is recorded in data/raw/MANIFEST.json (url, sha256, size, licence, date).
Downloaded files are data only: they are parsed, never executed.

Milan is 62 daily files of ~320 MB (20.8 GB in total). Each day is streamed to a temporary
file, aggregated over country codes to one row per (square, 10-minute interval), written to
data/processed/milan/ as Parquet, and the raw file is deleted. Peak extra disk use: one day.
Re-running skips days that are already processed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd

from yovahti.paths import PROCESSED, RAW, ROOT

DATAVERSE = "https://dataverse.harvard.edu/api"
MILAN_DOI = "doi:10.7910/DVN/EGZHFV"
GRID_DOI = "doi:10.7910/DVN/QJWLFU"
ITU_ZIP = (
    "https://github.com/ITU-AI-ML-in-5G-Challenge/"
    "5G-Energy-Consumption-Modelling-Solution-Team-Farzi-Data-Scientists/"
    "raw/main/ITU-5G-energy-Consumption-Dataset.zip"
)
PRICES_API = "https://api.energy-charts.info/price"
SLOVAK_RECORD = "17815388"  # Zenodo: PM counters from a live 2G/4G/5G RAN (Ericsson Slovakia)
SLOVAK_FILES = ["README.md", "Dataset_01.zip", "Dataset_02.zip", "Dataset_03.zip"]

LICENCES = {
    "milan": "ODbL 1.0 (Telecom Italia Big Data Challenge, Harvard Dataverse)",
    "grid": "ODbL 1.0 (Telecom Italia Big Data Challenge, Harvard Dataverse)",
    "itu": "Not stated in the mirror; ITU AI/ML in 5G Challenge data, research only (ISSUES I4)",
    "slovak": "CC BY 4.0 (Lehoczky et al., Sci Data 2026; Zenodo 10.5281/zenodo.17815388)",
    "prices": "Energy-Charts: private and internal use only; do not publish (FINDINGS G10)",
}

MILAN_COLUMNS = ["square_id", "time_ms", "country", "sms_in", "sms_out",
                 "call_in", "call_out", "internet"]
ACTIVITY = ["sms_in", "sms_out", "call_in", "call_out", "internet"]

USER_AGENT = "yovahti-research/0.1 (dataset download)"


# ---------------------------------------------------------------- helpers

def _client() -> httpx.Client:
    return httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, read=300),
                        headers={"User-Agent": USER_AGENT})


def _stream_to(client: httpx.Client, url: str, dest: Path) -> tuple[str, int]:
    """Stream url to dest atomically (via a .part file); return (sha256, bytes).

    A failed download never leaves a file at dest, so "already present" checks stay honest.
    """
    h = hashlib.sha256()
    n = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with client.stream("GET", url) as r:
            r.raise_for_status()
            with part.open("wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
                    h.update(chunk)
                    n += len(chunk)
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    return h.hexdigest(), n


def _record(key: str, entry: dict) -> None:
    manifest = RAW / "MANIFEST.json"
    RAW.mkdir(parents=True, exist_ok=True)
    data = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    entry = {**entry, "licence": LICENCES[key.split(":")[0]],
             "retrieved": datetime.now(UTC).isoformat(timespec="seconds")}
    data[key] = entry
    manifest.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _dataverse_files(client: httpx.Client, doi: str) -> list[dict]:
    r = client.get(f"{DATAVERSE}/datasets/:persistentId/", params={"persistentId": doi})
    r.raise_for_status()
    return [f["dataFile"] for f in r.json()["data"]["latestVersion"]["files"]]


def _env() -> dict[str, str]:
    """Read KEY=VALUE lines from the git-ignored .env at the repo root (no shell expansion)."""
    env = ROOT / ".env"
    if not env.exists():
        return {}
    out = {}
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _guestbook_url(client: httpx.Client, file_id: int) -> str:
    """Submit the dataset's guestbook (details from .env) and return a signed download URL.

    The Milan files require a guestbook response (G11). Frank approved sending his details.
    """
    env = _env()
    keys = ["name", "email", "institution", "position"]
    resp = {k: env.get(f"DATAVERSE_GB_{k.upper()}", "") for k in keys}
    if not resp["name"] or not resp["email"]:
        raise SystemExit("Set DATAVERSE_GB_NAME and DATAVERSE_GB_EMAIL in .env (see .env.example)")
    r = client.post(f"{DATAVERSE}/access/datafile/{file_id}",
                    json={"guestbookResponse": resp})
    r.raise_for_status()
    return r.json()["data"]["signedUrl"]


def _public_url(file_id: int) -> str:
    """The URL recorded in the manifest (signed URLs expire and carry a token)."""
    return f"{DATAVERSE}/access/datafile/{file_id}"


# ---------------------------------------------------------------- datasets

def download_itu() -> None:
    out = RAW / "itu"
    if (out / "ECdata.csv").exists():
        print("itu: already present")
        return
    with _client() as c, tempfile.TemporaryDirectory() as tmp:
        z = Path(tmp) / "itu.zip"
        sha, n = _stream_to(c, ITU_ZIP, z)
        with zipfile.ZipFile(z) as zf:
            for member in zf.namelist():
                name = Path(member).name
                if name.endswith(".csv"):  # flat extract, no paths from the archive
                    (out / name).parent.mkdir(parents=True, exist_ok=True)
                    (out / name).write_bytes(zf.read(member))
    _record("itu", {"url": ITU_ZIP, "sha256": sha, "bytes": n})
    print(f"itu: {n / 1e6:.1f} MB -> {out}")


def download_slovak() -> None:
    """Real 15-min cell-level PM counters with radio-unit and baseband energy (primary, D19)."""
    out = RAW / "slovakia"
    with _client() as c:
        for name in SLOVAK_FILES:
            dest = out / name
            if dest.exists():
                print(f"slovak {name}: already present")
                continue
            url = f"https://zenodo.org/records/{SLOVAK_RECORD}/files/{name}?download=1"
            sha, n = _stream_to(c, url, dest)
            if name.endswith(".zip"):
                with zipfile.ZipFile(dest) as zf:
                    for member in zf.namelist():
                        parts = Path(member).parts
                        if member.endswith(".csv") and ".." not in parts:
                            target = out / Path(*parts)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(zf.read(member))
            _record(f"slovak:{name}", {"url": url, "sha256": sha, "bytes": n})
            print(f"slovak {name}: {n / 1e6:.1f} MB", flush=True)


def download_grid() -> None:
    dest = RAW / "milan" / "milano-grid.geojson"
    if dest.exists():
        print("grid: already present")
        return
    with _client() as c:
        (f,) = _dataverse_files(c, GRID_DOI)
        url = _public_url(f["id"])
        sha, n = _stream_to(c, _guestbook_url(c, f["id"]), dest)
    _record("grid", {"url": url, "doi": GRID_DOI, "sha256": sha, "bytes": n})
    print(f"grid: {n / 1e6:.1f} MB -> {dest}")


def _process_milan_day(raw: Path, out: Path) -> int:
    df = pd.read_csv(raw, sep="\t", header=None, names=MILAN_COLUMNS,
                     dtype={"square_id": "int32", "time_ms": "int64", "country": "float32",
                            **{a: "float32" for a in ACTIVITY}})
    agg = df.groupby(["square_id", "time_ms"], as_index=False)[ACTIVITY].sum(min_count=1)
    agg["time"] = pd.to_datetime(agg.pop("time_ms"), unit="ms", utc=True)
    agg = agg[["square_id", "time", *ACTIVITY]]
    out.parent.mkdir(parents=True, exist_ok=True)
    agg.to_parquet(out, index=False, compression="zstd")
    return len(agg)


def download_milan(days: int | None = None) -> None:
    out_dir = PROCESSED / "milan"
    with _client() as c:
        files = sorted(_dataverse_files(c, MILAN_DOI), key=lambda f: f["filename"])
        if days:
            files = files[:days]
        for i, f in enumerate(files, 1):
            day = f["filename"].removeprefix("sms-call-internet-mi-").removesuffix(".txt")
            out = out_dir / f"{day}.parquet"
            if out.exists():
                print(f"milan {i}/{len(files)} {day}: done earlier")
                continue
            url = _public_url(f["id"])
            t0 = datetime.now()
            with tempfile.TemporaryDirectory() as tmp:
                raw = Path(tmp) / f["filename"]
                sha, n = _stream_to(c, _guestbook_url(c, f["id"]), raw)
                rows = _process_milan_day(raw, out)
            secs = (datetime.now() - t0).total_seconds()
            _record(f"milan:{day}", {"url": url, "doi": MILAN_DOI, "sha256": sha, "bytes": n,
                                     "rows_processed": rows})
            print(f"milan {i}/{len(files)} {day}: {n / 1e6:.0f} MB in {secs:.0f}s, "
                  f"{rows:,} rows, {out.stat().st_size / 1e6:.1f} MB parquet", flush=True)


def download_prices(start: date, end: date) -> None:
    """Finnish day-ahead prices (EUR/MWh), month by month. Development use only (G10)."""
    frames = []
    with _client() as c:
        cur = start
        while cur <= end:
            # Few, large requests: the API rate-limits bursts of small ones (429).
            nxt = min(cur + timedelta(days=120), end + timedelta(days=1))
            params = {"bzn": "FI", "start": cur.isoformat(),
                      "end": (nxt - timedelta(days=1)).isoformat()}
            for attempt in range(6):
                r = c.get(PRICES_API, params=params)
                if r.status_code != 429:
                    break
                wait = 15 * 2**attempt
                print(f"prices: rate-limited, waiting {wait}s", flush=True)
                time.sleep(wait)
            r.raise_for_status()
            j = r.json()
            frames.append(pd.DataFrame({
                "time": pd.to_datetime(j["unix_seconds"], unit="s", utc=True),
                "eur_mwh": pd.array(j["price"], dtype="Float64"),
            }))
            cur = nxt
    df = pd.concat(frames).drop_duplicates("time").sort_values("time")
    out = PROCESSED / "prices" / "fi_day_ahead.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    _record("prices", {"url": PRICES_API, "params": {"bzn": "FI", "start": str(start),
                                                     "end": str(end)}, "rows": len(df)})
    step = df["time"].diff().dropna().value_counts().head(3).to_dict()
    print(f"prices: {len(df):,} rows {df['time'].min()} .. {df['time'].max()}, steps {step}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("dataset", choices=["itu", "grid", "milan", "prices", "slovak", "all"])
    p.add_argument("--days", type=int, help="milan: only the first N days")
    p.add_argument("--start", type=date.fromisoformat, default=date(2025, 10, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date(2026, 11, 22))
    a = p.parse_args(argv)
    if a.dataset in ("itu", "all"):
        download_itu()
    if a.dataset in ("grid", "all"):
        download_grid()
    if a.dataset in ("prices", "all"):
        download_prices(a.start, a.end)
    if a.dataset in ("slovak", "all"):
        download_slovak()
    if a.dataset in ("milan", "all"):
        download_milan(a.days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
