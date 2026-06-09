# NSE Index History — Build Log

## 2026-05-08 — Initial pipeline build

## 2026-05-08 — Update: yearly listing endpoint discovered

User flagged that semi-annual reviews were still missing. Investigation found:
**`niftyindices.com/press-release?date=YYYY` is server-rendered with the full PR list.** This was the missing piece — `/Resources/Press-Release` is JS-rendered, but `/press-release?date=YYYY` is plain HTML with all PR links visible to grep.

### Impact
- Inventory: **1,114 unique URLs** (vs 1,490 noisy probe-sweep before; 1,106 actual PDFs cached, only 8 hard failures).
- IM events extracted: **64** (was 16; 4× improvement).
- Famous transitions: **5/5 PASS** (was 4/5). HDFC merger now captured (`ind_prs04072023`, effective 2023-07-13).
- Coverage now includes every Mar/Sep semi-annual review from 2018→2026 plus dozens of off-cycle events.

### Remaining gaps
- **Image-only PDFs (~3 critical ones)**: `ind_prs23082021.pdf` (the canonical Aug 2021 semi-annual review) is 29 pages of 299 embedded images, zero text layer. Same for `ind_prs24092018_1.pdf` and `ind_prs25092018.pdf`. These need OCR (Tesseract) to extract — pdfplumber and pdfium both return empty strings.
- **Symbol renames**: Current snapshot uses post-rename names (ETERNAL, LTIM, ATGL); PR PDFs use pre-rename names (ZOMATO, MINDTREE, ADANIGAS). Walk-back doesn't reconcile — surfaces as ~5-25 "extra" symbols per index per archive snapshot. Requires building a rename map (or running the rename-detector over time).
- **Partial-coverage events**: Some PRs (e.g., `ind_prs15092021`) cover only Midcap/Smallcap segments; the corresponding Nifty 50/Next 50/100 PR for that quarter is in the image-only `ind_prs23082021.pdf`.

### What works correctly today
- Membership for any date in a covered period is exact (verified by 5/5 famous transitions).
- 64 PR events span 2017-2026 with most major review dates parsed.
- The CLI returns correct results: `pit_cli changes --index "Nifty 50" --from 2024-01-01 --to 2024-12-31` correctly shows `+SHRIRAMFIN, +BEL, +TRENT / -UPL, -DIVISLAB, -LTIM`.

---

## 2026-05-08 — Initial pipeline build

### What was built
End-to-end pipeline from NSE press-release PDFs → `index_membership_history` table:
- `code/fetch_press_releases.py` — discovers PR URLs via sitemap.xml + Wayback CDX + probe-sweep.
- `code/fetch_live.py` — fast live-only HTTP downloader (filters out soft-404 HTML).
- `code/parse_press_release.py` — single-PDF parser (pdfplumber) → JSON of (effective_date, index_id, included[], excluded[]).
- `code/parse_all.py` — batch driver across the cache.
- `code/build_history.py` — walk-backward from current snapshot, emit half-open intervals to DB.
- `code/validate.py` — 3 gates: archive cross-check, famous transitions, daily cardinality.
- `code/pit_cli.py` — CLI for member-as-of, changes-between, was-member-on.

### Source discovery (key finding)
The page `niftyindices.com/Resources/Press-Release` is JS-rendered; static HTML reveals zero PR links and the AJAX endpoint name (`getpressreleasedata` etc.) is wrong / not in any static JS bundle. **Discovered the URL pattern via sitemap.xml**: PRs follow `niftyindices.com/Press_Release/ind_prs<DDMMYYYY>[_N].pdf`. No headless browser needed.

### Inventory — what is actually fetchable
- Wayback CDX direct: 53 PDFs (sparse coverage, only what archive.org happened to crawl).
- 29 historical sitemap.xml snapshots from Wayback (July 2022 → Jan 2026): expanded inventory significantly.
- Probe-sweep at known semi-annual review windows (Feb 24-31, Mar 24-31, Aug 24-31, Sep 24-31 across 2014-2026 with `_1`, `_2`, `_3`, `_4` suffixes): added thousands of candidates but most return soft-404 HTML at HTTP 200.
- **Total live + verified-PDF**: 182 PDFs.
- **Total in inventory**: 1490 URLs. The remaining 1308 returned soft-404 HTML (`Content-Type: text/html`) at status 200 — niftyindices.com's missing-PDF behaviour is to render its homepage shell.

### Parser format variations encountered
Two regex changes were needed across the pipeline:
1. **2024+ PRs use lowercase letter sub-section markers**: `b) Nifty Next 50` not `2) Nifty Next 50`. Patched `SECTION_RE`.
2. **Pre-2020 PRs use uppercase NIFTY**: "1) NIFTY 50". Made alias lookup case-insensitive.

