"""Fetch NSE shareholding-pattern filing index per ticker.

For each NSE symbol in the input ticker list, calls the
`/api/corporate-share-holdings-master` endpoint and caches the returned list
of filings (each carrying date + XBRL URL + recordId) under
`data/filings_index/<TICKER>.json`.

Resumable: skips tickers whose cache file is < 7 days old. Re-fetched lists are
merged into the cached one, never replace it (NSE now returns only ~23 recent filings).

Run:
    python -m shareholding_history.code.fetch_filings --since 01-05-2026   # refresh: 2 calls
    python -m shareholding_history.code.fetch_filings --all                # full history, per symbol
    python -m shareholding_history.code.fetch_filings --tickers RELIANCE,KAYNES
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "data" / "filings_index"
INDEX_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_PATH = ROOT / "data" / "filings_index_summary.json"
UNIVERSE_CACHE = ROOT / "data" / "_universe.csv"

PROJECT_ROOT = ROOT.parent

# Full NSE universe — main board + SME Emerge (~2,800 symbols total).
EQUITY_L_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
SME_L_URL = "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"

API_URL = "https://www.nseindia.com/api/corporate-share-holdings-master"
REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern"


def _make_session() -> requests.Session:
    """Reuse the warming pattern from fno_history."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from fno_history.code.fetch_circulars import make_session  # noqa: E402
    return make_session()


def _read_universe_cache() -> list[tuple[str, str]]:
    """Load the committed/self-contained universe from data/_universe.csv."""
    out: list[tuple[str, str]] = []
    with UNIVERSE_CACHE.open() as f:
        for row in csv.DictReader(f):
            out.append((row["symbol"], row["segment"]))
    return out


def _load_full_universe(s: requests.Session, force_refresh: bool = False) -> list[tuple[str, str]]:
    """Returns list of (symbol, segment) for every NSE-listed equity + SME.

    Caches to data/_universe.csv. Fresh fetch if cache > 7 days old or --force.
    A committed _universe.csv ships with the repo, so this works offline:
    if the live fetch yields nothing, we fall back to the cached file
    regardless of its age.
    """
    if UNIVERSE_CACHE.exists() and not force_refresh:
        age_days = (time.time() - UNIVERSE_CACHE.stat().st_mtime) / 86400
        if age_days < 7:
            return _read_universe_cache()

    out: list[tuple[str, str]] = []
    for url, segment in [(EQUITY_L_URL, "EQ"), (SME_L_URL, "SME")]:
        r = s.get(url, timeout=30, headers={"Referer": "https://www.nseindia.com/"})
        if r.status_code != 200:
            print(f"  warn: {segment} list fetch returned {r.status_code}")
            continue
        reader = csv.reader(io.StringIO(r.text))
        next(reader, None)  # header
        for row in reader:
            if not row:
                continue
            sym = row[0].strip().upper()
            if sym:
                out.append((sym, segment))
        print(f"  loaded {segment} segment: {sum(1 for _,s2 in out if s2==segment)} symbols")

    # Offline fallback: live fetch yielded nothing → use the committed cache.
    if not out and UNIVERSE_CACHE.exists():
        print("  live universe fetch empty; falling back to committed _universe.csv")
        return _read_universe_cache()

    # Dedup (a symbol could in theory appear in both, prefer EQ).
    seen = {}
    for sym, seg in out:
        if sym not in seen or seg == "EQ":
            seen[sym] = seg
    rows = sorted(seen.items())

    UNIVERSE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with UNIVERSE_CACHE.open("w") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "segment"])
        w.writerows(rows)
    return rows


def _is_fresh(p: Path, max_age_days: float = 7) -> bool:
    if not p.exists():
        return False
    age_days = (time.time() - p.stat().st_mtime) / 86400
    return age_days < max_age_days


def merge_filings(old: list[dict], new: list[dict]) -> list[dict]:
    """Fresh list first, then every cached filing the API no longer returns.
    NSE's master endpoint started returning only ~23 recent filings (2026-11);
    the committed index holds the full history and must never shrink."""
    seen = {f["xbrl"] for f in new}
    return new + [f for f in old if f.get("xbrl") not in seen]


def fetch_one(s: requests.Session, ticker: str, force: bool = False) -> dict:
    """Fetch the master-list of filings for a single ticker."""
    out_file = INDEX_DIR / f"{ticker}.json"
    if not force and _is_fresh(out_file):
        try:
            cached = json.loads(out_file.read_text())
            return {"ticker": ticker, "status": "cached", "n_filings": len(cached.get("filings", []))}
        except Exception:
            pass  # corrupt cache → re-fetch

    try:
        r = s.get(
            API_URL,
            params={"index": "equities", "symbol": ticker},
            headers={"Referer": REFERER, "Accept": "*/*", "X-Requested-With": "XMLHttpRequest"},
            timeout=30,
        )
    except requests.RequestException as e:
        return {"ticker": ticker, "status": f"err_{type(e).__name__}", "error": str(e)[:100]}

    if r.status_code != 200:
        return {"ticker": ticker, "status": r.status_code, "error": r.text[:120]}

    try:
        body = r.json()
    except json.JSONDecodeError:
        return {"ticker": ticker, "status": "non_json", "error": r.text[:120]}

    if not isinstance(body, list):
        return {"ticker": ticker, "status": "unexpected_shape", "error": str(type(body))}

    n = _write_merged(ticker, [_compact(row) for row in body if row.get("xbrl")])
    return {"ticker": ticker, "status": "ok", "n_filings": n}


