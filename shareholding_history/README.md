# NSE Shareholding History (Point-in-Time)

Builds `shareholding_history` — a PIT table of quarterly shareholding patterns
(promoter, FII, DII, public, pledge) per NSE-listed symbol — by parsing SHP
XBRL filings published on `nsearchives.nseindia.com`.

## Why a separate pipeline

Most third-party portals expose only the most recent ~9 quarters of
shareholding per symbol — not enough for a quarterly-rebalanced backtest with
proper walk-forward validation.

The NSE master endpoint exposes the **full disclosure history** — typically
20+ years per symbol — and links to publicly downloadable XBRL files
(no auth, no Cloudflare). Each XBRL is the regulator-filed source data.

## Coverage

| | scope |
|--|--|
| Universe | Full NSE-listed universe (`data/_universe.csv`, ~2,910 symbols, self-contained) |
| Committed | **2,261 symbols** parsed, periods **2001-03 → 2026-04** (108 quarters) |
| Depth | All available filings per symbol (typically Dec-2005 → today) |
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
cookies. Reuses `fno_history.code.fetch_circulars.make_session()`.

## Pipeline

```
fetch_filings.py    # API → data/filings_index/<TICKER>.json (per-ticker XBRL URL list)
download_xbrl.py    # bulk fetch → data/xbrl/SHP_*.xml        (resumable)
parse_xbrl.py       # XBRL → data/parsed/_flat.csv            (ticker, period, %)
build_signals.py    # _qoq_delta.csv + _signals.csv           (deep history)
validate.py         # OPTIONAL cross-check vs a --reference export you supply
```

> **Note — `data/xbrl/` is not present locally / not in git.** The raw XBRL
> source (~16 GB / ~60K XML files) is git-ignored and was deleted on
> 2026-06-13 during a disk cleanup (see repo `CHANGELOG.md`). The committed
> outputs (`data/filings_index/`, `data/parsed/`) are unaffected. Only
> re-fetch if you need to re-parse from raw XBRL: rerun `fetch_filings.py`
> then `download_xbrl.py` (resumable) to repopulate `data/xbrl/`.

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

1. **Parser correctness (optional):** `validate.py` cross-checks the parsed
   `(promoter, fii, dii)` values against an external reference export you
   supply via `--reference` (long-format `ticker, period, category, pct`).
   For an overlapping window they should match within ±0.5 pp. The reference
   file is not shipped; the committed `data/validation_vs_stockedge.json` is
   the recorded result of a past run.
2. **Coverage:** most symbols should carry ≥ 20 quarters of history.
3. **Sanity:** for any (ticker, period), promoter + public ≈ 100% (±0.5 pp,
   accounting for rounding + Custodian/DR rows).

## Uses

General-purpose PIT shareholding source for any strategy that needs to
reconstruct historical institutional ownership (e.g. a quarterly-rebalanced
smart-money screen on FII+DII Δ).
