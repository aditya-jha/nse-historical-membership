"""Fetch every NSE Press Release PDF we can find for 2014-today.

Sources of URL inventory (unioned):
  1. Current sitemap.xml on niftyindices.com.
  2. Historical sitemap.xml snapshots from archive.org Wayback CDX.
  3. Wayback CDX listing of `niftyindices.com/Press_Release/*.pdf` directly.
  4. Probe-sweep: for each year 2014..today, probe Feb 27/28 and Aug 27/28
     (and a +/- 3 day window) with suffix '', '_1', '_2', '_3', '_4'.
     Captures the semi-annual Index Maintenance Sub-committee announcements.

Each unique PDF is downloaded once, idempotently, to data/press_releases/.
If a URL 404s on the live host, we fall back to the most recent Wayback copy.

Run:  python -m index_history.code.fetch_press_releases
"""
from __future__ import annotations
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
PR_DIR = ROOT / "data" / "press_releases"
PR_DIR.mkdir(parents=True, exist_ok=True)
INDEX_FILE = ROOT / "data" / "press_releases" / "_index.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

PDF_RE = re.compile(
    r"https?://(?:www\.)?niftyindices\.com/Press_Release/(ind_prs\d{8}(?:_\d+)?\.pdf)",
    re.I,
)


def _normalise(url: str) -> str:
    """Canonicalise to https://niftyindices.com/Press_Release/<filename>."""
    m = PDF_RE.search(url)
    if not m:
        return url
    return f"https://niftyindices.com/Press_Release/{m.group(1)}"


def fetch_current_sitemap() -> set[str]:
    print("[1/4] current sitemap.xml")
    r = SESSION.get("https://www.niftyindices.com/sitemap.xml", timeout=30)
    r.raise_for_status()
    urls = {_normalise(u) for u in PDF_RE.findall(r.text) or []}
    # PDF_RE returns filename only (group 1); we need full URL — re-extract:
    urls = set()
    for full in re.findall(
        r"https?://(?:www\.)?niftyindices\.com/Press_Release/ind_prs\d{8}(?:_\d+)?\.pdf",
        r.text,
        re.I,
    ):
        urls.add(_normalise(full))
    print(f"    found {len(urls)} URLs")
    return urls


def fetch_wayback_sitemap_snapshots() -> set[str]:
    print("[2/4] Wayback historical sitemaps")
    r = SESSION.get(
        "https://web.archive.org/cdx/search/cdx?"
        "url=niftyindices.com/sitemap.xml"
        "&output=json&filter=statuscode:200&fl=timestamp"
        "&from=20140101&to=20260601&collapse=timestamp:6",
        timeout=60,
    )
    r.raise_for_status()
    rows = r.json()[1:]
    timestamps = [row[0] for row in rows]
    print(f"    {len(timestamps)} snapshots to walk")
    urls: set[str] = set()
    for ts in timestamps:
        wb_url = f"https://web.archive.org/web/{ts}id_/https://niftyindices.com/sitemap.xml"
        try:
            rr = SESSION.get(wb_url, timeout=45)
            if rr.status_code != 200:
                continue
            for full in re.findall(
                r"https?://(?:www\.)?niftyindices\.com/Press_Release/ind_prs\d{8}(?:_\d+)?\.pdf",
                rr.text,
                re.I,
            ):
                urls.add(_normalise(full))
        except requests.RequestException as e:
            print(f"    WARN {ts}: {e}")
        time.sleep(0.3)  # be polite
    print(f"    union after Wayback sitemaps: {len(urls)}")
    return urls


def fetch_wayback_cdx_direct() -> set[str]:
    print("[3/4] Wayback CDX direct (Press_Release/*)")
    r = SESSION.get(
        "https://web.archive.org/cdx/search/cdx?"
        "url=niftyindices.com%2FPress_Release%2F*"
        "&output=json&filter=statuscode:200&fl=timestamp,original"
        "&from=20140101&to=20260601",
        timeout=90,
    )
    r.raise_for_status()
    rows = r.json()[1:]
    urls = set()
    for _ts, orig in rows:
        if orig.lower().endswith(".pdf"):
            n = _normalise(orig)
            if PDF_RE.search(n):
                urls.add(n)
    print(f"    {len(urls)} URLs")
    return urls