def _compact(row: dict) -> dict:
    """Keep just the fields we need to make the cache compact."""
    return {
        "date": row.get("date"),                  # e.g. "31-MAR-2026"
        "submission_date": row.get("submissionDate"),
        "broadcast_date": row.get("broadcastDate"),
        "xbrl": row["xbrl"],
        "record_id": row.get("recordId"),
        "revised": row.get("revisedData"),        # "Y" / "N"
        "format": row.get("format"),
    }


def _write_merged(ticker: str, filings: list[dict]) -> int:
    """Merge `filings` into data/filings_index/<ticker>.json (never shrinks it)."""
    out_file = INDEX_DIR / f"{ticker}.json"
    if out_file.exists():
        try:
            filings = merge_filings(json.loads(out_file.read_text()).get("filings", []), filings)
        except json.JSONDecodeError:
            pass  # corrupt cache → keep only the fresh list
    out_file.write_text(json.dumps({
        "ticker": ticker,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_filings": len(filings),
        "filings": filings,
    }, indent=2))
    return len(filings)


def fetch_since(s: requests.Session, since: str, until: str) -> dict:
    """Every filing submitted in [since, until] (DD-MM-YYYY), main board + SME, in one
    call per segment — instead of one call per symbol. Merges into each symbol's index
    file; symbols listed after _universe.csv was built get a new file."""
    by_ticker: dict[str, list[dict]] = {}
    for segment in ("equities", "sme"):
        r = s.get(
            API_URL,
            params={"index": segment, "from_date": since, "to_date": until},
            headers={"Referer": REFERER, "Accept": "*/*", "X-Requested-With": "XMLHttpRequest"},
            timeout=120,
        )
        r.raise_for_status()
        body = r.json()
        if not isinstance(body, list):
            raise RuntimeError(f"{segment}: unexpected response shape {type(body)}")
        print(f"  {segment}: {len(body)} filings submitted {since} → {until}")
        for row in body:
            if row.get("xbrl") and row.get("symbol"):
                by_ticker.setdefault(row["symbol"], []).append(_compact(row))
    new_symbols = [t for t in by_ticker if not (INDEX_DIR / f"{t}.json").exists()]
    for t, filings in by_ticker.items():
        _write_merged(t, filings)
    return {"symbols": len(by_ticker), "filings": sum(map(len, by_ticker.values())),
            "new_symbols": sorted(new_symbols)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="Full NSE universe = main board + SME Emerge (~2,800)")
    ap.add_argument("--tickers", help="Comma-separated tickers (overrides --all)")
    ap.add_argument("--force", action="store_true", help="Re-fetch even if cached")
    ap.add_argument("--refresh-universe", action="store_true",
                    help="Re-fetch the EQUITY_L + SME_EQUITY_L master CSVs")
    ap.add_argument("--sleep", type=float, default=0.4, help="Seconds between calls (politeness)")
    ap.add_argument("--since", help="DD-MM-YYYY: fetch every filing submitted since this date in "
                                    "2 calls (main board + SME) — the quarterly-refresh path")
    ap.add_argument("--until", default=datetime.now().strftime("%d-%m-%Y"),
                    help="DD-MM-YYYY end of the --since window (default: today)")
    args = ap.parse_args()

    s = _make_session()
    if args.since:
        res = fetch_since(s, args.since, args.until)
        print(f"\n{res['filings']} filings across {res['symbols']} symbols merged into {INDEX_DIR}")
        if res["new_symbols"]:
            print(f"  new symbols (not in an earlier index): {', '.join(res['new_symbols'])}")
        return
    if args.tickers:
        targets = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif args.all:
        universe = _load_full_universe(s, force_refresh=args.refresh_universe)
        targets = [sym for sym, _ in universe]
    else:
        print("Specify --all (full NSE universe) | --tickers SYM1,SYM2 …")
        sys.exit(1)

    print(f"Fetching filing index for {len(targets)} ticker(s)…")
    results = []
    t0 = time.time()
    for i, t in enumerate(targets, 1):
        r = fetch_one(s, t, force=args.force)
        marker = "·" if r["status"] == "cached" else ("✓" if r["status"] == "ok" else "✗")
        print(f"  [{i:4d}/{len(targets)}] {t:<14} [{marker}] status={r['status']:<10} n={r.get('n_filings','-')}")
        results.append(r)
        if r["status"] not in ("cached",):
            time.sleep(args.sleep)
        # Re-warm session every 250 calls to dodge cookie staleness.
        if i % 250 == 0 and i < len(targets):
            print("  (re-warming session)")
            s = _make_session()

    elapsed = time.time() - t0
    SUMMARY_PATH.write_text(json.dumps({
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_targets": len(targets),
        "n_ok": sum(1 for r in results if r["status"] == "ok"),
        "n_cached": sum(1 for r in results if r["status"] == "cached"),
        "n_failed": sum(1 for r in results if r["status"] not in ("ok", "cached")),
        "elapsed_seconds": round(elapsed, 1),
        "results": results,
    }, indent=2))
    n_ok = sum(1 for r in results if r["status"] == "ok")
    n_cached = sum(1 for r in results if r["status"] == "cached")
    n_failed = sum(1 for r in results if r["status"] not in ("ok", "cached"))
    total_filings = sum(r.get("n_filings", 0) or 0 for r in results)
    print(f"\nok={n_ok}  cached={n_cached}  failed={n_failed}  total_filings={total_filings}  elapsed={elapsed:.0f}s")
    print(f"  → {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
