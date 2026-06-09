# NSE EOD (cash-market daily OHLC)

Per-day NSE cash-market bhavcopy → consolidated long-format daily OHLC table.

Sibling to `index_history/`, `fno_history/`, `shareholding_history/`.
Provides the canonical NSE-equity OHLC + turnover source for backtests that
need a wide universe (main board + SME Emerge), no auth, no Cloudflare.

## Why a separate pipeline

NSE publishes a single end-of-day bhavcopy CSV per trading day that covers the
**entire** cash-market universe (main board + SME Emerge) in one file, with no
auth and no per-symbol id mapping. That makes it the cleanest source for wide,
survivorship-correct daily OHLC + turnover across all ~2,900 NSE names — which
the index/F&O/shareholding pipelines in this repo don't provide (they track
membership and ownership, not prices).

## Data source

```
GET https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv
GET https://nsearchives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MMM}/cm{DD}{MMM}{YYYY}bhav.csv.gz   ← legacy fallback (pre-2020)
```

Schema (`sec_bhavdata_full`):

| col | meaning |
|--|--|
| SYMBOL | NSE symbol |
| SERIES | EQ (main), SM (SME Emerge), BE/BZ (trade-to-trade), ST (SME T2T), GS/GB (gov bonds — drop) |
| DATE1 | trade date (DD-MMM-YYYY) |
| OPEN_PRICE / HIGH_PRICE / LOW_PRICE / CLOSE_PRICE | OHLC |
| LAST_PRICE / AVG_PRICE / PREV_CLOSE | aux |
| TTL_TRD_QNTY | volume (shares) |
| TURNOVER_LACS | ₹ turnover in lacs (= ₹100k) — use for liquidity gates |

## Pipeline

```
fetch_bhavcopy.py    # daily download → data/bhavcopy/sec_bhavdata_full_*.csv  (resumable)
build_daily_ohlc.py  # union all CSVs → data/_daily_ohlc.parquet (long format)
```

## Output schema (`data/_daily_ohlc.parquet`)

```
symbol, date, series, open, high, low, close, last, prev_close, avg_price,
volume_shares, turnover_inr, n_trades
```

## Status

* **No data is shipped in this repo** — unlike the index/F&O/shareholding
  modules, the bhavcopies (~half a GB) and the consolidated parquet are
  gitignored. You generate them locally:
  `python -m nse_eod.code.fetch_bhavcopy --start 2020-01-01 --end today`
  then `python -m nse_eod.code.build_daily_ohlc`. Both are resumable.
* 2020-01-01 → today is the supported window via `sec_bhavdata_full`.
* SERIES filter recommended: keep `{EQ, SM, BE, BZ, ST}`; drop bonds.
* `turnover_inr = TURNOVER_LACS * 1e5` for clean ₹.