def probe_sweep(start_year: int = 2014, end_year: int | None = None) -> set[str]:
    """Probe URL pattern for likely Index Maintenance announce dates.

    Convention: NSE publishes results around Feb 27/28 (for end-March effective)
    and Aug 27/28 (for end-September effective). Off-cycle events also use this
    URL pattern but on arbitrary dates — those are caught by sitemap union.
    Here we just shore up the gap before Wayback's coverage starts (mid-2022).
    """
    print("[4/4] probe-sweep for semi-annual review dates")
    today = date.today()
    end_year = end_year or today.year
    candidates: list[str] = []
    for y in range(start_year, end_year + 1):
        for m in (2, 3, 8, 9):
            # last 5 days of the month
            for d in range(24, 32):
                try:
                    dt = date(y, m, d)
                except ValueError:
                    continue
                if dt > today:
                    continue
                stem = f"ind_prs{dt.strftime('%d%m%Y')}"
                for sfx in ("", "_1", "_2", "_3", "_4"):
                    candidates.append(
                        f"https://niftyindices.com/Press_Release/{stem}{sfx}.pdf"
                    )
    print(f"    {len(candidates)} probes ({start_year}-{end_year})")
    found = set()

    def head(u):
        try:
            r = SESSION.head(u, timeout=8, allow_redirects=True)
            return u if r.status_code == 200 else None
        except requests.RequestException:
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        for i, hit in enumerate(pool.map(head, candidates)):
            if hit:
                found.add(hit)
            if (i + 1) % 500 == 0:
                print(f"    probed {i+1}/{len(candidates)}; hits so far: {len(found)}")
    print(f"    {len(found)} hits")
    return found


def download_one(url: str) -> tuple[str, str, int]:
    """Returns (url, status, size_bytes). Skips if file already cached."""
    fname = urlparse(url).path.rsplit("/", 1)[-1]
    out = PR_DIR / fname
    if out.exists() and out.stat().st_size > 0:
        return (url, "cached", out.stat().st_size)

    # Try live host first.
    try:
        r = SESSION.get(url, timeout=30)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            out.write_bytes(r.content)
            return (url, "live", len(r.content))
    except requests.RequestException:
        pass

    # Fallback to Wayback most-recent snapshot.
    try:
        avail = SESSION.get(
            "https://archive.org/wayback/available",
            params={"url": url},
            timeout=20,
        ).json()
        snap = avail.get("archived_snapshots", {}).get("closest")
        if snap and snap.get("status") == "200":
            wb_url = snap["url"].replace("/http", "id_/http", 1)
            r = SESSION.get(wb_url, timeout=60)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                out.write_bytes(r.content)
                return (url, "wayback", len(r.content))
    except requests.RequestException:
        pass

    return (url, "FAIL", 0)


def main():
    inventory: set[str] = set()
    inventory |= fetch_current_sitemap()
    inventory |= fetch_wayback_sitemap_snapshots()
    inventory |= fetch_wayback_cdx_direct()
    inventory |= probe_sweep(start_year=2014)

    inventory = sorted(inventory)
    print()
    print(f"=== Total unique PR URLs: {len(inventory)} ===")

    # Year histogram
    from collections import Counter
    yrs = Counter()
    for u in inventory:
        m = re.search(r"ind_prs\d{4}(\d{4})", u)
        if m:
            yrs[m.group(1)] += 1
    print("Year histogram:")
    for y in sorted(yrs):
        print(f"  {y}: {yrs[y]}")

    # Persist URL list
    INDEX_FILE.write_text(json.dumps(inventory, indent=2))
    print(f"Wrote {INDEX_FILE}")

    # Download
    print()
    print("=== Downloading PDFs ===")
    results = {"cached": 0, "live": 0, "wayback": 0, "FAIL": []}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for url, status, size in pool.map(download_one, inventory):
            if status == "FAIL":
                results["FAIL"].append(url)
            else:
                results[status] = results.get(status, 0) + 1
    print(
        f"Downloaded — cached: {results['cached']} | live: {results['live']} | "
        f"wayback: {results['wayback']} | failed: {len(results['FAIL'])}"
    )
    if results["FAIL"]:
        print("FAILED URLs (will retry next run):")
        for u in results["FAIL"]:
            print(f"  {u}")


if __name__ == "__main__":
    main()
