"""Bulk-download SHP XBRL files referenced by data/filings_index/*.json.

Resumable: skips files already on disk that look like valid XML (>1KB,
content starts with `<`). Polite rate-limit, optional parallelism.

Run:
    python -m shareholding_history.code.download_xbrl --workers 4 --sleep 0.15
    python -m shareholding_history.code.download_xbrl --tickers RELIANCE,KAYNES
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "data" / "filings_index"
XBRL_DIR = ROOT / "data" / "xbrl"
XBRL_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_PATH = ROOT / "data" / "xbrl_download_summary.json"

PROJECT_ROOT = ROOT.parent
REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern"


def _make_session() -> requests.Session:
    sys.path.insert(0, str(PROJECT_ROOT))
    from fno_history.code.fetch_circulars import make_session  # noqa: E402
    return make_session()


def _filename_from_url(url: str) -> str:
    return urlparse(url).path.rsplit("/", 1)[-1]


def _is_valid_xml(p: Path) -> bool:
    if not p.exists() or p.stat().st_size < 1024:
        return False
    head = p.read_bytes()[:200]
    return head.startswith(b"<?xml") or head.startswith(b"<")


def _enumerate_filings(targets: list[str] | None) -> list[tuple[str, str, str]]:
    """Returns list of (ticker, date, xbrl_url) tuples."""
    out = []
    files = sorted(INDEX_DIR.glob("*.json"))
    if targets:
        wanted = set(t.upper() for t in targets)
        files = [f for f in files if f.stem.upper() in wanted]
    for jf in files:
        try:
            data = json.loads(jf.read_text())
        except Exception:
            continue
        ticker = data.get("ticker") or jf.stem
        for fl in data.get("filings", []):
            url = fl.get("xbrl") or ""
            if not url or url in ("null", "-"):
                continue
            out.append((ticker, fl.get("date") or "", url))
    return out


def _fetch_one(s: requests.Session, ticker: str, date_str: str, url: str,
               retries: int = 2, retry_delay: float = 1.5) -> dict:
    fn = _filename_from_url(url)
    if not fn or fn in ("null", "-"):
        return {"ticker": ticker, "date": date_str, "url": url, "status": "bad_url"}
    out = XBRL_DIR / fn
    if _is_valid_xml(out):
        return {"ticker": ticker, "date": date_str, "url": url, "status": "cached", "size": out.stat().st_size}
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = s.get(url, timeout=45, headers={"Referer": REFERER})
            if r.status_code == 200 and r.content and (r.content[:5] == b"<?xml" or r.content[:1] == b"<"):
                out.write_bytes(r.content)
                return {"ticker": ticker, "date": date_str, "url": url, "status": "ok", "size": len(r.content)}
            last_err = f"http_{r.status_code}"
        except requests.RequestException as e:
            last_err = f"err_{type(e).__name__}"
        if attempt < retries:
            time.sleep(retry_delay)
    return {"ticker": ticker, "date": date_str, "url": url, "status": last_err or "fail"}


def _worker(task, sleep: float):
    ticker, date_str, url, session_holder = task
    s = session_holder["session"]
    r = _fetch_one(s, ticker, date_str, url)
    if r["status"] == "ok":
        time.sleep(sleep)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", help="Comma-separated tickers (default: all in filings_index/)")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--sleep", type=float, default=0.1, help="Per-worker sleep after successful fetch")
    ap.add_argument("--limit", type=int, help="Cap total filings to fetch (debug)")
    ap.add_argument("--refresh-every", type=int, default=2000,
                    help="Re-warm all worker sessions every N successful fetches")
    args = ap.parse_args()

    progress_path = ROOT / "data" / "download_xbrl_progress.txt"

    def log(msg: str):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with progress_path.open("a") as f:
            f.write(line + "\n")

    targets = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None
    filings = _enumerate_filings(targets)
    if args.limit:
        filings = filings[: args.limit]

    # Dedup by XBRL filename: same URL can be referenced by multiple tickers
    # (dual listings, symbol renames). One download covers all references.
    seen_fn = set()
    deduped: list[tuple[str, str, str]] = []
    for ticker, date_str, url in filings:
        fn = _filename_from_url(url)
        if not fn or fn in ("null", "-"):
            continue
        if fn in seen_fn:
            continue
        seen_fn.add(fn)
        deduped.append((ticker, date_str, url))

    # Skip filings whose XBRL already on disk (resumable).
    pending = []
    cached = 0
    for ticker, date_str, url in deduped:
        out = XBRL_DIR / _filename_from_url(url)
        if _is_valid_xml(out):
            cached += 1
            continue
        pending.append((ticker, date_str, url))
    log(f"Filing entries: total={len(filings)}  unique_urls={len(deduped)}  "
        f"on_disk={cached}  pending={len(pending)}")

    sessions = [_make_session() for _ in range(args.workers)]
    results = []
    t0 = time.time()
    n_total = len(pending)
    n_ok_window = 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {}
        for i, (ticker, date_str, url) in enumerate(pending):
            s = sessions[i % args.workers]
            fut = ex.submit(_fetch_one, s, ticker, date_str, url)
            futures[fut] = (ticker, date_str)
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            results.append(r)
            if r["status"] == "ok":
                n_ok_window += 1
                time.sleep(args.sleep)
            if i % 100 == 0 or i == n_total:
                ok = sum(1 for x in results if x["status"] == "ok")
                fa = sum(1 for x in results if x["status"] not in ("ok", "cached"))
                rate = i / (time.time() - t0) if time.time() > t0 else 0
                eta_min = (n_total - i) / rate / 60 if rate > 0 else 0
                # Sample failure modes for diagnosis
                from collections import Counter
                fc = Counter(x["status"] for x in results[-100:] if x["status"] not in ("ok", "cached"))
                fc_str = ", ".join(f"{k}={v}" for k, v in fc.most_common(3)) if fc else ""
                log(f"  [{i:5d}/{n_total}] ok={ok} fail={fa}  {rate:.1f} req/s  ETA={eta_min:.0f}m  recent_fails: {fc_str}")
            # Periodically re-warm sessions to avoid cookie expiry stalls
            if n_ok_window >= args.refresh_every:
                log(f"  re-warming {args.workers} sessions after {n_ok_window} successful fetches")
                sessions = [_make_session() for _ in range(args.workers)]
                n_ok_window = 0

    elapsed = time.time() - t0
    SUMMARY_PATH.write_text(json.dumps({
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_filings": len(filings),
        "n_pending_at_start": len(pending),
        "n_ok": sum(1 for r in results if r["status"] == "ok"),
        "n_cached": sum(1 for r in results if r["status"] == "cached"),
        "n_failed": sum(1 for r in results if r["status"] not in ("ok", "cached")),
        "elapsed_seconds": round(elapsed, 1),
        "failures": [r for r in results if r["status"] not in ("ok", "cached")][:500],
    }, indent=2))
    log(f"→ {SUMMARY_PATH}  elapsed={elapsed:.0f}s")


if __name__ == "__main__":
    main()
