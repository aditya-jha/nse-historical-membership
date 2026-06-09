"""Build index_membership_history from current snapshot + parsed PR events.

Algorithm:
  Phase 1 — walk BACKWARD from current snapshot through events
    (most recent first), reversing each event, to compute the membership
    set as it stood on COVERAGE_FLOOR.
  Phase 2 — walk FORWARD from COVERAGE_FLOOR through events
    (oldest first), emitting one interval row per
    (index, symbol, valid_from, valid_to) into index_membership_history.

Rationale: walking backward alone is enough to compute membership at any
historical date, but to *write* clean half-open intervals
[valid_from, valid_to) to the table, walking forward is simpler — every
exclude event closes an open interval and every include event opens a new
one.

A symbol that is a member in the current snapshot but never appears in any
include event we've observed gets `valid_from = COVERAGE_FLOOR` with a note
that the true entry date is unknown (i.e. predates our PR coverage).

Run: python -m index_history.code.build_history [--floor YYYY-MM-DD]
"""
from __future__ import annotations
import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

try:
    from sqlalchemy import text
except ImportError:  # only required for DB write path
    text = None

ROOT = Path(__file__).resolve().parent.parent
PARSED_DIR = ROOT / "data" / "parsed"
OVERRIDES_DIR = ROOT / "data" / "manual_overrides"

# `tools.postgres.connection` is an internal-dev dependency. Public users run
# build_history.py with --csv-out (no DB write); the import is therefore
# lazy and only required when actually writing to the DB.
sys.path.insert(0, str(ROOT.parent))

from index_history.code import registry as _reg

TARGET_INDEX_IDS: tuple[int, ...] = _reg.target_index_ids()
DEFAULT_FLOOR = date(2014, 1, 1)

# Per-index inception dates from the registry. Walking back past launch is
# meaningless — the index didn't exist yet — so we clamp the floor.
INDEX_LAUNCH: dict[int, date] = _reg.index_launch()


@dataclass(frozen=True)
class Event:
    effective_date: date
    publication_date: Optional[date]
    index_id: int
    excluded: tuple[str, ...]
    included: tuple[str, ...]
    source_url: str
    source_pdf: str
    source: str = "press_release"  # or "merger" for manual overrides


def _load_parsed_events() -> list[Event]:
    events: list[Event] = []
    for path in sorted(PARSED_DIR.glob("*.json")):
        d = json.loads(path.read_text())
        if not d.get("is_index_maintenance"):
            continue
        if not d.get("effective_date"):
            continue
        eff = datetime.fromisoformat(d["effective_date"]).date()
        pub = (
            datetime.fromisoformat(d["publication_date"]).date()
            if d.get("publication_date") else None
        )
        for ev in d.get("events", []):
            if ev["index_id"] not in TARGET_INDEX_IDS:
                continue
            events.append(Event(
                effective_date=eff,
                publication_date=pub,
                index_id=ev["index_id"],
                excluded=_canon_list(ev["excluded"]),
                included=_canon_list(ev["included"]),
                source_url=d.get("source_url", ""),
                source_pdf=d.get("source_pdf", path.stem + ".pdf"),
            ))
    return events


def _load_overrides() -> list[Event]:
    """Manual overrides for events that PR PDFs miss (mergers, name changes,
    early-termination cases, etc). Each override JSON has the same schema as
    a parsed PR but with `source: 'merger' | 'manual'`.

    Files whose top-level `_schema` field is `"renames"` are NOT events;
    those are loaded separately by _load_renames().
    """
    out: list[Event] = []
    if not OVERRIDES_DIR.exists():
        return out
    for path in sorted(OVERRIDES_DIR.glob("*.json")):
        d = json.loads(path.read_text())
        if d.get("_schema") == "renames":
            continue
        if "effective_date" not in d or "events" not in d:
            continue  # not an event file; skip silently
        eff = datetime.fromisoformat(d["effective_date"]).date()
        for ev in d["events"]:
            if ev["index_id"] not in TARGET_INDEX_IDS:
                continue
            out.append(Event(
                effective_date=eff,
                publication_date=eff,
                index_id=ev["index_id"],
                excluded=_canon_list(ev.get("excluded", [])),
                included=_canon_list(ev.get("included", [])),
                source_url=d.get("source_url", ""),
                source_pdf=d.get("source_pdf", path.name),
                source=d.get("source", "manual"),
            ))
    return out


