"""Download `sec_bhavdata_full_DDMMYYYY.csv` per trading day from NSE.

Resumable (skip if cached). Iterates weekdays in a date range and 404s
indicate non-trading days (holidays) — recorded in summary, not retried.

Run:
    python -m nse_eod.code.fetch_bhavcopy --start 2020-01-01 --end today
    python -m nse_eod.code.fetch_bhavcopy --start 2025-01-01 --end 2025-01-31  # smoke
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BHAVCOPY_DIR = ROOT / "data" / "bhavcopy"
BHAVCOPY_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_PATH = ROOT / "data" / "fetch_bhavcopy_summary.json"

PROJECT_ROOT = ROOT.parent
URL_TMPL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
LEGACY_URL_TMPL = (
    "https://nsearchives.nseindia.com/content/historical/EQUITIES/"
    "{yyyy}/{MMM}/cm{dd}{MMM}{yyyy}bhav.csv.gz"
)


def _make_session() -> requests.Session:
    sys.path.insert(0, str(PROJECT_ROOT))
    from fno_history.code.fetch_circulars import make_session  # noqa: E402
    return make_session()


def _daterange(start: date, end: date):
    cur = start
    one_day = timedelta(days=1)
    while cur <= end:
        # NSE trades Mon-Fri only.
        if cur.weekday() < 5:
            yield cur
        cur += one_day


def _path_for(d: date) -> Path:
    return BHAVCOPY_DIR / f"sec_bhavdata_full_{d.strftime('%d%m%Y')}.csv"


def _is_holiday_marker(p: Path) -> bool:
    return p.exists() and p.stat().st_size == 0


def _fetch_one(s: requests.Session, d: date) -> dict:
    out = _path_for(d)
    if out.exists() and out.stat().st_size > 5000:
        return {"date": d.isoformat(), "status": "cached", "size": out.stat().st_size}
    if _is_holiday_marker(out):
        return {"date": d.isoformat(), "status": "holiday_cached"}

    url = URL_TMPL.format(ddmmyyyy=d.strftime("%d%m%Y"))
    try:
        r = s.get(url, timeout=30, headers={"Referer": "https://www.nseindia.com/"})
    except requests.RequestException as e:
        return {"date": d.isoformat(), "status": f"err_{type(e).__name__}", "error": str(e)[:80]}

    if r.status_code == 200 and len(r.content) > 5000 and r.text.startswith("SYMBOL"):
        out.write_bytes(r.content)
        return {"date": d.isoformat(), "status": "ok", "size": len(r.content)}
    if r.status_code == 404:
        # Mark as known holiday to skip on resume.
        out.write_text("")
        return {"date": d.isoformat(), "status": "holiday"}
    return {"date": d.isoformat(), "status": f"http_{r.status_code}",
            "error": r.text[:80]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="today")
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--refresh-every", type=int, default=200)
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    if args.end == "today":
        end = date.today()
    else:
        end = datetime.strptime(args.end, "%Y-%m-%d").date()

    days = list(_daterange(start, end))
    print(f"Fetching {len(days)} weekdays from {start} to {end} …", flush=True)

    s = _make_session()
    results = []
    n_ok_window = 0
    t0 = time.time()
    for i, d in enumerate(days, 1):
        r = _fetch_one(s, d)
        results.append(r)
        marker = {
            "ok": "✓", "cached": "·", "holiday": " ", "holiday_cached": " ",
        }.get(r["status"], "✗")
        if r["status"] == "ok":
            n_ok_window += 1
        if i % 50 == 0 or i == len(days):
            ok = sum(1 for x in results if x["status"] == "ok")
            ca = sum(1 for x in results if x["status"] == "cached")
            ho = sum(1 for x in results if x["status"] in ("holiday", "holiday_cached"))
            fa = sum(1 for x in results if x["status"] not in ("ok", "cached", "holiday", "holiday_cached"))
            rate = i / (time.time() - t0) if time.time() > t0 else 0
            print(f"  [{i:5d}/{len(days)}]  ok={ok} cached={ca} holiday={ho} fail={fa}  "
                  f"{rate:.1f} req/s", flush=True)
        if r["status"] == "ok":
            time.sleep(args.sleep)
        if n_ok_window >= args.refresh_every:
            s = _make_session()
            n_ok_window = 0

    elapsed = time.time() - t0
    SUMMARY_PATH.write_text(json.dumps({
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "start": str(start),
        "end": str(end),
        "n_days": len(days),
        "n_ok": sum(1 for r in results if r["status"] == "ok"),
        "n_cached": sum(1 for r in results if r["status"] == "cached"),
        "n_holiday": sum(1 for r in results if r["status"] in ("holiday", "holiday_cached")),
        "n_failed": sum(1 for r in results if r["status"] not in ("ok", "cached", "holiday", "holiday_cached")),
        "elapsed_seconds": round(elapsed, 1),
        "failures": [r for r in results if r["status"] not in ("ok", "cached", "holiday", "holiday_cached")][:200],
    }, indent=2))
    print(f"\n→ {SUMMARY_PATH}  elapsed={elapsed:.0f}s")


if __name__ == "__main__":
    main()
