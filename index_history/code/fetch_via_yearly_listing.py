"""Fetch PR PDFs via the per-year listing endpoint.

Discovery: `niftyindices.com/press-release?date=YYYY` is server-rendered
HTML with every PR for that year. This is the canonical listing — the
JS-rendered `/Resources/Press-Release` page we found earlier was a dead end.

Run: python -m index_history.code.fetch_via_yearly_listing
"""
from __future__ import annotations
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
PR_DIR = ROOT / "data" / "press_releases"
INDEX_FILE = PR_DIR / "_index.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

PDF_RE = re.compile(r'/Press_Release/(ind_prs\d{8}(?:_\d+)?\.pdf)', re.I)


def list_year(year: int) -> set[str]:
    url = f"https://www.niftyindices.com/press-release?date={year}"
    r = SESSION.get(url, timeout=30)
    if r.status_code != 200:
        print(f"  {year}: HTTP {r.status_code}")
        return set()
    pdfs = {f"https://niftyindices.com/Press_Release/{m}" for m in PDF_RE.findall(r.text)}
    print(f"  {year}: {len(pdfs)} PDF refs")
    return pdfs


def fetch_one(url: str) -> tuple[str, str, int]:
    fname = urlparse(url).path.rsplit("/", 1)[-1]
    out = PR_DIR / fname
    if out.exists() and out.stat().st_size > 0 and out.read_bytes()[:4] == b"%PDF":
        return (url, "cached", out.stat().st_size)
    try:
        r = SESSION.get(url, timeout=60)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            out.write_bytes(r.content)
            return (url, "ok", len(r.content))
        return (url, f"http_{r.status_code}", 0)
    except requests.RequestException as e:
        return (url, f"err_{type(e).__name__}", 0)


def main():
    print("=== Listing per year ===")
    inventory: set[str] = set()
    for year in range(2014, 2027):
        inventory |= list_year(year)
        time.sleep(0.5)  # polite

    inventory = sorted(inventory)
    print(f"\n=== Total unique URLs: {len(inventory)} ===")
    INDEX_FILE.write_text(json.dumps(inventory, indent=2))

    print("\n=== Downloading ===")
    t0 = time.time()
    results = {"cached": 0, "ok": 0}
    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        for i, (url, status, _) in enumerate(pool.map(fetch_one, inventory), 1):
            if status in ("cached", "ok"):
                results[status] += 1
            else:
                failures.append((url, status))
            if i % 100 == 0 or i == len(inventory):
                el = time.time() - t0
                rate = i / el if el > 0 else 0
                print(f"  {i}/{len(inventory)} ({rate:.1f}/s) "
                      f"cached={results['cached']} ok={results['ok']} fail={len(failures)}")

    print(f"\nDone in {time.time()-t0:.1f}s — cached: {results['cached']}, "
          f"ok: {results['ok']}, fail: {len(failures)}")
    if failures:
        print("Failures (first 20):")
        for u, s in failures[:20]:
            print(f"  {s}: {u}")


if __name__ == "__main__":
    main()