def _load_renames() -> dict[str, str]:
    """Load symbol_renames.json and resolve transitive chains.

    Returns dict {historical_symbol → terminal_canonical_symbol}. Multi-step
    chains (e.g., MOTHERSUMI → MSUMI → MOTHERSON) collapse to the terminal.
    """
    path = OVERRIDES_DIR / "symbol_renames.json"
    if not path.exists():
        return {}
    d = json.loads(path.read_text())
    direct = {}  # one-step
    for r in d.get("renames", []):
        old = (r.get("old") or "").upper().strip()
        new = (r.get("new") or "").upper().strip()
        if not old or not new or old == new:
            continue
        direct[old] = new

    # Resolve transitive
    resolved: dict[str, str] = {}
    for old in direct:
        seen = {old}
        cur = direct[old]
        while cur in direct and cur not in seen:
            seen.add(cur)
            cur = direct[cur]
        resolved[old] = cur
    return resolved


RENAMES: dict[str, str] = {}  # populated in main()


def _canon(sym: str) -> str:
    s = sym.upper().strip()
    out = RENAMES.get(s, s)
    return "" if out == "_DUMMY_DROP" else out


def _canon_list(syms) -> tuple[str, ...]:
    return tuple(c for c in (_canon(s) for s in syms) if c)


SNAPSHOT_DIR = ROOT / "data" / "current_snapshot"

# Snapshot filenames come from the registry (slug + .csv).
_SNAPSHOT_FILES: dict[int, str] = {
    s.id: f"{s.snapshot_slug}.csv" for s in _reg.load()
}


def _load_current_snapshot() -> dict[int, list[tuple[str, Optional[float]]]]:
    """Seed the walk-back from NSE Indices' authoritative published CSVs in
    data/current_snapshot/. These are produced by fetch_nse_snapshot.py.

    The prior seed (internal index_equity_map table) carried 5-7 stale Next 50
    entries that NSE's published list did not (ABBOTINDIA, ALKEM, IDBI, MRF,
    PETRONET, UBL, MCDOWELL-N). The walk-back propagated them backward,
    producing systematic +5/+17/+19 over-counts on every historical date.
    NSE's published CSV is the source of truth.
    """
    import csv as _csv
    out: dict[int, list[tuple[str, Optional[float]]]] = {}
    if not SNAPSHOT_DIR.exists():
        raise RuntimeError(
            f"Current-snapshot directory not found: {SNAPSHOT_DIR}\n"
            f"Run: python -m index_history.code.fetch_nse_snapshot"
        )
    missing = []
    for idx, fname in _SNAPSHOT_FILES.items():
        path = SNAPSHOT_DIR / fname
        if not path.exists():
            missing.append(fname)
            continue
        with path.open() as f:
            rows = list(_csv.DictReader(f))
        out[idx] = [
            (r["symbol"].upper().strip(), None)
            for r in rows
            if r.get("symbol")
            and not r["symbol"].upper().startswith("DUMMY")
            and not r["symbol"].upper().startswith("TEMP")
        ]
    if missing:
        print(
            f"  WARN: {len(missing)} snapshot CSVs missing — these indices "
            f"will be skipped. Run fetch_nse_snapshot to populate. Examples: "
            f"{missing[:3]}"
        )
    return out


