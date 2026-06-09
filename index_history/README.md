# NSE Index Membership History (Point-in-Time)

`data/index_membership_history.csv` — PIT table of which symbols were in which NSE index on which date — built by walking **backward** from the current snapshot through NSE's published replacement press releases.

## Indices in scope

| index_id | name              | inception |
|----------|-------------------|-----------|
| 217      | Nifty 50          | 1996      |
| 218      | Nifty Next 50     | 1996      |
| 219      | Nifty 100         | 2003      |
| 221      | Nifty 500         | 1995      |
| 223      | Nifty Midcap 150  | April 2016 |
| 227      | Nifty Smallcap 250| April 2016 |
| 228      | Nifty Microcap 250| April 2019 |

Reliable coverage: **2018-04 → today** for the first six. Best-effort earlier where PR PDFs are findable. Pre-2018 fills the membership but the cardinality gate flags drift. Microcap 250's NSE press-release coverage only begins **2021-10**, so it is reliable from then; its 2019–2021 stretch is seeded from the current snapshot and over-counts.

The full tracked set is **42 indices** across broad / sector / strategy / thematic families. The 7 above are the broad family; for the complete per-index table — id, family, target size, current member count, and the date range actually present in the data — see the generated [`COVERAGE.md`](../COVERAGE.md) at the repo root (machine source of truth: `data/index_registry.json`).

## Source

`https://niftyindices.com/Press_Release/ind_prs<DDMMYYYY>[_N].pdf`

URL pattern discovered via `sitemap.xml`. The page `/Resources/Press-Release` is JS-rendered and useless for scraping. Pre-July-2022 PDFs not all in current sitemap; recovered via union of 29 historical sitemap snapshots from Wayback CDX, plus targeted probe-sweep around Feb-end and Aug-end of each year (semi-annual Index Maintenance Sub-committee review windows).

## Pipeline

```
fetch_press_releases.py   # union sitemap snapshots + probe-sweep → cache PDFs
parse_press_release.py    # PDF → {effective_date, index, included[], excluded[]}
                          # falls back to pdftoppm + tesseract OCR for image-only PDFs
build_history.py          # walk-backward from current snapshot → intervals
validate.py               # 5 gates G1–G5 (see below); writes docs/validation_report.md
pit_cli.py                # `python -m index_history.code.pit_cli member --index 'Nifty 50' --as-of 2022-06-15`
```

## Validation gates

`validate.py` runs five gates (G1–G5); latest run is written to `docs/validation_report.md` and summarised in the main [README](../README.md#coverage-and-known-gaps).

- **G1 — snapshot match:** `members(today, idx)` equals NSE's current published CSV for every index. **0/42 mismatches.**
- **G2 — internal consistency:** structural invariants (Nifty 100 ⊆ Nifty 500, sectors ⊆ Nifty 500, Next 50 ⊆ Nifty 100, etc.). Holds today; some pre-2018 dates violate it from walk-back drift.
- **G3 — famous transitions:** every documented real-world transition reconciles. **29/29 PASS**, e.g.:
   - HDFC absent from Nifty 50 on/after 2023-07-13 (HDFC–HDFCBANK merger)
   - SHRIRAMFIN entered Nifty 50 2024-03-28; UPL excluded same date
   - ETERNAL (was ZOMATO) entered Nifty 50 in March 2025
   - INDIGO + MAXHEALTH entered Nifty 50 2025-09-30; HEROMOTOCO + INDUSINDBK excluded same date
   - ATGL (was ADANIGAS) member of Nifty 500 in 2021
   - LTIM (was MINDTREE) member of Nifty 500 in 2022
- **G4 — cardinality:** `|members(index, date)| == target_size(index)` for every business day. Clean 2018+; drifts ±2–13 on pre-2018 dates (tracked as R1b in `ROADMAP.md`). Only the 20 indices with a registry `target_size` are checked.
- **G5 — Wayback cross-check:** Nifty 50 reconstruction vs archive.org snapshots of NSE's official constituent CSVs. Mean drift 0.0 across the sampled snapshots.

## Failure policy

A press release that fails to parse stops the build until it's either fixed or has a human-curated entry in `data/manual_overrides/`.

## Known limitations

- Cardinality gate (G4) currently fails for many 2014–2019 dates (over-inclusion of 5–7 symbols on Next 50 / 100 / 500 / Smallcap 250). Famous-transition gate (G3) all PASS, indicating the walk-back is structurally sound but historical replacement events are incomplete pre-2018. Contributions adding pre-2018 PR coverage are welcome.
- Image-only press releases (pre-text-layer scanned PDFs) are OCR'd via `tesseract` + `pdftoppm`. Of 15 detected, 1 OCR'd into a clean event (Aug 2021 review → 2021-09-30); the rest were dividend or non-IM notices that OCR correctly classified as not-IM.
