# Changelog

## Unreleased

**Disk cleanup — purged local raw XBRL cache (2026-06-13).**
- Deleted `shareholding_history/data/xbrl/` (~16 GB, ~60K `SHP_*.xml` files) to
  reclaim disk. The directory is git-ignored (raw source cache), so nothing
  committed was lost — `data/filings_index/` and `data/parsed/` outputs remain
  intact.
- Rebuild path if raw XBRL is needed again: rerun `fetch_filings.py` then
  `download_xbrl.py` (resumable). Documented in `shareholding_history/README.md`.

**Index history — build fix: dedup superseded excludes (early-period accuracy).**
- `build_history.py` now collapses a run of exclude events for the same symbol
  with no intervening re-inclusion down to its *last* effective date. NSE
  routinely re-announces a deferred reconstitution with a later effective date
  (e.g. the March-2020 review was COVID-deferred to June 2020), so a symbol
  appeared in two exclude lists ~3 months apart. The old build closed the
  interval at the *first* exclude and fabricated a phantom "member since
  launch" stub from the *second* (orphan-exclude), inflating early-period
  membership.
- Effect: mean per-month cardinality error (vs target size) drops sharply for
  every broad index — Nifty 500 13.5 → 1.6, Smallcap 250 23.5 → 11.0, Midcap
  150 13.9 → 6.9, Next 50 4.4 → 1.8, Nifty 50 0.4 → 0.0. Overall Gate 4
  failures 619 → 608. G1 (0/42) and G3 (0/29) unchanged; pytest 16/16.
- Residual early-period over-count is now dominated by genuine missing include
  events (symbols seeded at the launch floor that actually joined later),
  tracked under R1b in `ROADMAP.md`.

**Index history — added Nifty Microcap 250 (41 → 42 indices).**
- New broad-family registry record (`id` 228, `target_size` 250, launch
  2019-04-01, snapshot `ind_niftymicrocap250_list.csv`).
- Re-parsed the 44 cached press releases that reference the index so its
  include/exclude events are extracted; rebuilt `index_membership_history.csv`
  (now ~6,730 intervals, +815 Microcap intervals).
- Reconstructs to NSE's published current list exactly (G1 snapshot match
  0/42; the `DUMMYALCAR` placeholder in the NSE CSV is filtered, leaving 250
  real constituents). Famous-transition gate unaffected (G3 0/29).
- Coverage caveat: NSE press-release coverage for Microcap 250 begins
  **2021-10**, so the index is reliable from then. Its 2019-04 → 2021-10
  stretch is seeded from the current snapshot and over-counts (walk-back drift,
  ~+15), consistent with the documented best-effort early-coverage limitation.

## v0.2.0 — 2026-05-11 — Multi-family coverage, registry, validation overhaul

**Index history — coverage 6 → 41 indices** (broad + sector + strategy + thematic).
The dataset previously tracked only the six broad-market indices. v0.2.0 adds
35 more across three new families.

- New `index_history/data/index_registry.json` is the single source of truth
  for every tracked index: `id`, `canonical_name`, `family`, `launch_date`,
  `target_size`, `aliases`, `snapshot_slug`, `snapshot_url`. Adding a new
  index is one JSON record + a re-fetch + rebuild.
- `parse_press_release.py`, `build_history.py`, `validate.py`, and
  `fetch_nse_snapshot.py` all consume the registry — no more hardcoded
  index lists across files.
- Sector indices (15): Bank, IT, FMCG, Pharma, Auto, Metal, Realty, Energy,
  PSU Bank, Private Bank, Healthcare, Financial Services, Media, Consumer
  Durables, Oil & Gas.
- Strategy indices (9): Alpha 50, High Beta 50, Low Volatility 50, Nifty50
  Value 20, Nifty100 Equal Weight, Nifty100 Low Volatility 30, Nifty100
  Quality 30, Midcap 50, Smallcap 50.
- Thematic indices (11): Commodities, Consumption, CPSE, Infrastructure, MNC,
  PSE, Services Sector, India Manufacturing, India Defence, Tata 25% Cap,
  MAATR.
- `fetch_nse_snapshot.py` gained an `nseapi:<INDEX NAME>` URL transport that
  uses nseindia.com's `/api/equity-stockIndices` JSON endpoint (warmed-up
  cookie session) for indices not mirrored on `archives.nseindia.com`.

