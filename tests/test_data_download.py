"""Milan processing: country rows are summed per (square, interval); blanks stay missing."""

import pandas as pd

from yovahti.data.download import _process_milan_day

# square, time_ms, country, sms_in, sms_out, call_in, call_out, internet (tab-separated, blanks)
RAW = (
    "1\t1383260400000\t0\t0.1\t\t\t\t1.0\n"
    "1\t1383260400000\t39\t0.2\t0.3\t0.4\t0.5\t2.0\n"
    "1\t1383261000000\t39\t\t\t\t\t\n"
    "2\t1383260400000\t39\t1.0\t1.0\t1.0\t1.0\t5.0\n"
)


def test_aggregates_countries(tmp_path):
    raw = tmp_path / "day.txt"
    raw.write_text(RAW)
    out = tmp_path / "day.parquet"
    assert _process_milan_day(raw, out) == 3
    df = pd.read_parquet(out).set_index(["square_id", "time"])
    t0 = pd.Timestamp(1383260400000, unit="ms", tz="UTC")
    t1 = pd.Timestamp(1383261000000, unit="ms", tz="UTC")
    assert df.loc[(1, t0), "internet"] == 3.0
    assert abs(df.loc[(1, t0), "sms_in"] - 0.3) < 1e-6
    assert df.loc[(1, t0), "sms_out"] == 0.3  # one blank + one value -> the value
    assert pd.isna(df.loc[(1, t1), "internet"])  # all blank -> missing, not zero
    assert df.loc[(2, t0), "internet"] == 5.0


def test_failed_download_leaves_no_file(tmp_path):
    import httpx
    import pytest

    from yovahti.data.download import _stream_to

    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(400)))
    dest = tmp_path / "f.bin"
    with pytest.raises(httpx.HTTPStatusError):
        _stream_to(client, "https://example.invalid/f", dest)
    assert not dest.exists()
    assert not list(tmp_path.iterdir())
