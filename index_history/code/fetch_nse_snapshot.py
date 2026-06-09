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
    python -m index_history.code.fetch_nse_snapshot
"""
from __future__ import annotations
import csv
import io
from pathlib import Path

import requests

from index_history.code import registry as _reg

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "data" / "current_snapshot"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; nse-historical-membership/0.1)",
    "Accept": "text/csv,*/*",
}

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}


_API_SESSION: requests.Session | None = None


def _api_session() -> requests.Session:
    """Warmed-up session for nseindia.com JSON API (which requires cookies)."""
    global _API_SESSION
    if _API_SESSION is None:
        s = requests.Session()
        s.headers.update(BROWSER_HEADERS)
        s.get("https://www.nseindia.com/", timeout=15)
        _API_SESSION = s
    return _API_SESSION


def fetch_one(url: str) -> list[dict[str, str]]:
    """Fetch a snapshot. Two transports:
      - http(s)://...csv   → archives.nseindia.com CSV
      - nseapi:NIFTY ALPHA 50  → nseindia.com JSON API
    """
    if url.startswith("nseapi:"):
        index_name = url[len("nseapi:"):]
        s = _api_session()
        r = s.get(
            "https://www.nseindia.com/api/equity-stockIndices",
            params={"index": index_name}, timeout=30,
        )
        r.raise_for_status()
        rows = r.json().get("data", [])
        # First row is the index itself; remainder are constituents.
        return [
            {"Symbol": row.get("symbol", ""), "Company Name": row.get("meta", {}).get("companyName", "")}
            for row in rows[1:]
        ]
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    if "html" in r.headers.get("Content-Type", "").lower():
        raise RuntimeError(f"{url} returned HTML (probable 404 page)")
    return list(csv.DictReader(io.StringIO(r.text)))


def main() -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    summary: list[tuple[int, str, str, str, int]] = []
    failures: list[tuple[str, str]] = []
    for spec in _reg.load():
        out = SNAPSHOT_DIR / f"{spec.snapshot_slug}.csv"
        try:
            rows = fetch_one(spec.snapshot_url)
        except Exception as e:  # noqa: BLE001
            failures.append((spec.canonical_name, f"{type(e).__name__}: {e}"))
            print(f"  {spec.id} {spec.canonical_name:32s} → FAIL ({e})")
            continue
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["symbol", "company_name"])
            for r in rows:
                w.writerow([r.get("Symbol", "").strip(), r.get("Company Name", "").strip()])
        summary.append((spec.id, spec.canonical_name, spec.family,
                        spec.snapshot_slug, len(rows)))
        print(f"  {spec.id} {spec.canonical_name:32s} → {len(rows):3d} symbols")

    manifest = SNAPSHOT_DIR / "_manifest.csv"
    with manifest.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index_id", "name", "family", "n_symbols", "slug"])
        for index_id, name, family, slug, n in summary:
            w.writerow([index_id, name, family, n, slug])
    print(f"\nManifest → {manifest}  ({len(summary)} ok, {len(failures)} failed)")
    if failures:
        for name, err in failures:
            print(f"  FAIL: {name}  {err}")


if __name__ == "__main__":
    main()
