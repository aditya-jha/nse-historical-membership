"""Circuit flags in nse_eod.build_daily_ohlc, on rows with known answers."""
from datetime import date

import pandas as pd

from nse_eod.code.build_daily_ohlc import add_circuit_flags, band_breach_rate

D = date(2026, 11, 25)


def _rows():
    # symbol, series, prev_close, high, low, close
    return pd.DataFrame([
        # prices from the real 25-Nov-2026 HMAAGRO row (+10% exactly), scored against a 10% band
        ("HMAAGRO", "EQ", 40.03, 44.03, 38.67, 44.03),
        ("TOUCHUP", "EQ", 100.00, 105.00, 99.00, 101.00),   # 5% band: touched, closed below
        ("LOCKDN", "BE", 50.00, 50.00, 47.50, 47.50),       # 5% band: closed at lower band
        ("QUIET", "EQ", 200.00, 204.00, 198.00, 202.00),    # 20% band: nothing
        ("FNOSTK", "EQ", 1000.00, 1150.00, 990.00, 1140.00),  # No Band (F&O): never flagged
        # real 25-Nov-2026 rows that a flat ₹0.05 slack wrongly flagged (₹0.01 ticks by then):
        ("DHARAN", "BZ", 0.12, 0.13, 0.12, 0.12),    # 5% band < 1 tick: touched +1 tick, closed flat
        ("EMPOWER", "EQ", 0.99, 1.03, 0.99, 1.00),   # 5% band = 1.0395: touched 1.03, closed +1%
    ], columns=["symbol", "series", "prev_close", "high", "low", "close"]).assign(date=D)


def _bands():
    return pd.DataFrame({
        "date": D,
        "symbol": ["HMAAGRO", "TOUCHUP", "LOCKDN", "QUIET", "FNOSTK", "DHARAN", "EMPOWER"],
        "series": ["EQ", "EQ", "BE", "EQ", "EQ", "BZ", "EQ"],
        "band_pct": [10.0, 5.0, 5.0, 20.0, float("nan"), 5.0, 5.0],
    })


def test_flags():
    out = add_circuit_flags(_rows(), _bands()).set_index("symbol")
    assert out.loc["HMAAGRO", ["upper_hit", "upper_close"]].all()
    assert out.loc["TOUCHUP", "upper_hit"] and not out.loc["TOUCHUP", "upper_close"]
    assert out.loc["LOCKDN", ["lower_hit", "lower_close"]].all()
    flags = ["upper_hit", "upper_close", "lower_hit", "lower_close"]
    assert not out.loc[["QUIET", "FNOSTK"], flags].any().any()
    for s in ("DHARAN", "EMPOWER"):
        assert out.loc[s, "upper_hit"] and not out.loc[s, "upper_close"], s


def test_series_must_match():
    # A band listed for the BE series must not attach to an EQ row of the same symbol.
    bands = _bands().assign(series="BE")
    out = add_circuit_flags(_rows(), bands).set_index("symbol")
    assert out.loc["HMAAGRO", "band_pct"] != out.loc["HMAAGRO", "band_pct"]  # NaN
    assert not out.loc["HMAAGRO", "upper_close"]


def test_breach_rate_flags_wrong_band():
    out = add_circuit_flags(_rows(), _bands())
    assert band_breach_rate(out) == 0.0
    # Under the old 20% band HMAAGRO is fine; under a 2% band it breaches.
    wrong = _bands().assign(band_pct=[2.0, 5.0, 5.0, 20.0, float("nan"), 5.0, 5.0])
    assert band_breach_rate(add_circuit_flags(_rows(), wrong)) > 0


def test_holiday_copy_is_detected():
    from nse_eod.code.fetch_bhavcopy import _file_date
    # What NSE serves for 26-Jan-2024 (Republic Day): the 25-Jan session.
    text = ("SYMBOL, SERIES, DATE1, PREV_CLOSE\n"
            "20MICRONS, EQ, 25-Jan-2024, 180.44\n")
    assert _file_date(text) == date(2024, 1, 25)
    assert _file_date("SYMBOL\n") is None


def test_band_file_applies_to_next_session():
    from nse_eod.code.build_daily_ohlc import bands_in_force
    # Files for Fri 23-Jan-2026 and Tue 27-Jan-2026; Mon 26-Jan is a holiday, so the
    # Friday file is in force on Tuesday and Tuesday's on Wednesday. The last file has no
    # session after it yet and is dropped.
    sessions = [date(2026, 1, 23), date(2026, 1, 27), date(2026, 1, 28)]
    files = pd.DataFrame({"date": [date(2026, 1, 23), date(2026, 1, 27), date(2026, 1, 28)],
                          "symbol": "X", "series": "EQ", "band_pct": [20.0, 10.0, 5.0]})
    out = bands_in_force(files, sessions)
    assert list(pd.to_datetime(out.date).dt.date) == [date(2026, 1, 27), date(2026, 1, 28)]
    assert list(out.band_pct) == [20.0, 10.0]
