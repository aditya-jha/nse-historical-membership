# Contributing

Anything that improves the dataset's quality or coverage is welcome. The five contribution paths below are listed in rough order of leverage — `Add a missed press release` and `Fix pre-2018 cardinality` are by far the highest-impact.

---

## 1. Add a missed press release

Symptom: a famous-transition or archive cross-check fails because we never saw the PR that recorded it.

```bash
# Find the missing PR — usually a niftyindices.com URL or a Wayback snapshot.
# Drop it into the cache and re-parse.
cp ind_prs<DDMMYYYY>.pdf index_history/data/press_releases/
python -m index_history.code.parse_all
python -m index_history.code.build_history --csv-out index_history/data/index_membership_history.csv
pytest tests/
```

If the parser handles it, you're done — open a PR with the new CSV and the updated `parsed/<stem>.json`. If the parser fails on it, see path 4 below.

---

## 2. Add a manual override

Use when an event isn't well-described by a single PR — mergers, demergers, ticker renames. Examples already in `index_history/data/manual_overrides/`:

- `lti_mindtree_merger_2022.json`
- `pvr_inox_merger_2023.json`
- `bse_promotion_2024-03-28.json`
- `symbol_renames.json` — global rename map applied during walk-back

Add a new JSON in the same shape, then re-run `build_history` to regenerate the CSV. Include the upstream NSE source URL (or Wayback snapshot) in the JSON's `note` field.

F&O equivalents: an event with no circular goes in `fno_history/data/manual_events.json` (with its source), and a rename while in F&O goes in `RENAMES` in `fno_history/code/build_history.py`. Then run `python -m fno_history.code.build_history --csv-out fno_history/data/fno_membership_history.csv`.

---

## 3. Fix pre-2018 cardinality

This is the largest open coverage gap. The parser now reads the pre-2017 press releases (R1a), but walking back from today's snapshot still over-counts some indices before 2018 (Gate 4). The fix is a per-index 2014 seed snapshot to walk forward from — see R1b in `ROADMAP.md`.

If you can source authoritative early constituent lists (Wayback copies of NSE's `ind_*list.csv`), this is the single contribution that improves the dataset most.

---

## 4. Improve the parser

Look at `parse_press_release.py`. Common ways it fails:

- A new section-header layout (e.g. `"NIFTY 500 Index"` vs `"Nifty 500"`).
- A new exclusion-marker phrase (`is being excluded` vs `shall be excluded`).
- Multi-line wrapped table rows that pdfplumber's text extraction joins poorly.

Open a PR with both the parser fix and the previously-failing PDF as a fixture. The `parse_all` summary will show the recovery (`im_with_events` count goes up).

---

## 5. Validation gates

`validate.py` runs five gates: snapshot match (G1), internal consistency (G2), famous transitions (G3), daily cardinality (G4) and Wayback cross-check (G5). New transitions worth adding to `FAMOUS`:

- Any merger / demerger that touches a Nifty 50 / 500 constituent.
- Any rename (canonicalised name in the CSV must match).
- Any documented inclusion/exclusion at a known effective date.

A new transition is one line in `validate.py`'s `FAMOUS` list and one line in `tests/test_pit_lookups.py`'s parametrization.

---

## What we *don't* accept

- **Index data sourced from non-public/scraped paid feeds.** Everything in this repo is derived from NSE's free public press releases and circulars, and stays that way.
- **Raw NSE PR PDFs in commits.** They're under NSE's copyright; we redistribute parsed facts, not the source documents. `data/press_releases/` and `data/circulars/` are gitignored.
- **Index methodology changes from anonymous sources.** Cite the upstream NSE document.

---

## Open a PR

1. Branch off `main`. Name your branch `fix/<short-description>` or `feat/<short-description>`.
2. Run `pytest tests/` — must be green.
3. Run `python -m index_history.code.validate` if you touched index data — paste the relevant section of the validation report into the PR description.
4. Include the NSE source URL (or Wayback link) for any factual change in the PR body.

---

## Asking for new tasks / changes you can't implement yourself

Open an Issue on GitHub describing:
- What's wrong / what's missing (be specific — "ABBOTINDIA's exclusion event isn't captured" beats "data is wrong").
- The upstream NSE source (URL / circular number / PR date).
- The expected vs actual output, ideally with a `pit_cli` query or a 3-line pandas snippet.

Issues that block production use of the dataset get prioritized over feature requests.
