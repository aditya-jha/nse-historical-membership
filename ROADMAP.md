# Roadmap — open tasks

Anyone can pick one of these up. Each task lists its scope, leverage, and entry point. PRs welcome — see `CONTRIBUTING.md`.

---

## High leverage (move the needle most for users)

### R1 — Backfill pre-2017 NSE Indices PRs
**Status:** open · **Skill:** patient PDF/OCR work · **Time:** 1–2 days

The pre-2017 daily cardinality gate fails by ±5–7 symbols because we don't have all the replacement events for that era. A `niftyindices.com` PR scraper exists (`fetch_press_releases.py`) but ~40 of the 2014–2016 PR PDFs are image-only or use older table layouts the parser can't decode.

Concrete output: every December 31 from 2014 onward should have exactly 50/50/100/500/150/250 members in the published CSV. Right now, 2014-12-31 has 56/104/518/157/282 — that gap is what this task closes.

Entry point: `index_history/docs/validation_report.md` lists every failing date. Pick one, find the missing PR (Wayback Machine has most of them at `web.archive.org/web/*/niftyindices.com/Press_Release/*`), parse it.

### R2 — Pre-2014 F&O introductions
**Status:** open · **Skill:** sourcing · **Time:** 0.5–2 days

The F&O dataset starts 2014 because that's where `nseindia.com/api/circulars` reliable history begins. Real F&O has been live since 2001, so symbols introduced 2001–2013 and never excluded since (RELIANCE, INFY, TCS, HDFCBANK, …) are absent from the dataset's open intervals.

Two acceptable approaches:
1. Find a 2014-01-01 NSE F&O snapshot (PDF list, circular index, or archived `.csv`) and seed the table at that floor.
2. Scrape pre-2014 NSE circulars from a different URL pattern (NSE used to post these at `nse-india.com/.../circulars/...` with non-FAOP department codes).

If you find approach 1, this becomes a one-PR task: drop a 2014-01-01 seed CSV into `fno_history/data/manual_overrides/` and adjust `build_history` to merge it.

### R3 — Add Nifty Bank / Nifty IT / sector indices
**Status:** open · **Skill:** parser extension · **Time:** 1 day

Right now the dataset covers only the broad-market indices (Nifty 50/Next 50/100/500/Midcap 150/Smallcap 250). NSE publishes 30+ sector indices in the same press releases. The parser already extracts every section it sees; we just don't keep them.

Concrete change: extend `INDEX_NAME_TO_ID` in `parse_press_release.py` and `TARGET_INDEX_IDS` in `build_history.py`. Fetch the corresponding `archives.nseindia.com/.../ind_<sector>list.csv` for the seed.

Sector indices wanted (in priority order): Nifty Bank, Nifty IT, Nifty FMCG, Nifty Pharma, Nifty Auto, Nifty Metal, Nifty Realty, Nifty Energy, Nifty PSU Bank, Nifty Private Bank.

---

## Medium leverage

### R4 — Symbol-rename detection automation
**Status:** open · **Skill:** small · **Time:** 0.5 day

`detect_renames.py` exists but is run manually. Wire it into `build_history` as a preflight: any walk-back symbol absent from NSE's current snapshot but with a similarly-named entry should suggest a rename for human review. Output goes to `docs/symbol_renames_diagnostic.json` (already exists). Convert that into a "candidate renames" PR template.

### R5 — Sub-daily snapshots for index_equity_map_archive
**Status:** open · **Skill:** none — pure refactor · **Time:** 0.5 day

`validate.py`'s Gate 1 reads from a Postgres `index_equity_map_archive` table, but most contributors don't have that. Replace the Postgres dependency with periodic CSV snapshots committed to `index_history/data/archive_snapshots/<YYYY-MM-DD>.csv`. Validation becomes runnable in CI without any database.

### R6 — Notebook companion for `quickstart.py`
**Status:** open · **Skill:** none · **Time:** 1 hour

A Jupyter notebook (`examples/01_pit_queries.ipynb`) covering the same five questions plus 2–3 visualizations (Nifty 500 churn over time, average tenure of a Nifty 50 member, etc.). Notebooks render inline on GitHub and are by far the highest-leverage way to onboard new users.

### R7 — Parquet/SQLite distribution alongside CSV
**Status:** open · **Skill:** small · **Time:** 1 hour

A 2,820-row CSV is fine but pandas users on slow connections benefit from `.parquet` (1/3 the size, faster load) and SQLite users want a `.sqlite` file with both tables and indexes already built. A `make build` target that produces all three formats from a single source-of-truth.

### R8 — DuckDB recipe in README
**Status:** open · **Skill:** doc · **Time:** 30 min

Show how to run PIT queries directly from the CSV via DuckDB without loading anything into memory. This is the fastest path for exploratory work and one of the strongest "wow" demos.

---

## Lower leverage (nice but not blocking)

### R9 — Continuous monitoring
NSE publishes new PRs continuously. A weekly GitHub Actions workflow that runs `fetch_press_releases.py + parse_all + build_history + pytest` and opens a PR on diff would keep the dataset auto-updated. Triage volunteers welcome.

### R10 — Visual gallery
A `docs/gallery.md` with 5–10 charts derived from the dataset (sector-rotation plot, churn distribution, longest-tenured Nifty 50 members, etc.). Each is a 20-line script + PNG.

### R11 — Zenodo DOI registration
Once v0.1.0 is tagged, register on Zenodo for a citable DOI. One-time, ~10 minutes. Owner-only task (requires GitHub repo admin).

### R12 — Add corporate-action overlays
Splits, bonuses, demergers — useful for any backtest that consumes this. Probably a separate dataset with cross-references, not folded into the membership table.

---

## How to claim a task

1. Comment on the existing GitHub Issue (or open a new one referencing the task ID, e.g. `[R3] Adding Nifty Bank`).
2. State your timeline. If a task has been claimed for >30 days without progress, others can pick it up.
3. Open a PR linked to the issue.

## How to propose a new task

Open a GitHub Issue with the prefix `[Roadmap]` describing:
- The problem in user terms ("backtests that filter on sector membership can't be done with the current dataset").
- The proposed solution.
- What's the leverage — who benefits, by how much.

Tasks that block someone's production use of the dataset jump the queue.
