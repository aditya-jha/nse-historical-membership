"""F&O build rules — each test pins a bug found in the 2026-10-09 reconciliation of the
published CSV against NSE's live F&O list (fo_mktlots.csv)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from fno_history.code.build_history import build_intervals, canon
from fno_history.code.parse_circulars import SYMBOL_ROW_PATTERNS

FNO_CSV = Path(__file__).resolve().parent.parent / "fno_history" / "data" / "fno_membership_history.csv"


def _ev(kind, eff, *syms, circ=None):
    return {"kind": kind, "effective_date": eff, "symbols": list(syms), "circular_no": circ}


def _member(intervals, sym, d):
    d = date.fromisoformat(d)
    return any(r["symbol"] == sym and r["valid_from"] <= d and (r["valid_to"] is None or r["valid_to"] > d)
               for r in intervals)


def test_withdrawal_cancels_announced_introduction():
    # GLAND / CASTROLIND: introduced for 2025-01-31, withdrawn before it took effect
    iv = build_intervals([_ev("introduction", "2025-01-31", "GLAND", "CASTROLIND"),
                          _ev("withdrawal", "2025-01-31", "GLAND", "CASTROLIND")])
    assert iv == []


def test_withdrawal_before_its_introduction_suppresses_it():
    iv = build_intervals([_ev("withdrawal", "2025-05-30", "FSL"),
                          _ev("introduction", "2025-05-30", "FSL")])
    assert iv == []


def test_same_date_reannouncement_is_not_a_zero_length_interval():
    iv = build_intervals([_ev("introduction", "2021-01-01", "AARTIIND"),
                          _ev("introduction", "2021-01-01", "AARTIIND", "ALKEM")])
    assert [r["symbol"] for r in iv if r["symbol"] == "AARTIIND"] == ["AARTIIND"]
    assert all(r["valid_to"] is None or r["valid_to"] > r["valid_from"] for r in iv)


def test_exclusion_under_new_name_closes_old_name_interval():
    # PVR (2017) was renamed PVRINOX; the 2025 exclusion names PVRINOX
    assert canon("PVR") == "PVRINOX" and canon("LTI") == "LTM"
    iv = build_intervals([_ev("introduction", "2017-03-31", "PVR"),
                          _ev("exclusion", "2025-02-28", "PVRINOX")])
    assert len(iv) == 1 and iv[0]["symbol"] == "PVR" and iv[0]["valid_to"] == date(2025, 2, 28)


def test_symbol_may_start_with_a_digit_but_lot_sizes_never_match():
    line = "1 360 ONE WAM LIMITED 360ONE 500"
    hits = [h for p in SYMBOL_ROW_PATTERNS for h in p.findall(line)]
    assert "360ONE" in hits and "500" not in hits


@pytest.fixture(scope="module")
def fno():
    return pd.read_csv(FNO_CSV, parse_dates=["valid_from", "valid_to"])


@pytest.mark.parametrize("sym,on,expected", [
    ("CASTROLIND", "2025-06-30", False),   # withdrawn introduction (FAOP/66262)
    ("GLAND", "2025-06-30", False),
    ("ARE&M", "2025-06-30", False),        # withdrawn (FAOP/66760)
    ("FSL", "2025-09-30", False),          # withdrawn (FAOP/68129)
    ("SUPREMEIND", "2022-06-30", False),   # withdrawn (FAOP/50812)
    ("CONCOR", "2024-06-28", True),        # its 2023 exclusion was itself withdrawn (FAOP/57624)
    ("GSPL", "2023-06-30", False),         # excluded 2022-11-25 (FAOP/53878)
    ("CAPF", "2019-06-28", False),         # discontinued 2018-12-28 (FAOP/39715)
    ("HCC", "2019-06-28", False),          # last F&O contracts 2018-11-29 (bhavcopy; manual event)
    ("KPIT", "2020-06-30", False),         # renamed BSOFT, excluded 2019-09-27
    ("PVR", "2025-06-30", False),          # renamed PVRINOX, excluded 2025-02-28
    ("360ONE", "2025-09-30", True),        # introduced 2025-06-27 (FAOP/68764)
    ("ATHERENERG", "2026-07-31", False),   # introduced 2026-08-26 (FAOP/75371)
    ("ATHERENERG", "2026-09-30", True),
    ("MAHABANK", "2026-05-29", False),
    ("MAHABANK", "2026-09-30", True),
])
def test_published_csv_transitions(fno, sym, on, expected):
    d = pd.Timestamp(on)
    rows = fno[fno.symbol == sym]
    member = bool(((rows.valid_from <= d) & (rows.valid_to.isna() | (rows.valid_to > d))).any())
    assert member is expected