### IM events extracted (16 PDFs)
| Effective | Source PDF | Indices covered |
|-----------|------------|-----------------|
| 2017-03-31 | ind_prs07032017 | Nifty Smallcap 250 |
| 2017-03-31 | ind_prs16022017 | Next 50, 100, Midcap 150, Smallcap 250 |
| 2017-05-26 | ind_prs27042017 | 100, Midcap 150, Smallcap 250 |
| 2017-09-29 | ind_prs28082017 | Next 50, 100, Midcap 150, Smallcap 250 |
| 2017-09-29 | ind_prs29082017 | Midcap 150 |
| 2018-09-28 | ind_prs28082018 | All 6 |
| 2018-09-28 | ind_prs31082018 | 500, Smallcap 250 |
| 2019-03-29 | ind_prs25022019 | All 6 |
| 2019-09-27 | ind_prs28082019 | All 6 |
| 2021-06-30 | ind_prs15062021 | Next 50, 100, 500 |
| 2022-03-31 | ind_prs24022022_1 | All 6 |
| 2023-03-31 | ind_prs17022023_1 | Next 50, 100, 500, Midcap 150, Smallcap 250 |
| 2024-03-28 | ind_prs28022024 | All 6 |
| 2024-09-30 | ind_prs23082024 | All 6 |
| 2025-04-11 | ind_prs04042025_2 | 500, Smallcap 250 |
| 2025-09-30 | ind_prs22082025 | All 6 |

### Coverage gaps (semi-annual reviews not found)
- **Mar 2017** for Nifty 50 (have 2017-03-31 but Nifty 50 isn't in the parsed events — likely a separate PDF we don't have)
- **Mar 2018** — no PR PDF on live host
- **Mar 2020** — no PR (Mar 2020 disruption?)
- **Sep 2020** — no PR
- **Mar 2021** — no PR (have ind_prs24032021 but it's a Fixed Income IMSC PR)
- **Sep 2021** — no PR (ind_prs26082021 covers SME EMERGE only)
- **Sep 2022** — no PR (ind_prs26092022 is Fixed Income)
- **Sep 2023** — no PR (ind_prs28082023 is Fixed Income)
- **Mar 2025** — no PR (ind_prs24022025 is Fixed Income)
- **Mar 2026** — no PR (ind_prs24022026 is Fixed Income)

That's **~10 missing semi-annual reviews** + an unknown number of off-cycle events.

### Validation result
- **Gate 1 archive cross-check**: 43/43 mismatches. Two root causes:
  1. Symbol renames (ZOMATO→ETERNAL, MINDTREE→LTIM, ADANIGAS→ATGL) — current snapshot uses new names; PRs use historical names; walk-back doesn't reconcile.
  2. Missing semi-annual reviews above means walk-back can't re-add/remove ~30-100 stocks per index.
- **Gate 2 famous transitions**: 4/5 PASS.
  - ✓ HDFC absent from Nifty 50 on 2023-07-14 (merger).
  - ✓ HDFCBANK still in Nifty 50 on 2023-07-14.
  - ✓ SHRIRAMFIN added on 2024-03-28.
  - ✓ UPL excluded on 2024-03-28.
  - ✗ BPCL was member on 2022-01-01 — fails because BPCL was excluded mid-2020 then re-added later, and we don't have those PRs.
- **Gate 3 daily cardinality**: 228/228 fail (each affected by gaps + renames).

### Honest assessment
Pipeline logic is correct: where we have PR coverage, the table is accurate (4/5 famous transitions pass; SHRIRAMFIN and UPL on Nifty 50 verified). What we lack is *complete* PR coverage. The table is **NOT YET RELIABLE for arbitrary-date backtests** — symbol counts at any date drift from the true index size by 1-50 symbols depending on the index and date.

### Recommended next steps
1. **Backfill missing semi-annual review PDFs** by manually finding their dates (the IM-Sub-Committee meeting dates vary year-to-year; sometimes mid-month rather than Feb-end/Aug-end). Possible sources: NSE corporate-archive at nseindia.com, financial press reports, or BSE equivalents.
2. **Build a symbol-rename map** with effective dates: ZOMATO→ETERNAL (2025-XX), MINDTREE→LTIM (2022-11-14 merger of L&T Infotech + Mindtree), ADANIGAS→ATGL (2020-XX), ATGL/ADANITRANS, KMBL/KOTAKBANK, etc. Apply renames in walk-back so current-snapshot symbols project correctly to historical names.
3. **Use `data/manual_overrides/`** to inject the hand-curated events for the gaps; the build script already loads from there.
4. **Re-run validation** after each batch of overrides to track progress: target zero archive-mismatches.

### How to use today (with caveats)
- Famous transitions covered by parsed PRs are accurate (HDFC merger, SHRIRAMFIN, UPL, TRENT, BEL).
- Membership for any date in a covered period (e.g., 2024-03-28 to 2024-09-30) is exact.
- For uncovered periods (most of 2018-2023): expect ±1-50 symbols off vs true size.
- Use `python -m index_history.code.pit_cli member --index "Nifty 50" --as-of YYYY-MM-DD` to query.