**Pre-2017 PR parser overhaul.**
- Recognises legacy "CNX"/"S&P CNX" prefixes (`CNX Nifty`, `CNX Nifty Junior`,
  `CNX 100`, `CNX 500`, `CNX Bank`, `CNX IT`, etc.) so 2014–2016 PRs map onto
  the post-rebrand canonical names.
- Recognises the parenthesised "(N) Section Name Index" header form used in
  pre-2017 PRs (post-2017 PRs use bare "1) Section Name").
- Auto-detects the early-2014 NSE PDF font glitch where pdfplumber extracts
  each glyph twice ("IInnddeexx") and falls back to OCR (`pdftoppm` +
  `tesseract`) on those documents.
- More robust symbol-row regex: handles OCR output that drops the "Sr. No."
  column or inserts cell-border pipes (`| 6 | Some Co. SYMBOL`).
- All 55 previously-empty pre-2017 Index-Maintenance PDFs now re-parse cleanly.
- Total parsed PRs with at least one event for a tracked index: 130 (was ~100).

**Build pipeline.**
- Per-index launch-date floor — `build_history.py` no longer emits intervals
  before an index existed. Nifty Midcap 150 / Smallcap 250 clamped to
  2016-04-01; sector indices clamped per their own launch.
- **Reverse-reconciliation fix**: build opens an inferred-include interval
  for any symbol present in NSE's current snapshot but absent from our
  walk-forward (the symbol was excluded in some PR we parsed, then
  re-included in a later PR we did not parse). Without this, symbols like
  BANKBARODA (excluded from Nifty Next 50 in 2021-03-31, re-included later)
  silently dropped from "today's" membership. Drove Gate 1 to 0/41.
- `tools.postgres` is now a lazy import — `build_history --csv-out` runs on
  a clean public clone with no database.
- Symbol-rename `TATAMTRDVR → TMPV` changed to `_DUMMY_DROP`. Collapsing the
  DVR class into TMPV caused walk-forward to spuriously close TATAMOTORS'
  Nifty 50 interval at the 2017 PR that excluded TATAMTRDVR from a different
  index. The DVR is no longer listed; dropping it from canon is safe.

**Validation overhaul — 5 gates, no Postgres.**
`validate.py` rewritten to read from CSV + registry only. Runs on a clean
public clone.
- **G1 snapshot match** — `members(today, idx)` must equal NSE's published
  current CSV (DUMMY*/TEMP* placeholders filtered). Currently **0/41**.
- **G2 internal consistency** — Nifty 50 ⊆ Nifty 100, Nifty 100 ⊆ Nifty 500,
  each sector ⊆ Nifty 500. 19 semi-annual sample dates.
- **G3 famous transitions** — 29 hand-curated PIT checks covering all four
  families (broad, sector, strategy, thematic). Currently **0/29**.
- **G4 cardinality** — fixed-size indices' member count == target on
  quarterly samples; pre-launch dates skipped per index.
- **G5 Wayback cross-check** — pulls every Wayback Machine snapshot of each
  index's `archives.nseindia.com/.../ind_<name>list.csv`, samples up to 8
  evenly across time, diffs against our reconstruction at the snapshot's
  exact date. Nifty 50 currently has **mean drift 0.0** across 5 snapshots.
  Skip with `--skip-wayback` for a 30-second run.

**Numbers.** CSV grew from 2,820 → ~5,920 intervals across 41 indices.
838 events from 130 PRs. 16/16 pytest pass.

**Known limitations** — pre-2018 cardinality drifts ±2–13 on broad indices
and somewhat more on sparse-PR strategy/thematic indices, all due to
walk-back from current snapshot through balanced events not being
idempotent under lateral inter-index moves. ROADMAP R1b (2014-01-01 seed
snapshot per index) closes the gap.

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
- MIT-licensed (`LICENSE`).
- Build pipeline runs CSV-only, no database required (`build_history --csv-out`).
- 16-test pytest suite covering all famous transitions + Nifty 50 size invariant + 3 F&O reconciliation cases.

**Data license**
- CC BY 4.0 (`LICENSE-DATA`). Attribution required.
- Raw NSE press release / circular PDFs intentionally not redistributed; users rebuild via `fetch_press_releases.py` and `fetch_circulars.py`.

**Known gaps** — see `ROADMAP.md` for the full list. Highest impact:
- Pre-2017 NSE Indices PRs (~40 image-only or layout-incompatible PDFs).
- Pre-2014 F&O introductions (RELIANCE, INFY, TCS, HDFCBANK, etc. absent from open intervals).