def build_intervals(
    current: dict[int, list[tuple[str, Optional[float]]]],
    events: list[Event],
    floor: date,
):
    """Yield (index_id, symbol, valid_from, valid_to, weightage, source, source_url, notes)."""
    events_by_index: dict[int, list[Event]] = defaultdict(list)
    for ev in events:
        events_by_index[ev.index_id].append(ev)
    for k in events_by_index:
        events_by_index[k].sort(key=lambda e: e.effective_date)

    for index_id, snapshot in current.items():
        snapshot_set = {c for c in (_canon(s) for s, _ in snapshot) if c}
        weight_lookup = {_canon(s): w for s, w in snapshot if _canon(s)}
        evs = events_by_index.get(index_id, [])

        # Dedup superseded excludes. NSE sometimes announces a removal, then
        # defers and re-announces it with a later effective date (e.g. the
        # March-2020 reconstitution was COVID-deferred to June 2020, so the
        # same symbol appears in an exclude list twice ~3 months apart with no
        # re-inclusion between). Naively, the forward pass closes the interval
        # at the *first* exclude and then treats the *second* as an orphan,
        # fabricating a phantom "member since launch" stub. The truth is a
        # single exit on the *last* of a run of excludes-without-an-intervening
        # -include. Compute which earlier excludes to skip, per symbol.
        _per_sym: dict[str, list[tuple[date, str]]] = defaultdict(list)
        for ev in evs:
            for s in ev.included:
                _per_sym[s.upper().strip()].append((ev.effective_date, "inc"))
            for s in ev.excluded:
                _per_sym[s.upper().strip()].append((ev.effective_date, "exc"))
        skip_exclude: set[tuple[str, date]] = set()
        for s, timeline in _per_sym.items():
            timeline.sort()
            pending: list[date] = []  # excludes since the last inclusion
            for d, kind in timeline:
                if kind == "exc":
                    pending.append(d)
                else:  # an inclusion resets the run
                    for earlier in pending[:-1]:
                        skip_exclude.add((s, earlier))
                    pending = []
            for earlier in pending[:-1]:
                skip_exclude.add((s, earlier))

        # Per-index floor: never emit intervals that begin before the index
        # was launched (Nifty Midcap 150 / Smallcap 250 only exist from
        # 2016-04-01).
        idx_floor = max(floor, INDEX_LAUNCH.get(index_id, floor))

        # Phase 1: walk BACKWARD to find membership at idx_floor. Stop
        # walking past idx_floor — events before the launch date are not
        # meaningful for this index.
        m = set(snapshot_set)
        for ev in reversed(evs):
            if ev.effective_date <= idx_floor:
                break
            for s in ev.included:
                m.discard(s.upper().strip())
            for s in ev.excluded:
                cs = s.upper().strip()
                if (cs, ev.effective_date) in skip_exclude:
                    continue
                m.add(cs)

        # Phase 2: walk FORWARD emitting intervals.
        active_since: dict[str, date] = {s: idx_floor for s in m}
        active_source: dict[str, tuple[str, str]] = {
            s: ("snapshot_floor", "") for s in m  # truly unknown — predates coverage
        }
        for ev in evs:
            if ev.effective_date <= idx_floor:
                continue
            D = ev.effective_date
            for raw in ev.excluded:
                s = raw.upper().strip()
                if (s, D) in skip_exclude:
                    continue
                if s in active_since:
                    src, src_url = active_source.get(s, (ev.source, ev.source_url))
                    yield (
                        index_id, s,
                        active_since[s], D,
                        weight_lookup.get(s),
                        src, src_url,
                        f"closed by {ev.source_pdf}",
                    )
                    del active_since[s]
                    active_source.pop(s, None)
                else:
                    # Excluded but never recorded as active — usually means it
                    # was added and removed within an event horizon we don't
                    # cover; record a "pre-floor membership" stub.
                    yield (
                        index_id, s,
                        idx_floor, D,
                        None,
                        "snapshot_floor", ev.source_url,
                        f"orphan-exclude (no prior include in coverage)",
                    )
            for raw in ev.included:
                s = raw.upper().strip()
                if s in active_since:
                    # Re-include without prior exclude — data anomaly. Keep older
                    # interval open and overwrite valid_from. Log as note.
                    active_since[s] = D
                else:
                    active_since[s] = D
                active_source[s] = (ev.source, ev.source_url)
        # Snapshot reconciliation: any "active" interval whose symbol is NOT
        # in NSE's authoritative current snapshot must have been excluded by
        # an event we didn't parse. Close it at the most recent semi-annual
        # review date that's strictly after its open. NSE does Index Maintenance
        # twice a year, effective end-March and end-September, with the result
        # public ~5 weeks earlier. We use those review effective-dates as the
        # best-guess close.
        from datetime import date as _date
        def _next_review_after(d: _date) -> _date:
            """Next end-March or end-September after d."""
            for yr in range(d.year, d.year + 6):
                for m, day in ((3, 31), (9, 30)):
                    cand = _date(yr, m, day)
                    if cand > d:
                        return cand
            return _date(d.year + 6, 3, 31)

        for s, start in list(active_since.items()):
            if s in snapshot_set:
                # Genuinely current member.
                src, src_url = active_source.get(s, ("snapshot", ""))
                yield (
                    index_id, s,
                    start, None,
                    weight_lookup.get(s),
                    src, src_url,
                    None,
                )
            else:
                # Open but not in NSE official current snapshot — it was
                # excluded between our last captured inclusion (`start`) and
                # today, in a PR we did not parse.
                close_date = _next_review_after(start)
                if close_date > _date.today():
                    # No suitable review date in the past — drop the interval
                    # entirely rather than emit a known-wrong open interval.
                    continue
                src, src_url = active_source.get(s, ("snapshot", ""))
                yield (
                    index_id, s,
                    start, close_date,
                    weight_lookup.get(s),
                    src, src_url,
                    "inferred-exclude: not in NSE current snapshot, no PR found "
                    "(closed at next semi-annual review)",
                )

        # Reverse reconciliation: any symbol in NSE's current snapshot but NOT
        # currently active in our walk-forward was re-included by a PR we
        # didn't parse. Open a new interval at the most recent semi-annual
        # review on or before today (best-guess re-inclusion date). Without
        # this step, symbols like BANKBARODA (excluded 2021-03-31, re-included
        # later) drop out of "today's" membership entirely.
        def _last_review_before_or_eq(d: _date) -> _date:
            for yr in range(d.year, d.year - 6, -1):
                for m, day in ((9, 30), (3, 31)):
                    cand = _date(yr, m, day)
                    if cand <= d:
                        return cand
            return _date(d.year - 6, 3, 31)

        active_now = set(active_since.keys())
        missing = snapshot_set - active_now
        for s in sorted(missing):
            reopen = _last_review_before_or_eq(_date.today())
            yield (
                index_id, s,
                reopen, None,
                weight_lookup.get(s),
                "snapshot", "",
                "inferred-include: in NSE current snapshot, no PR found "
                "(opened at most-recent semi-annual review)",
            )


