"""Fetch NSE F&O circulars (introduction / exclusion notices) via the
nseindia.com circulars API.

Discovery: nseindia.com/api/circulars?dept=FAO&fromDate=DD-MM-YYYY&toDate=DD-MM-YYYY
returns JSON. Filter to subjects matching "Introduction of Futures & Options
Contracts" or "Exclusion of Futures and Options". Download each PDF.

nseindia.com is anti-bot — must warm session by hitting the parent page first
to acquire cookies, then call the API with proper headers.

Run: python -m fno_history.code.fetch_circulars
"""
from __future__ import annotations
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
CIRC_DIR = ROOT / "data" / "circulars"
CIRC_DIR.mkdir(parents=True, exist_ok=True)
INDEX_FILE = CIRC_DIR / "_index.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

INCL_RE = re.compile(r"Introduction\s+of\s+Futures\s+(?:&|and)\s+Options", re.I)
EXCL_RE = re.compile(r"Exclusion\s+of\s+Futures\s+(?:&|and)\s+Options", re.I)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    # Warm: hit homepage and circulars page to seed cookies.
    for url in (
        "https://www.nseindia.com/",
        "https://www.nseindia.com/resources/exchange-communication-circulars",
    ):
        try:
            s.get(url, timeout=20)
            time.sleep(0.5)
        except requests.RequestException as e:
            print(f"  warm fail {url}: {e}")
    return s


def fetch_year_window(s: requests.Session, from_dt: date, to_dt: date) -> list[dict]:
    """API rejects very large windows; chunk by ~6 months."""
    url = "https://www.nseindia.com/api/circulars"
    params = {
        "dept": "FAO",
        "fromDate": from_dt.strftime("%d-%m-%Y"),
        "toDate": to_dt.strftime("%d-%m-%Y"),
    }
    headers = {
        "Referer": "https://www.nseindia.com/resources/exchange-communication-circulars",
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
    }
    r = s.get(url, params=params, headers=headers, timeout=45)
    r.raise_for_status()
    j = r.json()
    return j.get("data", [])


def is_relevant(row: dict) -> str | None:
    sub = row.get("sub") or ""
    if INCL_RE.search(sub):
        return "introduction"
    if EXCL_RE.search(sub):
        return "exclusion"
    return None


def download_pdf(s: requests.Session, url: str) -> tuple[str, int] | None:
    fname = urlparse(url).path.rsplit("/", 1)[-1]
    out = CIRC_DIR / fname
    if out.exists() and out.stat().st_size > 0 and out.read_bytes()[:4] == b"%PDF":
        return ("cached", out.stat().st_size)
    try:
        r = s.get(url, timeout=45,
                  headers={"Referer": "https://www.nseindia.com/resources/exchange-communication-circulars"})
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            out.write_bytes(r.content)
            return ("ok", len(r.content))
    except requests.RequestException as e:
        return (f"err_{type(e).__name__}", 0)
    return ("not_pdf", 0)


def main(start_year: int = 2014):
    s = make_session()
    today = date.today()

    # Walk year-by-year. The API copes with year-sized windows.
    inventory: list[dict] = []
    for year in range(start_year, today.year + 1):
        a = date(year, 1, 1)
        b = date(year, 12, 31) if year < today.year else today
        try:
            rows = fetch_year_window(s, a, b)
        except Exception as e:
            print(f"  {year}: ERR {e}")
            continue
        relevant = [r for r in rows if is_relevant(r)]
        inventory.extend(relevant)
        print(f"  {year}: {len(rows)} circs total, {len(relevant)} F&O incl/excl")
        time.sleep(1.0)

    # De-dup by circNumber
    seen = set()
    deduped = []
    for r in inventory:
        cn = r.get("circNumber")
        if cn and cn not in seen:
            seen.add(cn)
            r["_kind"] = is_relevant(r)
            deduped.append(r)
    inventory = deduped
    print(f"\nTotal unique relevant circulars: {len(inventory)}")
    INDEX_FILE.write_text(json.dumps(inventory, indent=2, default=str))

    # Download PDFs
    print("\nDownloading PDFs...")
    urls = [r.get("circFilelink") for r in inventory if r.get("circFilelink")]
    cached = ok = fail = 0
    fails: list[str] = []
    # Single-threaded to be polite on nseindia
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i, (url, result) in enumerate(zip(urls, pool.map(lambda u: download_pdf(s, u), urls)), 1):
            if result is None or result[0] not in ("ok", "cached"):
                fail += 1
                fails.append(url)
            elif result[0] == "cached":
                cached += 1
            else:
                ok += 1
            if i % 20 == 0 or i == len(urls):
                print(f"  {i}/{len(urls)} cached={cached} ok={ok} fail={fail}")

    print(f"\nDone — cached: {cached}, ok: {ok}, fail: {fail}")
    if fails:
        print("Failures (first 10):")
        for u in fails[:10]:
            print(f"  {u}")


if __name__ == "__main__":
    main()
