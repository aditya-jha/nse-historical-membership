"""Build fno_membership_history from parsed FAOP introduction/exclusion events.

Algorithm: walk forward through events sorted by effective_date.
  - Each `introduction` opens an interval [eff_date, NULL] for each symbol.
  - Each `exclusion`   closes the most recent open interval at eff_date for that symbol.
  - Each `withdrawal`  CANCELS an announced introduction: the symbol's interval opened
    within the withdrawal window is deleted (it never took effect). A withdrawal that
    arrives before its introduction is processed suppresses that introduction.
  - A symbol re-introduced after exclusion gets a new interval (membership history).
  - Duplicate circulars (NSE re-issues the same notice as .pdf and .zip) are de-duplicated.

Idempotent: full table-rebuild each run.

Run:
    python -m fno_history.code.build_history --csv-out fno_history/data/fno_membership_history.csv
    python -m fno_history.code.build_history            # also write the Postgres table (internal)
"""
from __future__ import annotations
import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PARSED_DIR = ROOT / "data" / "parsed"

sys.path.insert(0, str(ROOT.parent))
# `tools.postgres.connection` is an internal-dev dependency (EntropyTester), imported only
# for the DB write so the public --csv-out path needs no database.


WITHDRAW_WINDOW_DAYS = 120   # an intro announced this long before the withdrawal can be cancelled
MANUAL_EVENTS = ROOT / "data" / "manual_events.json"

# Symbol renames that happened WHILE in F&O: an exclusion published under the new name must
# close the interval opened under the old one (PVR's 2017 interval stayed open after PVRINOX
# was excluded in 2025; RDEL->RNAVAL excluded 2018; SKSMICRO->BHARATFIN excluded 2019).
# Intervals keep the symbol as printed in their circular; matching uses the final name.
RENAMES: dict[str, str] = {
    "PVR": "PVRINOX", "RDEL": "RNAVAL", "SKSMICRO": "BHARATFIN", "KPIT": "BSOFT",
    "LTI": "LTIM", "LTIM": "LTM",
    "CADILAHC": "ZYDUSLIFE", "IDFCBANK": "IDFCFIRSTB", "L&TFH": "LTF",
    "MCDOWELL-N": "UNITDSPR", "MOTHERSUMI": "MOTHERSON", "NIITTECH": "COFORGE",
    "INFRATEL": "INDUSTOWER", "ZOMATO": "ETERNAL", "AMARAJABAT": "ARE&M",
    "IBULHSGFIN": "SAMMAANCAP", "EQUITAS": "EQUITASBNK",
}


def canon(sym: str) -> str:
    seen = set()
    while sym in RENAMES and sym not in seen:
        seen.add(sym)
        sym = RENAMES[sym]
    return sym


def load_events() -> list[dict]:
    out, seen = [], set()
    raw = [json.loads(f.read_text()) for f in sorted(PARSED_DIR.glob("*.json"))]
    if MANUAL_EVENTS.exists():
        raw += json.loads(MANUAL_EVENTS.read_text())
    # "- Update" circulars that withdraw an earlier circular (e.g. CONCOR's 2023 exclusion)
    cancelled = {d["cancels"] for d in raw if d.get("kind") == "cancels_circular"}
    for d in raw:
        if d.get("circular_no") in cancelled:
            continue
        if d.get("kind") not in ("introduction", "exclusion", "withdrawal"):
            continue
        if not d.get("symbols"):
            continue
        if d["kind"] != "withdrawal" and not d.get("effective_date"):
            continue
        if d["kind"] == "withdrawal" and not d.get("effective_date"):
            d["effective_date"] = d.get("circular_date")
        if not d.get("effective_date"):
            continue
        key = (d["kind"], d["effective_date"], tuple(sorted(s.upper() for s in d["symbols"])))
        if key in seen:          # same notice issued twice (.pdf + .zip bundle)
            continue
        seen.add(key)
        out.append(d)
    return out


