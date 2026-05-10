"""Smoke tests: every famous transition in NSE history must reconcile.

Run from the repo root:

    python -m pytest tests/

These are the same 13 cases the validator's "famous transitions" gate uses.
A failure here means the published CSV no longer reflects ground truth.
"""
from __future__ import annotations
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
INDEX_CSV = ROOT / "index_history" / "data" / "index_membership_history.csv"
FNO_CSV = ROOT / "fno_history" / "data" / "fno_membership_history.csv"


@pytest.fixture(scope="module")
def idx() -> pd.DataFrame:
    return pd.read_csv(INDEX_CSV, parse_dates=["valid_from", "valid_to"])


@pytest.fixture(scope="module")
def fno() -> pd.DataFrame:
    return pd.read_csv(FNO_CSV, parse_dates=["valid_from", "valid_to"])


def _is_member(df: pd.DataFrame, index_name: str, symbol: str, on: date) -> bool:
    on_ts = pd.Timestamp(on)
    sub = df[(df.index_name == index_name) & (df.symbol == symbol)]
    return bool(((sub.valid_from <= on_ts) & (sub.valid_to.isna() | (sub.valid_to > on_ts))).any())


# (description, index_name, symbol, on_date, expected_member?)
FAMOUS = [
    ("HDFC absent post-merger",                          "Nifty 50",  "HDFC",       date(2023, 7, 14), False),
    ("HDFCBANK still in Nifty 50 on merger day",         "Nifty 50",  "HDFCBANK",   date(2023, 7, 14), True),
    ("SHRIRAMFIN added 2024-03-28",                      "Nifty 50",  "SHRIRAMFIN", date(2024, 3, 28), True),
    ("UPL excluded 2024-03-28",                          "Nifty 50",  "UPL",        date(2024, 3, 28), False),
    ("BPCL was member on 2022-01-01",                    "Nifty 50",  "BPCL",       date(2022, 1, 1),  True),
    ("ETERNAL (was ZOMATO) joined Nifty 50 in Mar 2025", "Nifty 50",  "ETERNAL",    date(2025, 4, 1),  True),
    ("ETERNAL not in Nifty 50 pre-Mar 2025",             "Nifty 50",  "ETERNAL",    date(2024, 12, 31), False),
    ("INDIGO joined Nifty 50 on 2025-09-30",             "Nifty 50",  "INDIGO",     date(2025, 10, 1), True),
    ("MAXHEALTH joined Nifty 50 on 2025-09-30",          "Nifty 50",  "MAXHEALTH",  date(2025, 10, 1), True),
    ("HEROMOTOCO excluded from Nifty 50 on 2025-09-30",  "Nifty 50",  "HEROMOTOCO", date(2025, 10, 1), False),
    ("INDUSINDBK excluded from Nifty 50 on 2025-09-30",  "Nifty 50",  "INDUSINDBK", date(2025, 10, 1), False),
    ("ATGL (was ADANIGAS) member of Nifty 500 in 2021",  "Nifty 500", "ATGL",       date(2021, 6, 1),  True),
    # Symbols are stored canonically (terminal name in the rename chain). MINDTREE
    # → LTIMindtree (LTIM, 2022) → LTM (2026). Query as LTM, not the legacy alias.
    ("LTM (Mindtree lineage) member of Nifty 500 in 2022", "Nifty 500", "LTM",      date(2022, 12, 31), True),
]


@pytest.mark.parametrize("desc,index_name,symbol,on,expected", FAMOUS)
def test_famous_transition(idx, desc, index_name, symbol, on, expected):
    actual = _is_member(idx, index_name, symbol, on)
    assert actual == expected, f"{desc}: expected={expected}, got={actual}"


def test_nifty50_size_today(idx):
    """Nifty 50 must have exactly 50 currently-open intervals."""
    open_today = idx[(idx.index_name == "Nifty 50") & idx.valid_to.isna()]
    assert len(open_today) == 50, f"Nifty 50 has {len(open_today)} open intervals, expected 50"


def test_fno_known_introductions(fno):
    """F&O introductions that are publicly documented and must reconcile."""
    cases = [
        ("ZOMATO",     date(2024, 11, 29), True),   # NSE/FAOP/65295
        ("JIOFIN",     date(2024, 11, 29), True),
        ("HDIL",       date(2018, 4, 28),  False),  # excluded 2018-04-27
    ]
    for sym, on, expected in cases:
        on_ts = pd.Timestamp(on)
        sub = fno[fno.symbol == sym]
        is_member = bool(((sub.valid_from <= on_ts) & (sub.valid_to.isna() | (sub.valid_to > on_ts))).any())
        assert is_member == expected, f"{sym} F&O on {on}: expected={expected}, got={is_member}"


def test_csv_has_expected_columns(idx, fno):
    assert set(idx.columns) >= {"index_id", "index_name", "symbol", "valid_from", "valid_to"}
    assert set(fno.columns) >= {"symbol", "valid_from", "valid_to"}
