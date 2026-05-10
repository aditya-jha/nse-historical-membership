# Changelog

## v0.1.0 — 2026-05-10 — Initial public release

First open release. Two datasets, both as CSV + parsed-JSON intermediate.

**Index history** (`index_history/data/index_membership_history.csv`)
- 2,820 half-open intervals across 6 NSE indices: Nifty 50, Next 50, 100, 500, Midcap 150, Smallcap 250.
- Coverage: high confidence 2017+, partial 2014–2016.
- Walk-back seeded from NSE Indices' authoritative published CSVs at `archives.nseindia.com`.
- Snapshot-reconciliation step: walk-back intervals still open today whose symbol is *not* in NSE's official current list are auto-closed at the next semi-annual review with `notes='inferred-exclude'`.
- Image-only PDFs OCR'd via `tesseract` + `pdftoppm`.
- All 13 famous transitions reconcile (HDFC merger, ZOMATO→ETERNAL, INDIGO/MAXHEALTH inclusion, MINDTREE→LTM rename, ADANIGAS→ATGL, etc.).
- Symbols stored canonically — terminal name in any rename chain.

**F&O history** (`fno_history/data/fno_membership_history.csv`)
- 311 half-open intervals across 270 distinct symbols, 2014–2026.
- 140 currently-open intervals (NSE's actual ~220 F&O list — 80 missing are pre-2014 introductions never excluded since).
- Source: parsed FAOP circulars from `nseindia.com/api/circulars`.

**Code**
- MIT-licensed (`LICENSE-CODE`).
- Build pipeline runs CSV-only, no database required (`build_history --csv-out`).
- 16-test pytest suite covering all famous transitions + Nifty 50 size invariant + 3 F&O reconciliation cases.

**Data license**
- CC BY 4.0 (`LICENSE-DATA`). Attribution required.
- Raw NSE press release / circular PDFs intentionally not redistributed; users rebuild via `fetch_press_releases.py` and `fetch_circulars.py`.

**Known gaps** — see `ROADMAP.md` for the full list. Highest impact:
- Pre-2017 NSE Indices PRs (~40 image-only or layout-incompatible PDFs).
- Pre-2014 F&O introductions (RELIANCE, INFY, TCS, HDFCBANK, etc. absent from open intervals).
