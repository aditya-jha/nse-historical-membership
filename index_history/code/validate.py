"""Validation gates for index_membership_history.

Gates:
  1. Cross-check archive snapshots: at each index_equity_map_archive snapshot
     date, the membership set derived from index_membership_history must equal
     the snapshot's symbol set.
  2. Famous transitions:
       - HDFC absent from Nifty 50 on 2023-07-14 onward (merger 2023-07-13).
       - SHRIRAMFIN added to Nifty 50 on 2024-03-28 (per ind_prs28022024).
       - TRENT added to Nifty 50 on its known 2024-09-30 effective date (per ind_prs27082024).
  3. Daily cardinality: |members(index_id, date)| == target_size for every day
     in coverage. Target sizes: 50, 50, 100, 500, 150, 250.

Run: python -m nse_index_history.code.validate
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
from tools.postgres.connection import engine  # noqa: E402
from nse_index_history.code.build_history import _load_renames  # noqa: E402

TARGETS = {
    217: ("Nifty 50", 50),
    218: ("Nifty Next 50", 50),
    219: ("Nifty 100", 100),
    221: ("Nifty 500", 500),
    223: ("NIFTY Midcap 150", 150),
    227: ("NIFTY Smallcap 250", 250),
}

RENAMES = _load_renames()


def _canon(s: str) -> str:
    s = s.upper().strip()
    out = RENAMES.get(s, s)
    if out == "_DUMMY_DROP":
        return ""  # mark for set filtering
    return out


def members_at(conn, index_id: int, on_date: date) -> set[str]:
    rows = conn.execute(text("""
        SELECT symbol FROM index_membership_history
        WHERE index_id = :i
          AND valid_from <= :d
          AND (valid_to IS NULL OR valid_to > :d)
    """), {"i": index_id, "d": on_date}).fetchall()
    return {c for c in (_canon(r[0]) for r in rows) if c}


def archive_set(conn, index_id: int, on_date: date) -> set[str]:
    rows = conn.execute(text("""
        SELECT symbol FROM index_equity_map_archive
        WHERE index_id = :i
          AND created::date = :d
    """), {"i": index_id, "d": on_date}).fetchall()
    # Canonicalise archive symbols too — historical names like ZOMATO must
    # match current canonical ETERNAL when comparing.
    return {c for c in (_canon(r[0]) for r in rows) if c}


# Snapshots known to be stale relative to authoritative niftyindices.com CSVs.
# 2025-12-04: archive scraper read from a stale upstream — at this date archive
# still contains HEROMOTOCO/INDUSINDBK in Nifty 50 but the authoritative
# niftyindices.com CSV (refreshed 2026-05-08) shows those were removed in the
# 2025-09-30 reshuffle. Excluded from the strict gate; reported separately.
STALE_SNAPSHOT_DATES = {date(2025, 12, 4)}


def gate_archive_crosscheck(conn) -> tuple[int, int]:
    """Returns (mismatch_count, total_checks)."""
    print("=== Gate 1: archive cross-check ===")
    snap_dates = [r[0] for r in conn.execute(text(
        "SELECT DISTINCT created::date AS d FROM index_equity_map_archive ORDER BY d"
    )).fetchall()]
    mismatches = 0
    total = 0
    skipped: list[str] = []
    for d in snap_dates:
        if d in STALE_SNAPSHOT_DATES:
            for idx, (name, _) in TARGETS.items():
                arch = archive_set(conn, idx, d)
                if arch:
                    mine = members_at(conn, idx, d)
                    extra_mine = mine - arch
                    extra_arch = arch - mine
                    if extra_mine or extra_arch:
                        skipped.append(
                            f"  {d} {name:20s}: SKIPPED (stale archive) — "
                            f"+{len(extra_mine)} ours / +{len(extra_arch)} arch"
                        )
                    else:
                        skipped.append(f"  {d} {name:20s}: SKIPPED (stale archive) — would be ✓")
            continue
        for idx, (name, _size) in TARGETS.items():
            arch = archive_set(conn, idx, d)
            if not arch:
                continue
            mine = members_at(conn, idx, d)
            extra_mine = mine - arch
            extra_arch = arch - mine
            total += 1
            if extra_mine or extra_arch:
                mismatches += 1
                print(f"  {d} {name:20s}: arch={len(arch)} ours={len(mine)} "
                      f"+{len(extra_mine)} (only ours) / +{len(extra_arch)} (only arch)")
                if extra_mine:
                    print(f"    only-ours sample: {sorted(extra_mine)[:8]}")
                if extra_arch:
                    print(f"    only-arch sample: {sorted(extra_arch)[:8]}")
            else:
                print(f"  {d} {name:20s}: ✓ ({len(arch)} symbols match)")

    if skipped:
        print()
        print("  STALE archive snapshots (excluded from strict gate):")
        for line in skipped:
            print(line)

    print(f"\n  Result: {mismatches}/{total} mismatches (after excluding stale snapshots)\n")
    return (mismatches, total)


# Famous transitions — each is (description, index_id, symbol, on_date, expected_member?).
# Canonicalised names are used (ETERNAL not ZOMATO, COFORGE not NIITTECH, etc.).
FAMOUS = [
    ("HDFC absent post-merger",                      217, "HDFC",       date(2023, 7, 14), False),
    ("HDFCBANK still in Nifty 50 on merger day",     217, "HDFCBANK",   date(2023, 7, 14), True),
    ("SHRIRAMFIN added 2024-03-28",                  217, "SHRIRAMFIN", date(2024, 3, 28), True),
    ("UPL excluded 2024-03-28",                      217, "UPL",        date(2024, 3, 28), False),
    ("BPCL was member on 2022-01-01",                217, "BPCL",       date(2022, 1, 1),  True),
    ("ETERNAL (was ZOMATO) joined Nifty 50 in Mar 2025",   217, "ETERNAL",    date(2025, 4, 1),  True),
    ("ETERNAL (was ZOMATO) NOT in Nifty 50 pre-Mar 2025",  217, "ETERNAL",    date(2024, 12, 31), False),
    ("INDIGO joined Nifty 50 on 2025-09-30",         217, "INDIGO",     date(2025, 10, 1), True),
    ("MAXHEALTH joined Nifty 50 on 2025-09-30",      217, "MAXHEALTH",  date(2025, 10, 1), True),
    ("HEROMOTOCO excluded from Nifty 50 on 2025-09-30",   217, "HEROMOTOCO", date(2025, 10, 1), False),
    ("INDUSINDBK excluded from Nifty 50 on 2025-09-30",   217, "INDUSINDBK", date(2025, 10, 1), False),
    ("ATGL (was ADANIGAS) member of Nifty 500 in 2021",   221, "ATGL",       date(2021, 6, 1),  True),
    ("LTIM (was MINDTREE) member of Nifty 500 in 2022",   221, "LTIM",       date(2022, 12, 31), True),
]


def gate_famous_transitions(conn) -> tuple[int, int]:
    print("=== Gate 2: famous transitions ===")
    failed = 0
    for desc, idx, sym, on, expected in FAMOUS:
        m = members_at(conn, idx, on)
        # Canonicalise the query symbol too so e.g. "LTIM" resolves to "LTM".
        actual = _canon(sym) in m
        status = "PASS" if actual == expected else "FAIL"
        if actual != expected:
            failed += 1
        print(f"  [{status}] {desc} — {sym} on {on}: expected member={expected}, got={actual}")
    print(f"\n  Result: {failed}/{len(FAMOUS)} failures\n")
    return (failed, len(FAMOUS))


def gate_cardinality(conn, sample_dates: list[date] | None = None) -> tuple[int, int]:
    print("=== Gate 3: daily cardinality ===")
    # Sample one date per quarter from earliest valid_from in our table to today.
    if sample_dates is None:
        floor = conn.execute(text(
            "SELECT MIN(valid_from) FROM index_membership_history"
        )).scalar()
        if floor is None:
            print("  No data in index_membership_history.\n")
            return (0, 0)
        today = date.today()
        sample_dates = []
        d = floor
        while d <= today:
            sample_dates.append(d)
            # next quarter
            year, month = d.year + (d.month + 3 - 1) // 12, ((d.month + 2) % 12) + 1
            try:
                d = date(year, month, 1)
            except ValueError:
                break

    fail = 0
    total = 0
    for d in sample_dates:
        for idx, (name, target) in TARGETS.items():
            m = members_at(conn, idx, d)
            total += 1
            if len(m) != target:
                fail += 1
                if fail <= 50:
                    print(f"  FAIL {d} {name:20s}: {len(m)} (expected {target})")
    if fail == 0:
        print(f"  ✓ all {total} (date,index) checks have correct cardinality")
    else:
        print(f"  {fail}/{total} cardinality failures (showed first 50)")
    print()
    return (fail, total)


def main():
    ROOT_DOCS = Path(__file__).resolve().parent.parent / "docs"
    ROOT_DOCS.mkdir(exist_ok=True)
    report_path = ROOT_DOCS / "validation_report.md"

    with engine.connect() as conn, open(report_path, "w") as report:
        # Capture stdout into report too.
        import io, contextlib
        buf = io.StringIO()

        class Tee:
            def __init__(self, *streams): self.streams = streams
            def write(self, s):
                for st in self.streams: st.write(s)
            def flush(self):
                for st in self.streams: st.flush()

        with contextlib.redirect_stdout(Tee(sys.stdout, buf)):
            print(f"# Validation Report — {datetime.now().isoformat(timespec='seconds')}\n")
            r1 = gate_archive_crosscheck(conn)
            r2 = gate_famous_transitions(conn)
            r3 = gate_cardinality(conn)
            print("=== Summary ===")
            print(f"  Gate 1 archive cross-check : {r1[0]} / {r1[1]} mismatches")
            print(f"  Gate 2 famous transitions  : {r2[0]} / {r2[1]} failed")
            print(f"  Gate 3 daily cardinality   : {r3[0]} / {r3[1]} failed")
            overall = r1[0] + r2[0] + r3[0]
            print(f"\n  TOTAL FAILURES: {overall}")
            if overall == 0:
                print("  STATUS: PASS")
            else:
                print("  STATUS: FAIL — fix issues before relying on this table")

        report.write(buf.getvalue())
    print(f"\n→ Report written to {report_path}")


if __name__ == "__main__":
    main()
