"""Build _qoq_delta.csv + _signals.csv from data/parsed/_flat.csv.

Emits a source-agnostic long/wide shareholding schema so downstream backtest
code can consume it directly, with deep history (typically 2018+ for
promoter/public, 2022+ for FII/DII).

Signal definitions:
  smart_money_score(t) = (fii(t) - fii(t-4)) + (dii(t) - dii(t-4))      ← 4Q-cumulative Δ
  promoter_d4q(t)     = promoter(t) - promoter(t-4)
  worst_promoter_qtr(t) = min over last 4 (promoter(t-i) - promoter(t-i-1))

`_qoq_delta.csv` is per-quarter Δ (used by the backtester to reconstruct the
top-decile screen at any historical quarter end).

`_signals.csv` is the LATEST-period snapshot per ticker.

Run:
    python -m shareholding_history.code.build_signals
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PARSED = ROOT / "data" / "parsed" / "_flat.csv"
OUT_DIR = ROOT / "data" / "parsed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

QOQ_OUT = OUT_DIR / "_qoq_delta.csv"
SIGNALS_OUT = OUT_DIR / "_signals.csv"
WIDE_OUT = OUT_DIR / "_wide.csv"


def main():
    df = pd.read_csv(PARSED)
    print(f"Loaded {len(df)} rows ({df.ticker.nunique()} tickers)")

    # If a ticker has multiple filings for the same period (revised filings),
    # keep the most recent submission (last in file order, stable).
    df = df.dropna(subset=["period"])
    df = df.sort_values(["ticker", "period", "submission_date"]).drop_duplicates(
        subset=["ticker", "period"], keep="last"
    )
    df = df.sort_values(["ticker", "period"]).reset_index(drop=True)

    # Wide table: one row per (ticker, period).
    wide = df[["ticker", "period", "promoter_pct", "fii_pct", "dii_pct",
               "public_pct", "noninst_pct", "total_shares", "taxonomy"]].copy()
    wide.to_csv(WIDE_OUT, index=False)
    print(f"  → {WIDE_OUT}  ({len(wide)} rows)")

    # ── QoQ Δ ──────────────────────────────────────────────────────────
    qoq = wide.copy()
    qoq = qoq.sort_values(["ticker", "period"])
    for col in ["promoter_pct", "fii_pct", "dii_pct", "public_pct"]:
        qoq[col.replace("_pct", "_d1q")] = qoq.groupby("ticker")[col].diff()
        qoq[col.replace("_pct", "_d4q")] = qoq.groupby("ticker")[col].diff(4)
    qoq["smart_money_score"] = qoq["fii_d4q"].fillna(0) + qoq["dii_d4q"].fillna(0)
    # Track the worst single-quarter Δpromoter over the trailing 4 quarters.
    qoq["promoter_d1q"] = qoq.groupby("ticker")["promoter_pct"].diff()
    qoq["worst_promoter_qtr"] = qoq.groupby("ticker")["promoter_d1q"].rolling(4, min_periods=1).min().reset_index(level=0, drop=True)

    qoq_keep = ["ticker", "period",
                "promoter_pct", "fii_pct", "dii_pct", "public_pct",
                "total_shares",
                "promoter_d1q", "promoter_d4q",
                "fii_d1q", "fii_d4q", "dii_d1q", "dii_d4q", "public_d4q",
                "worst_promoter_qtr", "smart_money_score"]
    qoq[qoq_keep].to_csv(QOQ_OUT, index=False)
    print(f"  → {QOQ_OUT}  ({len(qoq)} rows)")

    # ── Latest-period signals (snapshot) ──────────────────────────────
    latest_period = qoq.groupby("ticker")["period"].max().rename("latest_period")
    snap = qoq.merge(latest_period.reset_index(), on=["ticker"]).query("period == latest_period")
    snap = snap.rename(columns={
        "promoter_pct": "latest_promoter",
        "fii_pct": "latest_fii",
        "dii_pct": "latest_dii",
        "public_pct": "latest_public",
        "noninst_pct": "latest_noninst",
    })
    sig_cols = ["ticker", "latest_period",
                "latest_promoter", "latest_fii", "latest_dii", "latest_public",
                "promoter_d4q", "fii_d4q", "dii_d4q", "public_d4q",
                "worst_promoter_qtr", "smart_money_score"]
    snap[sig_cols].to_csv(SIGNALS_OUT, index=False)
    print(f"  → {SIGNALS_OUT}  ({len(snap)} rows)")

    # Sanity prints
    print("\nCoverage by year (period count):")
    wide["yr"] = wide.period.str[:4]
    print(wide.groupby("yr").size().tail(10).to_string())

    print(f"\nLatest signal universe: {len(snap)} tickers; "
          f"with FII Δ4Q: {snap.fii_d4q.notna().sum()}; "
          f"with DII Δ4Q: {snap.dii_d4q.notna().sum()}; "
          f"with smart_money_score (both non-null): "
          f"{(snap.fii_d4q.notna() & snap.dii_d4q.notna()).sum()}")


if __name__ == "__main__":
    main()