def build_intervals(events: list[dict]):
    """Yield (symbol, valid_from, valid_to, source_url, circular_no, notes)."""
    order = {"introduction": 0, "withdrawal": 1, "exclusion": 2}
    events = sorted(events, key=lambda e: (e["effective_date"], order[e["kind"]]))
    # ^ same-day: introductions, then withdrawals (cancel them), then exclusions

    open_intervals: dict[str, dict] = {}   # canonical symbol → record-in-progress
    completed: list[dict] = []
    suppress: dict[str, date] = {}         # withdrawal seen before its introduction
    last_closed: dict[str, dict] = {}      # canonical symbol → interval closed by an exclusion

    for ev in events:
        eff = datetime.fromisoformat(ev["effective_date"]).date()
        for raw in ev["symbols"]:
            sym = raw.upper().strip()       # as printed in the circular (kept in the output)
            s = canon(sym)                  # matching key across renames
            if ev["kind"] == "withdrawal":
                rec = open_intervals.get(s)
                if rec and (eff - rec["valid_from"]).days <= WITHDRAW_WINDOW_DAYS:
                    open_intervals.pop(s)          # never took effect — drop it
                else:
                    suppress[s] = eff
                continue
            if ev["kind"] == "introduction" and s in suppress:
                if abs((eff - suppress[s]).days) <= WITHDRAW_WINDOW_DAYS:
                    suppress.pop(s)
                    continue
                suppress.pop(s)
            if ev["kind"] == "introduction":
                last_closed.pop(s, None)
                # Open new interval. If one is already open (re-introduction
                # without a recorded exclusion), close the old one at this date.
                if s in open_intervals:
                    if open_intervals[s]["valid_from"] == eff:
                        continue        # same-date re-announcement ("Update" circular)
                    old = open_intervals.pop(s)
                    old["valid_to"] = eff
                    completed.append(old)
                open_intervals[s] = {
                    "symbol": sym,
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
                    last_closed[s] = open_intervals.pop(s)
                    completed.append(last_closed[s])
                elif s in last_closed:
                    # Repeat exclusion with no re-introduction between: a revised/deferred
                    # date (MRF, APOLLOTYRE 05-27 -> 05-30) or a superseded notice (ZEEL
                    # 2023 -> 2024). Keep the LAST date, as index_history does.
                    rec = last_closed[s]
                    if eff > rec["valid_to"]:
                        rec["valid_to"] = eff
                        rec["notes"] = f"closed by {ev.get('circular_no') or ev.get('source_pdf')} (revised)"
                else:
                    # Excluded without prior recorded introduction: emit a
                    # stub interval with valid_from=NULL (predates coverage)
                    completed.append({
                        "symbol": sym,
                        "valid_from": date(2000, 1, 1),  # coverage floor sentinel
                        "valid_to": eff,
                        "source_url": ev.get("source_url", ""),
                        "circular_no": ev.get("circular_no"),
                        "notes": "exclusion without prior introduction in coverage",
                    })
                    last_closed[s] = completed[-1]

    # Emit currently-open intervals
    for rec in open_intervals.values():
        completed.append(rec)
    # Zero-length intervals carry no membership (an exclusion on the introduction date).
    return [r for r in completed if r["valid_to"] is None or r["valid_to"] > r["valid_from"]]


CSV_COLS = ["symbol", "valid_from", "valid_to", "source", "source_url", "circular_no", "notes"]


def write_csv(records: list[dict], path: Path):
    rows = sorted(records, key=lambda r: (r["symbol"], r["valid_from"]))
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({"symbol": r["symbol"], "valid_from": r["valid_from"],
                        "valid_to": r["valid_to"] or "", "source": "circular",
                        "source_url": r.get("source_url") or "", "circular_no": r.get("circular_no") or "",
                        "notes": r.get("notes") or ""})


def write(records: list[dict]):
    from sqlalchemy import text                    # internal dev deps — DB path only
    from tools.postgres.connection import engine
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-out", type=str, default=None, help="write the CSV and skip the DB")
    args = ap.parse_args()
    events = load_events()
    print(f"Events: {len(events)} ({sum(1 for e in events if e['kind']=='introduction')} intro / "
          f"{sum(1 for e in events if e['kind']=='exclusion')} excl)")
    intervals = build_intervals(events)
    print(f"Intervals: {len(intervals)}")
    open_now = sum(1 for r in intervals if r["valid_to"] is None)
    print(f"Open intervals (currently F&O member): {open_now}")
    if args.csv_out:
        write_csv(intervals, Path(args.csv_out))
        print(f"Wrote {args.csv_out}")
        return
    write(intervals)
    print("Written to fno_membership_history.")


if __name__ == "__main__":
    main()