def write_to_db(intervals_iter, dry_run: bool = False) -> int:
    rows = list(intervals_iter)
    if dry_run:
        print(f"[dry-run] {len(rows)} interval rows would be written")
        return len(rows)

    from tools.postgres.connection import engine  # type: ignore  # internal dev dep
    with engine.begin() as conn:
        # Per spec, we DO NOT clobber existing index_equity_map_archive.
        # We DO own index_membership_history fully.
        conn.execute(text("DELETE FROM index_membership_history"))
        for idx, sym, vfrom, vto, w, src, surl, notes in rows:
            conn.execute(
                text("""
                    INSERT INTO index_membership_history
                      (index_id, symbol, valid_from, valid_to, weightage, source, source_url, notes)
                    VALUES (:i, :s, :vf, :vt, :w, :src, :url, :n)
                    ON CONFLICT (index_id, symbol, valid_from) DO UPDATE
                      SET valid_to = EXCLUDED.valid_to,
                          weightage = EXCLUDED.weightage,
                          source = EXCLUDED.source,
                          source_url = EXCLUDED.source_url,
                          notes = EXCLUDED.notes
                """),
                {"i": idx, "s": sym, "vf": vfrom, "vt": vto, "w": w,
                 "src": src, "url": surl, "n": notes},
            )
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--floor", type=str, default="2014-01-01",
                    help="Coverage floor date (YYYY-MM-DD). Default 2014-01-01.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--csv-out", type=str, default=None,
                    help="If set, write intervals to this CSV path and skip DB write.")
    args = ap.parse_args()
    floor = datetime.fromisoformat(args.floor).date()

    global RENAMES
    RENAMES = _load_renames()
    print(f"Renames loaded: {len(RENAMES)}")
    for old, new in sorted(RENAMES.items()):
        print(f"  {old:14s} → {new}")
    print()

    events = _load_parsed_events() + _load_overrides()
    current = _load_current_snapshot()

    print(f"Floor: {floor}")
    print(f"Events: {len(events)}")
    for idx in TARGET_INDEX_IDS:
        n = len([e for e in events if e.index_id == idx])
        print(f"  index_id={idx}: {n} events, current={len(current.get(idx, []))}")

    intervals = list(build_intervals(current, events, floor))
    print(f"\nTotal intervals: {len(intervals)}")

    if args.csv_out:
        import csv as _csv
        from pathlib import Path as _Path
        out = _Path(args.csv_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        # Name lookup (canonical) for human-readable output.
        names = {s.id: s.canonical_name for s in _reg.load()}
        with out.open("w", newline="") as f:
            w = _csv.writer(f)
            w.writerow(["index_id", "index_name", "symbol", "valid_from",
                        "valid_to", "weightage", "source", "source_url", "notes"])
            for row in intervals:
                idx, sym, vf, vt, weight, src, src_url, notes = row
                w.writerow([idx, names.get(idx, ""), sym, vf, vt or "",
                            weight or "", src or "", src_url or "", notes or ""])
        print(f"Wrote {len(intervals)} intervals to {out}")
        # Keep the generated coverage doc in sync with the headline CSV, but
        # only when we just rebuilt the canonical headline file (not an ad-hoc
        # --csv-out path). Never let this optional step fail the build.
        try:
            repo_root = _Path(__file__).resolve().parents[2]
            canonical = repo_root / "index_history" / "data" / "index_membership_history.csv"
            if out.resolve() == canonical.resolve():
                import sys as _sys
                if str(repo_root) not in _sys.path:
                    _sys.path.insert(0, str(repo_root))
                from tools.build_coverage import main as _refresh_coverage
                _refresh_coverage()
        except Exception as e:  # noqa: BLE001
            print(f"  (coverage refresh skipped: {e})")
        return

    n = write_to_db(iter(intervals), dry_run=args.dry_run)
    print(f"Wrote {n} rows to index_membership_history")


if __name__ == "__main__":
    main()
