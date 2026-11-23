"""Slovak processing: published columns map to the common schema; blanks stay missing."""

import pandas as pd
import pytest

from yovahti.data.slovak import process_file, rename_columns

LTE = (
    "Base station,Sector,Timestamp,Radio unit energy consumption,Baseband energy consumption,"
    "4G max active users DL,4G max active users UL,4G data volume DL,4G data volume UL,"
    "4G max RRC users,4G RB utilization,4G CQI rank 1,4G CQI rank 2,4G CQI rank 3,"
    "4G CQI rank 4,4G RRC users,4G active users UL,4G active users DL,4G MIMO rank DL\n"
    "B_1,1,2025-09-01 00:00:00,40,80,3,2,100.5,10,9,12.5,10,9,,,8,1,2,1.5\n"
    "B_1,1,2025-09-01 00:15:00,41,81,3,2,90,9,9,,10,9,,,8,1,2,1.4\n"
)


def test_process_lte(tmp_path):
    d = tmp_path / "Baseband_02"
    d.mkdir()
    f = d / "Dataset_03_LTE_1800.csv"
    f.write_text(LTE)
    df = process_file(f)
    assert list(df.columns[:8]) == ["site", "sector", "time", "dataset", "baseband", "tech",
                                    "band_mhz", "bandwidth_mhz"]
    assert df["tech"].iloc[0] == "LTE" and df["band_mhz"].iloc[0] == 1800
    assert df["bandwidth_mhz"].iloc[0] == 20
    assert df["rb_util_pct"].iloc[0] == pytest.approx(12.5)
    assert pd.isna(df["rb_util_pct"].iloc[1])  # blank stays missing
    assert str(df["time"].dt.tz) == "UTC"


def test_gsm_and_nr_columns_map():
    m = rename_columns(["2G TS utilization", "5G RB utilization", "Sector"])
    assert m == {"2G TS utilization": "ts_util_pct", "5G RB utilization": "rb_util_pct",
                 "Sector": "sector"}


def test_unknown_column_is_an_error():
    with pytest.raises(ValueError):
        rename_columns(["4G something new"])
