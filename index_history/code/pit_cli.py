"""Point-in-time index membership CLI.

Usage:
  python -m index_history.code.pit_cli member --index "Nifty 50" --as-of 2022-06-15
  python -m index_history.code.pit_cli member --index-id 217 --as-of 2022-06-15
  python -m index_history.code.pit_cli changes --index "Nifty 50" --from 2024-01-01 --to 2024-12-31
  python -m index_history.code.pit_cli was-member --index "Nifty 50" --symbol HDFC --as-of 2023-07-14
"""
from __future__ import annotations
import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
from tools.postgres.connection import engine  # noqa: E402

NAME_TO_ID = {
    "Nifty 50": 217,
    "Nifty Next 50": 218,
    "Nifty 100": 219,
    "Nifty 500": 221,
    "NIFTY Midcap 150": 223,
    "Nifty Midcap 150": 223,
    "NIFTY Smallcap 250": 227,
    "Nifty Smallcap 250": 227,
}


def _resolve_index(args) -> int:
    if args.index_id:
        return args.index_id
    if args.index:
        if args.index in NAME_TO_ID:
            return NAME_TO_ID[args.index]
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT id FROM nse_indices WHERE LOWER(name) = LOWER(:n)"
            ), {"n": args.index}).fetchone()
            if row:
                return row[0]
        sys.exit(f"unknown --index '{args.index}'. Try --index-id directly.")
    sys.exit("specify --index NAME or --index-id N")


def cmd_member(args):
    idx = _resolve_index(args)
    on = datetime.fromisoformat(args.as_of).date()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT symbol, valid_from, valid_to, weightage, source
            FROM index_membership_history
            WHERE index_id = :i
              AND valid_from <= :d
              AND (valid_to IS NULL OR valid_to > :d)
            ORDER BY symbol
        """), {"i": idx, "d": on}).fetchall()
    print(f"# {len(rows)} members of index_id={idx} on {on}")
    for sym, vf, vt, w, src in rows:
        wstr = f"{float(w):6.3f}" if w is not None else "  -  "
        print(f"  {sym:18s} {wstr}  [{vf} → {vt or 'open'}]  src={src}")


def cmd_changes(args):
    idx = _resolve_index(args)
    a = datetime.fromisoformat(args.from_).date()
    b = datetime.fromisoformat(args.to).date()
    with engine.connect() as conn:
        # Inclusions: valid_from in (a, b]
        inc = conn.execute(text("""
            SELECT symbol, valid_from, source FROM index_membership_history
            WHERE index_id=:i AND valid_from > :a AND valid_from <= :b
            ORDER BY valid_from, symbol
        """), {"i": idx, "a": a, "b": b}).fetchall()
        # Exclusions: valid_to in (a, b]
        exc = conn.execute(text("""
            SELECT symbol, valid_to, source FROM index_membership_history
            WHERE index_id=:i AND valid_to > :a AND valid_to <= :b
            ORDER BY valid_to, symbol
        """), {"i": idx, "a": a, "b": b}).fetchall()
    print(f"# index_id={idx} changes between {a} and {b}")
    print(f"# Inclusions ({len(inc)}):")
    for sym, vf, src in inc:
        print(f"  + {sym:18s} {vf}  src={src}")
    print(f"# Exclusions ({len(exc)}):")
    for sym, vt, src in exc:
        print(f"  - {sym:18s} {vt}  src={src}")


def cmd_was_member(args):
    idx = _resolve_index(args)
    on = datetime.fromisoformat(args.as_of).date()
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT 1 FROM index_membership_history
            WHERE index_id=:i AND symbol=:s
              AND valid_from <= :d AND (valid_to IS NULL OR valid_to > :d)
        """), {"i": idx, "s": args.symbol.upper(), "d": on}).fetchone()
    print(f"{args.symbol.upper()} member of index_id={idx} on {on}: {'YES' if row else 'NO'}")


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)

    m = sp.add_parser("member", help="list members of an index on a date")
    m.add_argument("--index", help='e.g. "Nifty 50"')
    m.add_argument("--index-id", type=int)
    m.add_argument("--as-of", required=True)
    m.set_defaults(func=cmd_member)

    c = sp.add_parser("changes", help="inclusions/exclusions in a date range")
    c.add_argument("--index")
    c.add_argument("--index-id", type=int)
    c.add_argument("--from", dest="from_", required=True)
    c.add_argument("--to", required=True)
    c.set_defaults(func=cmd_changes)

    w = sp.add_parser("was-member", help="check if a symbol was in an index on a date")
    w.add_argument("--index")
    w.add_argument("--index-id", type=int)
    w.add_argument("--symbol", required=True)
    w.add_argument("--as-of", required=True)
    w.set_defaults(func=cmd_was_member)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
