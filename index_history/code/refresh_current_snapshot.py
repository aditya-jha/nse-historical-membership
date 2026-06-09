"""Refresh `index_equity_map` from authoritative niftyindices.com CSVs.

Discovery: each index has a stable CSV URL like
  https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv

These are server-rendered, cookie-free, and reflect today's true membership.
The local `index_equity_map` table can be stale (last refresh by some other
scraper); refresh it before validating walk-backward output.

Run: python -m index_history.code.refresh_current_snapshot
"""
from __future__ import annotations
import csv
import io
import sys
from pathlib import Path

import requests
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
from tools.postgres.connection import engine  # noqa: E402

# index_id → (display_name, csv_path on niftyindices.com)
TARGETS = {
    217: ("Nifty 50",          "ind_nifty50list.csv"),
    218: ("Nifty Next 50",     "ind_niftynext50list.csv"),
    219: ("Nifty 100",         "ind_nifty100list.csv"),
    221: ("Nifty 500",         "ind_nifty500list.csv"),
    223: ("NIFTY Midcap 150",  "ind_niftymidcap150list.csv"),
    227: ("NIFTY Smallcap 250","ind_niftysmallcap250list.csv"),
}

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def fetch_index_csv(csv_name: str) -> list[dict]:
    url = f"https://www.niftyindices.com/IndexConstituent/{csv_name}"
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    text_data = r.content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text_data))
    return list(reader)


def main():
    with engine.begin() as conn:
        for idx, (name, csv_name) in TARGETS.items():
            rows = fetch_index_csv(csv_name)
            print(f"[{idx}] {name}: {len(rows)} symbols from {csv_name}")
            # Wipe + insert
            conn.execute(text("DELETE FROM index_equity_map WHERE index_id=:i"),
                         {"i": idx})
            for r in rows:
                sym = (r.get("Symbol") or "").strip().upper()
                ind = (r.get("Industry") or "").strip()
                if not sym:
                    continue
                conn.execute(text("""
                    INSERT INTO index_equity_map (index_id, symbol, industry)
                    VALUES (:i, :s, :ind)
                """), {"i": idx, "s": sym, "ind": ind})
        # Quick sanity print
        for idx, (name, _) in TARGETS.items():
            n = conn.execute(text(
                "SELECT COUNT(*) FROM index_equity_map WHERE index_id=:i"
            ), {"i": idx}).scalar()
            print(f"  index_equity_map[{idx}] {name}: {n}")


if __name__ == "__main__":
    main()
