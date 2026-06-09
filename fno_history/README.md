# NSE F&O Membership History (Point-in-Time)

`data/fno_membership_history.csv` — PIT table of which symbols were in NSE's Futures & Options segment on which dates — built by parsing FAOP circulars from `nseindia.com/api/circulars`.

## Why a separate pipeline from `index_history/`?

F&O segment membership is governed by **NSE Exchange** (the trading exchange), while index membership is governed by **NSE Indices Limited** (a separate subsidiary). They publish at different domains in different formats:

|             | index_history                               | fno_history                                       |
|-------------|---------------------------------------------|---------------------------------------------------|
| Publisher   | NSE Indices Limited                         | NSE Exchange                                      |
| URL         | `niftyindices.com/Press_Release/`           | `nsearchives.nseindia.com/content/circulars/`     |
| Discovery   | `niftyindices.com/press-release?date=YYYY`  | `nseindia.com/api/circulars?dept=FAO&fromDate=…`  |
| Anti-bot    | none                                        | session cookies required (warm via homepage GET)  |
| File type   | mostly PDF                                  | mostly PDF, some `.zip`-bundled (post-2024)       |
| Content     | index inclusions/exclusions                 | F&O introduction/exclusion                        |

## Coverage

- 188 candidate F&O circulars discovered 2014→2026 (filter: subject contains "Introduction of Futures & Options" or "Exclusion of Futures and Options").
- 187 PDFs cached (11 of which were inside `.zip` bundles, extracted).
- 155 events parsed cleanly (84 introductions + 71 exclusions).
- 311 interval rows in `fno_membership_history.csv`, covering 270 distinct symbols.
- 140 currently-open intervals (vs. NSE's actual ~220 F&O list — gap is symbols added pre-2014 and never excluded; we have no introduction event for them).

**Shipped & freshness:** the headline `fno_membership_history.csv` and the `parsed/*.json` intermediates are committed — read them directly, no rebuild needed. Raw circular PDFs are not redistributed (rebuild via `fetch_circulars.py`). Current data-through date is shown in the repo-root [`COVERAGE.md`](../COVERAGE.md).

## Pipeline

```
fetch_circulars.py    # nseindia.com/api/circulars → cache PDFs (incl. zip extraction)
parse_circulars.py    # PDF → {kind, effective_date, symbols, …}
build_history.py      # walk-forward through events → half-open intervals
pit_cli.py            # members --as-of / was-fno / changes
```

## Schema

```sql
CREATE TABLE fno_membership_history (
    id          BIGSERIAL PRIMARY KEY,
    symbol      VARCHAR(50) NOT NULL,
    valid_from  DATE NOT NULL,
    valid_to    DATE,                 -- NULL = currently F&O member
    source      VARCHAR(50),          -- 'circular'
    source_url  TEXT,
    circular_no VARCHAR(40),          -- e.g. 'NSE/FAOP/73205'
    notes       TEXT,
    created     TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (symbol, valid_from)
);
```

A symbol may have multiple intervals (re-introduction after exclusion). PIT query: `valid_from <= D AND (valid_to IS NULL OR valid_to > D)`.

## Verified spot checks

- HDIL: F&O member up to 2018-04-27, excluded thereafter. ✓
- ZOMATO: introduced 2024-11-29 (NSE/FAOP/65295). ✓
- JIOFIN: introduced 2024-11-29. ✓
- SAMMAANCAP: introduced 2025-08-29, excluded 2026-07-01 (NSE/FAOP/73769). ✓
- November 2024 batch: 45 introductions on 2024-11-29 (matches NSE's published big addition list).

## Known limitations

1. **Coverage starts 2014.** Symbols that joined F&O before 2014 and were never excluded (e.g., RELIANCE, INFY, TCS) are absent. To recover them: scrape pre-2014 NSE circulars (different URL pattern, less consistent format) OR seed the table from a 2014 snapshot of NSE's F&O list if one exists.
2. **8 incomplete parses**: edge-case PDFs where pdfplumber struggles with multi-line wrapped table rows. Mostly old (2014–2017) introductions affecting 1–3 symbols each. Would need pdfplumber's `extract_tables` API or hand-curation.
3. **CMPT/SURV circulars skipped**: those mention "Exclusion" but are clearing/surveillance notices, not F&O segment changes. Correctly skipped.
4. **Index F&O introductions skipped**: e.g. "Introduction of F&O on Nifty Midcap Select Index" — those add an index-level future, not a stock-level F&O membership change.
