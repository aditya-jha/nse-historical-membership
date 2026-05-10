# Roadmap — open tasks

Anyone can pick one of these up. Each task lists its scope, leverage, and entry point. PRs welcome — see `CONTRIBUTING.md`.

---

## Completed in v0.2.0 (2026-05-11)

- **R1a — Pre-2017 PR parser overhaul**. CNX legacy aliases, OCR fallback for the early-2014 PDF font glitch, robust symbol-row regex. All 55 previously-empty pre-2017 IM PDFs now re-parse cleanly.
- **R3 — Sector / strategy / thematic indices**. Coverage went from 6 → **41** indices (6 broad + 15 sector + 9 strategy + 11 thematic) via a single registry (`index_history/data/index_registry.json`). Adding a new index is now one JSON record + a re-fetch.
- **R5 — Postgres-free validation**. `validate.py` rewritten to read CSV + registry only. Five gates (snapshot match, internal consistency, famous transitions, cardinality, Wayback cross-check). No database required.

---

## High leverage (move the needle most for users)

### R1b — 2014-01-01 seed snapshots per index
**Status:** open · **Skill:** sourcing · **Time:** 0.5–1 day

Walk-back from current snapshot through balanced events isn't idempotent when symbols moved laterally between indices over time (e.g. a stock that joined Nifty Next 50 in 2014, was promoted to Nifty 50 in 2018, then exited entirely in 2024 cannot be fully reconstructed by walking Nifty Next 50 events alone).

**Symptoms today**: Gate 4 reports ±2–13 cardinality drift on pre-2018 dates for broad indices and somewhat more for sparse-PR strategy/thematic families. Gate 2 reports subset violations (e.g. `Nifty Next 50 ⊆ Nifty 100`) on the same pre-2018 dates. Gate 3 (famous transitions) is unaffected — per-symbol membership transitions are correct.

**Fix**: source authoritative 2014-01-01 (or earliest available) member CSVs per index from Wayback's CDX of `archives.nseindia.com/.../ind_<name>list.csv`, drop them in `index_history/data/seed_snapshots/<slug>.csv`, and switch `build_history.py` to walk *forward* from those seeds (instead of backward from current). Once the seeds are sourced this is a one-PR change to `build_intervals` in `build_history.py`.

`validate.py:gate_wayback` already has a working CDX fetcher you can lift for the sourcing step.

### R2 — Pre-2014 F&O introductions
**Status:** open · **Skill:** sourcing · **Time:** 0.5–2 days

The F&O dataset starts 2014 because that's where `nseindia.com/api/circulars` reliable history begins. Real F&O has been live since 2001, so symbols introduced 2001–2013 and never excluded since (RELIANCE, INFY, TCS, HDFCBANK, …) are absent from the dataset's open intervals.

Two acceptable approaches:
1. Find a 2014-01-01 NSE F&O snapshot (PDF list, circular index, or archived `.csv`) and seed the table at that floor.
2. Scrape pre-2014 NSE circulars from a different URL pattern (NSE used to post these at `nse-india.com/.../circulars/...` with non-FAOP department codes).

If you find approach 1, this becomes a one-PR task: drop a 2014-01-01 seed CSV into `fno_history/data/manual_overrides/` and adjust `build_history` to merge it.

---

## Medium leverage

### R4 — Symbol-rename detection automation
**Status:** open · **Skill:** small · **Time:** 0.5 day

`detect_renames.py` exists but is run manually. Wire it into `build_history` as a preflight: any walk-back symbol absent from NSE's current snapshot but with a similarly-named entry should suggest a rename for human review. Output goes to `docs/symbol_renames_diagnostic.json` (already exists). Convert that into a "candidate renames" PR template.

### R6 — Notebook companion for `quickstart.py`
**Status:** open · **Skill:** none · **Time:** 1 hour

A Jupyter notebook (`examples/01_pit_queries.ipynb`) covering the same five questions plus 2–3 visualizations (Nifty 500 churn over time, average tenure of a Nifty 50 member, sector-rotation plot, etc.). Notebooks render inline on GitHub and are by far the highest-leverage way to onboard new users — especially now that we have 41 indices to explore.

### R7 — Parquet/SQLite distribution alongside CSV
**Status:** open · **Skill:** small · **Time:** 1 hour

A 5,919-row CSV is fine but pandas users on slow connections benefit from `.parquet` (1/3 the size, faster load) and SQLite users want a `.sqlite` file with both tables and indexes already built. A `make build` target that produces all three formats from a single source-of-truth.

### R8 — DuckDB recipe in README
**Status:** open · **Skill:** doc · **Time:** 30 min

Show how to run PIT queries directly from the CSV via DuckDB without loading anything into memory. This is the fastest path for exploratory work and one of the strongest "wow" demos.

---

## Lower leverage (nice but not blocking)

### R9 — Continuous monitoring
NSE publishes new PRs continuously. A weekly GitHub Actions workflow that runs `fetch_press_releases.py + parse_all + build_history + pytest + validate --skip-wayback` and opens a PR on diff would keep the dataset auto-updated. Triage volunteers welcome.

### R10 — Visual gallery
A `docs/gallery.md` with 5–10 charts derived from the dataset (sector-rotation plot across the 15 sector indices, churn distribution per family, longest-tenured Nifty 50 members, etc.). Each is a 20-line script + PNG.

### R11 — Zenodo DOI registration
Once a release is tagged, register on Zenodo for a citable DOI. One-time, ~10 minutes. Owner-only task (requires GitHub repo admin).

### R12 — Add corporate-action overlays
Splits, bonuses, demergers — useful for any backtest that consumes this. Probably a separate dataset with cross-references, not folded into the membership table.

### R13 — Per-family famous-transitions backfill
Gate 3 currently has 29 hand-curated PIT checks. Most are on broad indices (Nifty 50 / Nifty 500). Backfilling 3–5 famous events per sector / strategy / thematic index would tighten regression detection considerably. Source: NSE Indices factsheets + press releases.

---

## How to claim a task

1. Comment on the existing GitHub Issue (or open a new one referencing the task ID, e.g. `[R1b] 2014 seed snapshots`).
2. State your timeline. If a task has been claimed for >30 days without progress, others can pick it up.
3. Open a PR linked to the issue.

## How to propose a new task

Open a GitHub Issue with the prefix `[Roadmap]` describing:
- The problem in user terms ("backtests that filter on sector membership can't be done with the current dataset").
- The proposed solution.
- What's the leverage — who benefits, by how much.

Tasks that block someone's production use of the dataset jump the queue.
