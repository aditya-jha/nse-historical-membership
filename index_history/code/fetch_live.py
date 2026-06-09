"""Fast live-only fetch: download every URL in _index.json from niftyindices.com.

Skips Wayback fallback (its rate limits dominate runtime). Failed URLs
are recorded; a separate Wayback pass can pick them up later.

Run: python -m index_history.code.fetch_live
"""
from __future__ import annotations
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
PR_DIR = ROOT / "data" / "press_releases"
INDEX_FILE = PR_DIR / "_index.json"
FAIL_FILE = PR_DIR / "_live_failures.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    adapter = requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


SESSION = _make_session()


def fetch_one(url: str) -> tuple[str, str, int]:
    fname = urlparse(url).path.rsplit("/", 1)[-1]
    out = PR_DIR / fname
    if out.exists() and out.stat().st_size > 0:
        return (url, "cached", out.stat().st_size)
    try:
        r = SESSION.get(url, timeout=20)
        if r.status_code == 200 and r.content[:4] == b"%PDF":
            out.write_bytes(r.content)
            return (url, "ok", len(r.content))
        return (url, f"http_{r.status_code}", 0)
    except requests.RequestException as e:
        return (url, f"err_{type(e).__name__}", 0)


def main():
    urls = json.loads(INDEX_FILE.read_text())
    print(f"Inventory: {len(urls)} URLs")

    t0 = time.time()
    results = {"cached": 0, "ok": 0}
    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=24) as pool:
        futs = {pool.submit(fetch_one, u): u for u in urls}
        for i, fut in enumerate(as_completed(futs), 1):
            url, status, _ = fut.result()
            if status in ("cached", "ok"):
                results[status] += 1
            else:
                failures.append((url, status))
            if i % 100 == 0 or i == len(urls):
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta = (len(urls) - i) / rate if rate > 0 else 0
                print(
                    f"  {i}/{len(urls)} ({rate:.1f}/s, ETA {eta:.0f}s) "
                    f"cached={results['cached']} ok={results['ok']} fail={len(failures)}"
                )

    print()
    print(f"Done in {time.time()-t0:.1f}s — cached: {results['cached']}, "
          f"ok: {results['ok']}, fail: {len(failures)}")
    FAIL_FILE.write_text(json.dumps(failures, indent=2))
    print(f"Failures recorded → {FAIL_FILE}")


if __name__ == "__main__":
    main()
