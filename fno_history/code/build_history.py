"""Build fno_membership_history from parsed FAOP introduction/exclusion events.

Algorithm: walk forward through events sorted by effective_date.
  - Each `introduction` opens an interval [eff_date, NULL] for each symbol.
  - Each `exclusion`   closes the most recent open interval at eff_date for that symbol.
  - A symbol re-introduced after exclusion gets a new interval (membership history).

Idempotent: full table-rebuild each run.

Run: python -m fno_history.code.build_history
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
PARSED_DIR = ROOT / "data" / "parsed"

sys.path.insert(0, str(ROOT.parent))
from tools.postgres.connection import engine  # noqa: E402


def load_events() -> list[dict]:
    out = []
    for f in sorted(PARSED_DIR.glob("*.json")):
        d = json.loads(f.read_text())
        if d.get("kind") not in ("introduction", "exclusion"):
            continue
        if not d.get("effective_date") or not d.get("symbols"):
            continue
        out.append(d)
    return out


def build_intervals(events: list[dict]):
    """Yield (symbol, valid_from, valid_to, source_url, circular_no, notes)."""
    events = sorted(events, key=lambda e: (e["effective_date"], e["kind"] == "exclusion"))
    # ^ for same-day events, process introductions before exclusions

    open_intervals: dict[str, dict] = {}   # symbol → record-in-progress
    completed: list[dict] = []

    for ev in events:
        eff = datetime.fromisoformat(ev["effective_date"]).date()
        for raw in ev["symbols"]:
            s = raw.upper().strip()
            if ev["kind"] == "introduction":
                # Open new interval. If one is already open (re-introduction
                # without a recorded exclusion), close the old one at this date.
                if s in open_intervals:
                    old = open_intervals.pop(s)
                    old["valid_to"] = eff
                    completed.append(old)
                open_intervals[s] = {
                    "symbol": s,
                    "valid_from": eff,
                    "valid_to": None,
                    "source_url": ev.get("source_url", ""),
                    "circular_no": ev.get("circular_no"),
                    "notes": None,
                }
            else:  # exclusion
                if s in open_intervals:
                    open_intervals[s]["valid_to"] = eff
                    open_intervals[s]["notes"] = (
                        f"closed by {ev.get('circular_no') or ev.get('source_pdf')}"
                    )
                    completed.append(open_intervals.pop(s))
                else:
                    # Excluded without prior recorded introduction: emit a
                    # stub interval with valid_from=NULL (predates coverage)
                    completed.append({
                        "symbol": s,
                        "valid_from": date(2000, 1, 1),  # coverage floor sentinel
                        "valid_to": eff,
                        "source_url": ev.get("source_url", ""),
                        "circular_no": ev.get("circular_no"),
                        "notes": "exclusion without prior introduction in coverage",
                    })

    # Emit currently-open intervals
    for rec in open_intervals.values():
        completed.append(rec)
    return completed


def write(records: list[dict]):
    with engine.begin() as c:
        c.execute(text("DELETE FROM fno_membership_history"))
        for r in records:
            c.execute(text("""
                INSERT INTO fno_membership_history
                  (symbol, valid_from, valid_to, source, source_url, circular_no, notes)
                VALUES (:s, :vf, :vt, 'circular', :url, :no, :n)
                ON CONFLICT (symbol, valid_from) DO UPDATE
                  SET valid_to = EXCLUDED.valid_to,
                      source_url = EXCLUDED.source_url,
                      circular_no = EXCLUDED.circular_no,
                      notes = EXCLUDED.notes
            """), {
                "s": r["symbol"],
                "vf": r["valid_from"],
                "vt": r["valid_to"],
                "url": r.get("source_url", ""),
                "no": r.get("circular_no"),
                "n": r.get("notes"),
            })


def main():
    events = load_events()
    print(f"Events: {len(events)} ({sum(1 for e in events if e['kind']=='introduction')} intro / "
          f"{sum(1 for e in events if e['kind']=='exclusion')} excl)")
    intervals = build_intervals(events)
    print(f"Intervals: {len(intervals)}")
    open_now = sum(1 for r in intervals if r["valid_to"] is None)
    print(f"Open intervals (currently F&O member): {open_now}")
    write(intervals)
    print("Written to fno_membership_history.")


if __name__ == "__main__":
    main()
