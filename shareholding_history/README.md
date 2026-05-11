# NSE Shareholding History (Point-in-Time)

Builds `shareholding_history` — a PIT table of quarterly shareholding patterns
(promoter, FII, DII, public, pledge) per NSE-listed symbol — by parsing SHP
XBRL filings published on `nsearchives.nseindia.com`.

## Why a separate pipeline from StockEdge

StockEdge's `GetShareHoldingPatternDisplaySet/{security_id}` endpoint takes no
date params and returns only the most recent ~9 quarters. That's not enough
for a quarterly-rebalanced backtest with proper walk-forward validation
(n≈4 rebalances per arm).

The NSE master endpoint exposes the **full disclosure history** — typically
20+ years per symbol — and links to publicly downloadable XBRL files
(no auth, no Cloudflare). Each XBRL is the regulator-filed source data
StockEdge ingests downstream.

## Coverage target

| | scope |
|--|--|
| Symbols | 1,016 NSE-listed (from `research/india-ai-story/06_data/stockedge/_shareholding/_signals.csv`) |
| Depth | All available filings per symbol (typically Dec-2005 → today, ~80 quarters) |
| Format | XBRL V1.1 (post 2025-10-31) + older taxonomies |

## Data source

```
1. List per ticker:
   GET https://www.nseindia.com/api/corporate-share-holdings-master
       ?index=equities&symbol={SYMBOL}
   → JSON list of filings, each with {date, xbrl, recordId}

2. Download filing:
   GET https://nsearchives.nseindia.com/corporate/xbrl/SHP_*.xml
   → application/xml, ~500 KB per file
```

NSE is anti-bot — must warm session by hitting homepage first to acquire
cookies. Reuses `nse_fno_history.code.fetch_circulars.make_session()`.

## Pipeline

```
fetch_filings.py    # API → data/filings_index.json   (per-ticker XBRL URL list)
download_xbrl.py    # bulk fetch → data/xbrl/SHP_*.xml (resumable)
parse_xbrl.py       # XBRL → data/parsed/_flat.csv     (ticker, period, %)
validate.py         # cross-check vs StockEdge overlap (9 quarters)
build_signals.py    # _qoq_delta.csv + _signals.csv    (deep history)
```

## Schema (output)

```
data/parsed/_flat.csv
  ticker, period, promoter_pct, fii_pct, dii_pct, public_pct, pledge_pct

data/parsed/_qoq_delta.csv
  ticker, period, prev_period, d_promoter, d_fii, d_dii, d_public, d_pledge

data/parsed/_signals.csv
  ticker, latest_period, latest_{promoter,fii,dii,public,pledge},
  {promoter,fii,dii,public}_d4q, worst_promoter_qtr, smart_money_score
```

`smart_money_score = fii_d4q + dii_d4q` (4-quarter cumulative Δ).

## Validation gates

1. **Parser correctness:** for the 2024-06 → 2026-03 overlap (9 quarters)
   the per-ticker (promoter, fii, dii) values in this pipeline must match
   StockEdge's `_flat.csv` within ±0.05 pp on at least 95% of (ticker, period)
   pairs.
2. **Coverage:** ≥ 95% of the 1,016 tickers have ≥ 20 quarters of history.
3. **Sanity:** for any (ticker, period), promoter + public ≈ 100% (±0.5 pp,
   accounting for rounding + Custodian/DR rows).

## Consumers

- `backtest/india/smart_money/` — quarterly-rebalanced smart-money momentum
  screen (FII+DII Δ).
- General-purpose PIT membership filter for any strategy that needs to
  reconstruct historical institutional ownership.
