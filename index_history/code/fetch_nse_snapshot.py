"""Fetch NSE Indices' authoritative current-membership CSVs.

Writes one CSV per index to data/current_snapshot/<slug>.csv. These files
are committed to the repo and serve as the seed for build_history's walk-back.

This replaces the prior seed (an internal `index_equity_map` table) which
proved unreliable: it carried 5-7 stale Next 50 entries (ABBOTINDIA, ALKEM,
IDBI, MRF, PETRONET, UBL, MCDOWELL-N) that NSE's published list did not.
The walk-back faithfully propagated those errors backward, producing a
+5/+17/+19 over-count on every historical date (2024-01-27 archive cross-check
showed exactly that drift).

Usage:
    python -m nse_index_history.code.fetch_nse_snapshot
"""
from __future__ import annotations
import csv
import io
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "data" / "current_snapshot"

# (index_id, canonical_name, slug, NSE archive URL)
INDICES = [
    (217, "Nifty 50",           "nifty_50",            "https://archives.nseindia.com/content/indices/ind_nifty50list.csv"),
    (218, "Nifty Next 50",      "nifty_next_50",       "https://archives.nseindia.com/content/indices/ind_niftynext50list.csv"),
    (219, "Nifty 100",          "nifty_100",           "https://archives.nseindia.com/content/indices/ind_nifty100list.csv"),
    (221, "Nifty 500",          "nifty_500",           "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"),
    (223, "Nifty Midcap 150",   "nifty_midcap_150",    "https://archives.nseindia.com/content/indices/ind_niftymidcap150list.csv"),
    (227, "Nifty Smallcap 250", "nifty_smallcap_250",  "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; nse-historical-membership/0.1)",
    "Accept": "text/csv,*/*",
}


def fetch_one(url: str) -> list[dict[str, str]]:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def main() -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    summary: list[tuple[int, str, int]] = []
    for index_id, name, slug, url in INDICES:
        rows = fetch_one(url)
        out = SNAPSHOT_DIR / f"{slug}.csv"
        # Write a normalized 2-column version so consumers don't depend on
        # NSE's exact column order.
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["symbol", "company_name"])
            for r in rows:
                w.writerow([r.get("Symbol", "").strip(), r.get("Company Name", "").strip()])
        summary.append((index_id, name, len(rows)))
        print(f"  {index_id} {name:20s} → {len(rows):3d} symbols  ({out})")

    # Write a manifest so build_history can read it once.
    manifest = SNAPSHOT_DIR / "_manifest.csv"
    with manifest.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index_id", "name", "n_symbols", "slug", "source_url"])
        for (index_id, name, n), (_, _, slug, url) in zip(summary, INDICES):
            w.writerow([index_id, name, n, slug, url])
    print(f"\nManifest → {manifest}")


if __name__ == "__main__":
    main()
