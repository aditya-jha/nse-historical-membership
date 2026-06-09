"""F&O membership point-in-time CLI.

Usage:
  python -m fno_history.code.pit_cli members --as-of 2022-06-15
  python -m fno_history.code.pit_cli was-fno --symbol HDIL --as-of 2018-04-26
  python -m fno_history.code.pit_cli was-fno --symbol HDIL --as-of 2018-04-28
  python -m fno_history.code.pit_cli changes --from 2024-01-01 --to 2024-12-31
"""
from __future__ import annotations
import argparse
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
from tools.postgres.connection import engine  # noqa: E402


def cmd_members(args):
    on = datetime.fromisoformat(args.as_of).date()
    with engine.connect() as c:
        rows = c.execute(text("""
            SELECT symbol, valid_from, valid_to, circular_no
            FROM fno_membership_history
            WHERE valid_from <= :d AND (valid_to IS NULL OR valid_to > :d)
            ORDER BY symbol
        """), {"d": on}).fetchall()
    print(f"# {len(rows)} F&O members on {on}")
    for s, vf, vt, cn in rows:
        print(f"  {s:18s}  [{vf} → {vt or 'open'}]  {cn or ''}")


def cmd_was(args):
    on = datetime.fromisoformat(args.as_of).date()
    with engine.connect() as c:
        row = c.execute(text("""
            SELECT valid_from, valid_to, circular_no FROM fno_membership_history
            WHERE symbol=:s AND valid_from <= :d AND (valid_to IS NULL OR valid_to > :d)
        """), {"s": args.symbol.upper(), "d": on}).fetchone()
    if row:
        print(f"{args.symbol.upper()} F&O member on {on}: YES "
              f"[interval {row[0]} → {row[1] or 'open'}, {row[2] or ''}]")
    else:
        # Show closest prior event
        closest = c.execute(text("""
            SELECT valid_from, valid_to FROM fno_membership_history
            WHERE symbol=:s ORDER BY valid_from
        """) if False else text("SELECT 1")).fetchall() if False else None
        with engine.connect() as c2:
            hist = c2.execute(text("""
                SELECT valid_from, valid_to FROM fno_membership_history
                WHERE symbol=:s ORDER BY valid_from
            """), {"s": args.symbol.upper()}).fetchall()
        print(f"{args.symbol.upper()} F&O member on {on}: NO")
        if hist:
            print(f"  All known intervals: {hist}")


def cmd_changes(args):
    a = datetime.fromisoformat(args.from_).date()
    b = datetime.fromisoformat(args.to).date()
    with engine.connect() as c:
        added = c.execute(text("""
            SELECT symbol, valid_from, circular_no FROM fno_membership_history
            WHERE valid_from > :a AND valid_from <= :b ORDER BY valid_from, symbol
        """), {"a": a, "b": b}).fetchall()
        removed = c.execute(text("""
            SELECT symbol, valid_to, circular_no FROM fno_membership_history
            WHERE valid_to > :a AND valid_to <= :b ORDER BY valid_to, symbol
        """), {"a": a, "b": b}).fetchall()
    print(f"# F&O changes between {a} and {b}")
    print(f"# Introductions ({len(added)}):")
    for s, d, cn in added:
        print(f"  + {s:18s} {d}  {cn or ''}")
    print(f"# Exclusions ({len(removed)}):")
    for s, d, cn in removed:
        print(f"  - {s:18s} {d}  {cn or ''}")


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)

    m = sp.add_parser("members"); m.add_argument("--as-of", required=True); m.set_defaults(func=cmd_members)
    w = sp.add_parser("was-fno"); w.add_argument("--symbol", required=True); w.add_argument("--as-of", required=True); w.set_defaults(func=cmd_was)
    c = sp.add_parser("changes"); c.add_argument("--from", dest="from_", required=True); c.add_argument("--to", required=True); c.set_defaults(func=cmd_changes)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
