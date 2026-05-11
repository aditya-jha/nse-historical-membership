"""Consolidate per-day bhavcopy CSVs into a long-format parquet/CSV.

Output schema:
    symbol str
    date   date
    series str   (EQ, SM, BE, BZ, ST)
    open / high / low / close / last / prev_close / avg_price  float
    volume_shares  int
    turnover_inr   float
    n_trades       int

Filters:
  * series ∈ {EQ, SM, BE, BZ, ST}  (drops GS / GB gov bonds, others)
  * skips empty (holiday-marker) files

Run:
    python -m nse_eod.code.build_daily_ohlc            # writes parquet
    python -m nse_eod.code.build_daily_ohlc --csv      # also writes long-form CSV
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BHAVCOPY_DIR = ROOT / "data" / "bhavcopy"
OUT_PARQUET = ROOT / "data" / "_daily_ohlc.parquet"
OUT_CSV = ROOT / "data" / "_daily_ohlc.csv"

KEEP_SERIES = {"EQ", "SM", "BE", "BZ", "ST"}


def _parse_date(s: str) -> datetime | None:
    s = (s or "").strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _read_one(path: Path) -> list[dict]:
    if path.stat().st_size == 0:  # holiday marker
        return []
    rows: list[dict] = []
    with path.open() as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader, [])]
        idx = {name: i for i, name in enumerate(header)}
        # Required columns
        needed = ["SYMBOL", "SERIES", "DATE1",
                  "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE",
                  "LAST_PRICE", "CLOSE_PRICE", "AVG_PRICE",
                  "PREV_CLOSE", "TTL_TRD_QNTY", "TURNOVER_LACS", "NO_OF_TRADES"]
        if any(n not in idx for n in needed):
            return []  # unrecognised schema — skip
        for parts in reader:
            try:
                series = parts[idx["SERIES"]].strip()
                if series not in KEEP_SERIES:
                    continue
                d = _parse_date(parts[idx["DATE1"]])
                if d is None:
                    continue
                def fnum(name):
                    v = parts[idx[name]].strip().replace(",", "")
                    if v in ("", "-"):
                        return None
                    return float(v)
                def inum(name):
                    v = parts[idx[name]].strip().replace(",", "")
                    if v in ("", "-"):
                        return None
                    return int(float(v))
                rows.append({
                    "symbol": parts[idx["SYMBOL"]].strip(),
                    "date": d,
                    "series": series,
                    "open":   fnum("OPEN_PRICE"),
                    "high":   fnum("HIGH_PRICE"),
                    "low":    fnum("LOW_PRICE"),
                    "close":  fnum("CLOSE_PRICE"),
                    "last":   fnum("LAST_PRICE"),
                    "prev_close": fnum("PREV_CLOSE"),
                    "avg_price":  fnum("AVG_PRICE"),
                    "volume_shares": inum("TTL_TRD_QNTY"),
                    "turnover_inr":  (fnum("TURNOVER_LACS") or 0) * 1e5,
                    "n_trades":      inum("NO_OF_TRADES"),
                })
            except (ValueError, IndexError):
                continue
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true", help="Also write long-format CSV")
    args = ap.parse_args()

    files = sorted(BHAVCOPY_DIR.glob("sec_bhavdata_full_*.csv"))
    print(f"Reading {len(files)} bhavcopy files …")
    all_rows: list[dict] = []
    n_skipped = 0
    for i, p in enumerate(files, 1):
        rows = _read_one(p)
        if not rows and p.stat().st_size > 0:
            n_skipped += 1
        all_rows.extend(rows)
        if i % 200 == 0:
            print(f"  [{i:5d}/{len(files)}]  rows so far={len(all_rows):,}", flush=True)

    if not all_rows:
        print("No rows parsed.", file=sys.stderr)
        sys.exit(1)

    df = pd.DataFrame(all_rows)
    df = df.sort_values(["symbol", "date", "series"]).reset_index(drop=True)
    print(f"\nTotal rows: {len(df):,}  unique_symbols: {df.symbol.nunique():,}  "
          f"date_range: {df.date.min()} → {df.date.max()}")
    print(f"Series breakdown: {df.series.value_counts().to_dict()}")
    if n_skipped:
        print(f"Skipped {n_skipped} files with unrecognised schema")

    df.to_parquet(OUT_PARQUET, index=False)
    print(f"→ {OUT_PARQUET}  ({OUT_PARQUET.stat().st_size / 1e6:.1f} MB)")
    if args.csv:
        df.to_csv(OUT_CSV, index=False)
        print(f"→ {OUT_CSV}  ({OUT_CSV.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
