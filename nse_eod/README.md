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
| NO_OF_TRADES | number of trades → `n_trades` |

## Price bands and circuits

```
GET https://nsearchives.nseindia.com/content/equities/sec_list_{DDMMYYYY}.csv
    Symbol, Series, Security Name, Band, Remarks      Band ∈ {2, 5, 10, 20, "No Band"}
```

One file per trading day (404 on holidays). "No Band" means no fixed band: F&O stocks use
dynamic limits instead, so they never get circuit flags.

**Dating: file D holds the bands in force from the NEXT session.** NSE publishes it after the
close. Across 14,660 band cuts in 2020-2026, 68% of the cut stocks still moved past the new
smaller band on the file's own date, and 3.8% on the next session (mostly ETF unit splits, where
`PREV_CLOSE` is unadjusted). `build_daily_ohlc` re-dates each file to the next trading session in
the bhavcopy and prints the share of rows whose high/low went past their band both ways: 0.057%
re-dated vs 0.294% on the file's own date. The bands are known before that session opens, so
using them is not look-ahead. NSE serves 2021-12-09 and 2022-05-10 as empty files, so the
sessions after them have no band.

Flags (joined on date + symbol + series; band price = `prev_close × (1 ± band)`, less one tick
for NSE's rounding; the tick is ₹0.05, or ₹0.01 below ₹250 from 2024-06-10, read off the closes):

| column | meaning |
|--|--|
| `upper_hit` / `lower_hit` | high (low) touched the band price |
| `upper_close` / `lower_close` | closed at the band price, the usual "circuit hitter" |

The price must also have moved, so a stock whose band is smaller than one tick never counts
as a circuit when it closes flat. 2020-01 → 2026-11: median 74 upper and 52 lower circuit closes a
day.

Limits: on an ex-date (split, bonus) NSE sets the band off an adjusted base price, but
`PREV_CLOSE` in the bhavcopy is not adjusted, so flags are unreliable on those days. About 8% of
sub-₹250 closes were on ₹0.01 steps before 2024-06-10 too; they get the looser ₹0.05 slack.

## Pipeline

```
fetch_bhavcopy.py    # daily download → data/bhavcopy/sec_bhavdata_full_*.csv  (resumable)
                     #   --dataset bands → data/price_bands/sec_list_*.csv
build_daily_ohlc.py  # union all CSVs → data/_daily_ohlc.parquet (long format)
```

## Output schema (`data/_daily_ohlc.parquet`)

```
symbol, date, series, open, high, low, close, last, prev_close, avg_price,
volume_shares, turnover_inr, n_trades, deliv_qty, deliv_pct,
band_pct, upper_hit, upper_close, lower_hit, lower_close
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
