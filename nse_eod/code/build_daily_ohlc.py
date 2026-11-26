"""Consolidate per-day bhavcopy CSVs into a long-format parquet/CSV.

Output schema:
    symbol str
    date   date
    series str   (EQ, SM, BE, BZ, ST)
    open / high / low / close / last / prev_close / avg_price  float
    volume_shares  int
    turnover_inr   float
    n_trades       int
    deliv_qty      int    (delivery quantity; None for SME/T2T rows NSE leaves "-")
    deliv_pct      float
    band_pct       float  (price band in force that day: 2/5/10/20; NaN = "No Band", e.g. F&O)
    upper_hit / lower_hit      bool  high (low) touched the band price
    upper_close / lower_close  bool  closed at the band price ("circuit hitter")

Band columns need `fetch_bhavcopy --dataset bands`; without band files they are NaN/False.

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
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BHAVCOPY_DIR = ROOT / "data" / "bhavcopy"
BANDS_DIR = ROOT / "data" / "price_bands"
# Slack for NSE rounding the band price = one tick. Ticks read off the closes themselves: ₹0.05
# everywhere until 2024-06-07, then ₹0.01 below ₹250 from 2024-06-10 (share of sub-₹250 closes off
# the 0.05 grid jumps 8% → 65% that day).
# shortcut: ~8% of sub-₹250 closes were on 0.01 steps before the switch too; they get the looser
# 0.05 slack. Use exact per-security ticks if those matter.
TICK_SWITCH = date(2024, 6, 10)
BAND_TOL = 0.05  # widest tick, used by band_breach_rate
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
                    "deliv_qty":     inum("DELIV_QTY") if "DELIV_QTY" in idx else None,
                    "deliv_pct":     fnum("DELIV_PER") if "DELIV_PER" in idx else None,
                })
            except (ValueError, IndexError):
                continue
    return rows


def load_bands(bands_dir: Path = BANDS_DIR) -> pd.DataFrame:
    """All `sec_list_DDMMYYYY.csv` files → (date, symbol, series, band_pct); `date` is the FILE's date.

    NSE publishes file D after the close for the next session; use `bands_in_force` to re-date it.
    """
    frames = []
    for p in sorted(bands_dir.glob("sec_list_*.csv")):
        if p.stat().st_size == 0:  # holiday marker
            continue
        # latin-1: some files carry cp1252 bytes in Security Name, a column we never read
        b = pd.read_csv(p, dtype=str, skipinitialspace=True, encoding="latin-1")
        b.columns = [c.strip() for c in b.columns]
        frames.append(pd.DataFrame({
            "date": datetime.strptime(p.stem.split("_")[-1], "%d%m%Y").date(),
            "symbol": b["Symbol"].str.strip(),
            "series": b["Series"].str.strip(),
            "band_pct": pd.to_numeric(b["Band"].str.strip(), errors="coerce"),  # "No Band" → NaN
        }))
    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "series", "band_pct"])
    return pd.concat(frames, ignore_index=True).drop_duplicates(["date", "symbol", "series"])


def bands_in_force(bands: pd.DataFrame, sessions) -> pd.DataFrame:
    """Re-date each band file to the first trading session after its file date.

    Evidence (2020-2026, 14,660 band cuts): on the file's own date 68% of cut stocks still moved
    past the new smaller band; on the next session 3.8% did. A missing file therefore leaves its
    next session without bands instead of shifting every later file.
    """
    sessions = pd.Index(sorted(sessions))
    pos = sessions.searchsorted(pd.Index(bands.date), side="right")
    ok = pos < len(sessions)
    return bands[ok].assign(date=sessions[pos[ok]])


def add_circuit_flags(df: pd.DataFrame, bands: pd.DataFrame) -> pd.DataFrame:
    """Join the day's band and flag rows that touched / closed at the upper or lower band."""
    out = df.drop(columns=["band_pct"], errors="ignore").merge(
        bands, on=["date", "symbol", "series"], how="left")
    tick = 0.05 - 0.04 * ((pd.to_datetime(out.date) >= pd.Timestamp(TICK_SWITCH))
                          & (out.prev_close < 250))
    up = out.prev_close * (1 + out.band_pct / 100) - tick
    lo = out.prev_close * (1 - out.band_pct / 100) + tick
    # The price must actually move: when the band is under one tick, unchanged is not a circuit.
    rose, fell = out.prev_close + 1e-9, out.prev_close - 1e-9
    out["upper_hit"] = ((out.high >= up) & (out.high > rose)).fillna(False).astype(bool)
    out["upper_close"] = ((out.close >= up) & (out.close > rose)).fillna(False).astype(bool)
    out["lower_hit"] = ((out.low <= lo) & (out.low < fell)).fillna(False).astype(bool)
    out["lower_close"] = ((out.close <= lo) & (out.close < fell)).fillna(False).astype(bool)
    return out


def band_breach_rate(df: pd.DataFrame) -> float:
    """Share of banded rows whose high/low went past the band: ≈0 when bands are dated correctly."""
    b = df[df.band_pct.notna() & df.prev_close.gt(0)]
    move = (b[["high", "low"]].sub(b.prev_close, axis=0).abs().max(axis=1)
            - b.prev_close * b.band_pct / 100)
    return float((move > 2 * BAND_TOL + 0.005 * b.prev_close).mean()) if len(b) else float("nan")


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
    # A holiday-dated copy of the previous session (older fetches saved those) repeats its rows.
    n_dup = df.duplicated(["symbol", "date", "series"]).sum()
    if n_dup:
        df = df.drop_duplicates(["symbol", "date", "series"]).reset_index(drop=True)
        print(f"Dropped {n_dup:,} duplicate rows (holiday-dated copies of a previous session)")
    print(f"\nTotal rows: {len(df):,}  unique_symbols: {df.symbol.nunique():,}  "
          f"date_range: {df.date.min()} → {df.date.max()}")
    print(f"Series breakdown: {df.series.value_counts().to_dict()}")
    if n_skipped:
        print(f"Skipped {n_skipped} files with unrecognised schema")

    raw_bands = load_bands()
    if len(raw_bands):
        bands = bands_in_force(raw_bands, df.date.unique())
        df = add_circuit_flags(df, bands)
        # Dating check: the correct dating should have the lower breach rate.
        print(f"Bands: {raw_bands.date.nunique()} files, band matched on "
              f"{df.band_pct.notna().mean():.1%} of rows; breach rate {band_breach_rate(df):.4%} "
              f"(file applied to its own date instead: "
              f"{band_breach_rate(add_circuit_flags(df, raw_bands)):.4%})")
        print(f"Upper-circuit closes: {df.upper_close.sum():,}  lower-circuit closes: {df.lower_close.sum():,}")

    df.to_parquet(OUT_PARQUET, index=False)
    print(f"→ {OUT_PARQUET}  ({OUT_PARQUET.stat().st_size / 1e6:.1f} MB)")
    if args.csv:
        df.to_csv(OUT_CSV, index=False)
        print(f"→ {OUT_CSV}  ({OUT_CSV.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
