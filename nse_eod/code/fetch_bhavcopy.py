"""Download a per-trading-day NSE equities file.

Datasets (``--dataset``):
  bhavcopy  `sec_bhavdata_full_DDMMYYYY.csv`  OHLC, volume, turnover, delivery
  bands     `sec_list_DDMMYYYY.csv`           price band (2/5/10/20 % or "No Band"), published
                                              after the close for the NEXT session

Resumable (skip if cached). Iterates weekdays in a date range and 404s
indicate non-trading days (holidays) — recorded in summary, not retried.

Run:
    python -m nse_eod.code.fetch_bhavcopy --start 2020-01-01 --end today
    python -m nse_eod.code.fetch_bhavcopy --dataset bands --start 2020-01-01 --end today
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
BANDS_DIR = ROOT / "data" / "price_bands"

PROJECT_ROOT = ROOT.parent
URL_TMPL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
BANDS_URL_TMPL = "https://nsearchives.nseindia.com/content/equities/sec_list_{ddmmyyyy}.csv"

# name -> (url template, output dir, file prefix, expected first bytes of a valid file)
DATASETS = {
    "bhavcopy": (URL_TMPL, BHAVCOPY_DIR, "sec_bhavdata_full", "SYMBOL"),
    "bands": (BANDS_URL_TMPL, BANDS_DIR, "sec_list", "Symbol"),
}
DATASET = "bhavcopy"  # set by main()
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
    _, out_dir, prefix, _ = DATASETS[DATASET]
    return out_dir / f"{prefix}_{d.strftime('%d%m%Y')}.csv"


def _file_date(text: str) -> date | None:
    """DATE1 of the first data row of a sec_bhavdata_full file."""
    try:
        return datetime.strptime(text.splitlines()[1].split(",")[2].strip(), "%d-%b-%Y").date()
    except (IndexError, ValueError):
        return None


def _is_holiday_marker(p: Path) -> bool:
    return p.exists() and p.stat().st_size == 0


def _fetch_one(s: requests.Session, d: date) -> dict:
    out = _path_for(d)
    if out.exists() and out.stat().st_size > 5000:
        return {"date": d.isoformat(), "status": "cached", "size": out.stat().st_size}
    if _is_holiday_marker(out):
        return {"date": d.isoformat(), "status": "holiday_cached"}

    url_tmpl, _, _, header = DATASETS[DATASET]
    url = url_tmpl.format(ddmmyyyy=d.strftime("%d%m%Y"))
    try:
        r = s.get(url, timeout=30, headers={"Referer": "https://www.nseindia.com/"})
    except requests.RequestException as e:
        return {"date": d.isoformat(), "status": f"err_{type(e).__name__}", "error": str(e)[:80]}

    if r.status_code == 200 and len(r.content) > 5000 and r.text.startswith(header):
        if DATASET == "bhavcopy" and _file_date(r.text) != d:
            # NSE answers some weekday holidays (e.g. 26-Jan-2024) with the previous
            # session's file; saving it would duplicate that session's rows.
            out.write_text("")
            return {"date": d.isoformat(), "status": "holiday"}
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
    ap.add_argument("--dataset", choices=sorted(DATASETS), default="bhavcopy")
    args = ap.parse_args()

    global DATASET
    DATASET = args.dataset
    DATASETS[DATASET][1].mkdir(parents=True, exist_ok=True)
    summary_path = ROOT / "data" / f"fetch_{DATASET}_summary.json"

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
    summary_path.write_text(json.dumps({
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
    print(f"\n→ {summary_path}  elapsed={elapsed:.0f}s")


if __name__ == "__main__":
    main()
