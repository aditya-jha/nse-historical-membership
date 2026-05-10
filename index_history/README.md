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

Reliable coverage: **2018-04 → today** for all six indices. Best-effort earlier where PR PDFs are findable. Pre-2018 fills the membership but the cardinality gate flags drift.

## Source

`https://niftyindices.com/Press_Release/ind_prs<DDMMYYYY>[_N].pdf`

URL pattern discovered via `sitemap.xml`. The page `/Resources/Press-Release` is JS-rendered and useless for scraping. Pre-July-2022 PDFs not all in current sitemap; recovered via union of 29 historical sitemap snapshots from Wayback CDX, plus targeted probe-sweep around Feb-end and Aug-end of each year (semi-annual Index Maintenance Sub-committee review windows).

## Pipeline

```
fetch_press_releases.py   # union sitemap snapshots + probe-sweep → cache PDFs
parse_press_release.py    # PDF → {effective_date, index, included[], excluded[]}
                          # falls back to pdftoppm + tesseract OCR for image-only PDFs
build_history.py          # walk-backward from current snapshot → intervals
validate.py               # 4 gates: archive cross-check, famous transitions, cardinality, manual spot-checks
pit_cli.py                # `python -m index_history.code.pit_cli member --index 'Nifty 50' --as-of 2022-06-15`
```

## Validation gates

1. `index_equity_map_archive` agrees with `v_index_member_at` lookups at all archived snapshot dates for indices 217 and 223.
2. **Famous transitions** (Gate 2 — currently 13/13 PASS):
   - HDFC absent from Nifty 50 on/after 2023-07-13 (HDFC–HDFCBANK merger)
   - SHRIRAMFIN entered Nifty 50 2024-03-28; UPL excluded same date
   - ETERNAL (was ZOMATO) entered Nifty 50 in March 2025
   - INDIGO + MAXHEALTH entered Nifty 50 2025-09-30; HEROMOTOCO + INDUSINDBK excluded same date
   - ATGL (was ADANIGAS) member of Nifty 500 in 2021
   - LTIM (was MINDTREE) member of Nifty 500 in 2022
3. `|members(index, date)| == target_size(index)` for every business day. Cardinality drift = data bug to investigate.
4. Random spot-checks against archive.org snapshots of niftyindices.com index pages.

## Failure policy

A press release that fails to parse stops the build until it's either fixed or has a human-curated entry in `data/manual_overrides/`.

## Known limitations

- Cardinality gate (Gate 3) currently fails for many 2014–2019 dates (over-inclusion of 5–7 symbols on Next 50 / 100 / 500 / Smallcap 250). Famous-transition gate (Gate 2) all PASS, indicating the walk-back is structurally sound but historical replacement events are incomplete pre-2018. Contributions adding pre-2018 PR coverage are welcome.
- Image-only press releases (pre-text-layer scanned PDFs) are OCR'd via `tesseract` + `pdftoppm`. Of 15 detected, 1 OCR'd into a clean event (Aug 2021 review → 2021-09-30); the rest were dividend or non-IM notices that OCR correctly classified as not-IM.
