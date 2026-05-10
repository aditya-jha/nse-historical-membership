"""Quickstart: 5 things you can do with this dataset in 30 lines.

Run from the repo root:

    python examples/quickstart.py
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
INDEX_CSV = ROOT / "index_history" / "data" / "index_membership_history.csv"
FNO_CSV = ROOT / "fno_history" / "data" / "fno_membership_history.csv"


def member(df: pd.DataFrame, index_name: str, symbol: str, on: str) -> bool:
    """Was `symbol` in `index_name` on date `on` (YYYY-MM-DD)?"""
    on_ts = pd.Timestamp(on)
    sub = df[(df.index_name == index_name) & (df.symbol == symbol)]
    return bool(((sub.valid_from <= on_ts) & (sub.valid_to.isna() | (sub.valid_to > on_ts))).any())


def members_on(df: pd.DataFrame, index_name: str, on: str) -> set[str]:
    """All symbols in `index_name` on `on`."""
    on_ts = pd.Timestamp(on)
    sub = df[df.index_name == index_name]
    mask = (sub.valid_from <= on_ts) & (sub.valid_to.isna() | (sub.valid_to > on_ts))
    return set(sub.loc[mask, "symbol"])


def changes_between(df: pd.DataFrame, index_name: str, start: str, end: str) -> dict[str, set[str]]:
    a, b = members_on(df, index_name, start), members_on(df, index_name, end)
    return {"added": b - a, "removed": a - b}


if __name__ == "__main__":
    idx = pd.read_csv(INDEX_CSV, parse_dates=["valid_from", "valid_to"])
    fno = pd.read_csv(FNO_CSV, parse_dates=["valid_from", "valid_to"])

    print("=== 1. Was HDFC in Nifty 50 the day before/after the merger? ===")
    print(f"  HDFC in Nifty 50 on 2023-07-12: {member(idx, 'Nifty 50', 'HDFC', '2023-07-12')}")
    print(f"  HDFC in Nifty 50 on 2023-07-14: {member(idx, 'Nifty 50', 'HDFC', '2023-07-14')}")

    print("\n=== 2. What did Nifty 50 look like on 2020-04-01 (post-COVID) ===")
    syms = sorted(members_on(idx, "Nifty 50", "2020-04-01"))
    print(f"  {len(syms)} members. First 10: {syms[:10]}")

    print("\n=== 3. Nifty 500 churn between 2020 and 2024 ===")
    delta = changes_between(idx, "Nifty 500", "2020-01-01", "2024-01-01")
    print(f"  Added in this window:   {len(delta['added'])} symbols")
    print(f"  Removed in this window: {len(delta['removed'])} symbols")
    print(f"  Sample additions:       {sorted(delta['added'])[:5]}")

    print("\n=== 4. When did ZOMATO/ETERNAL enter Nifty 50? ===")
    e = idx[(idx.symbol == "ETERNAL") & (idx.index_name == "Nifty 50")]
    print(e[["valid_from", "valid_to"]].to_string(index=False))

    print("\n=== 5. F&O: was JIOFIN tradeable in F&O on 2024-12-15? ===")
    on_ts = pd.Timestamp("2024-12-15")
    j = fno[(fno.symbol == "JIOFIN")
            & (fno.valid_from <= on_ts)
            & (fno.valid_to.isna() | (fno.valid_to > on_ts))]
    print(f"  JIOFIN F&O on 2024-12-15: {not j.empty}  (introduced {j.valid_from.iloc[0].date() if not j.empty else 'n/a'})")
