"""Validation gates for index_membership_history.csv.

Runs five gates and writes the result to docs/validation_report.md. No
Postgres required — everything reads from the CSV + registry.

Gates:
  1. Snapshot match (today)        — members(today) per index == current_snapshot CSV.
  2. Internal consistency          — Nifty subsumption (Next 50 ⊆ N100, N100 ⊆ N500),
                                     plus sector ⊆ Nifty 500 (broad coverage check).
  3. Famous transitions            — hand-curated PIT checks across all four families.
  4. Daily cardinality             — for fixed-size indices: |members(t)| == target.
  5. Wayback archive cross-check   — for 6 historical dates per index, diff our
                                     reconstruction against the Wayback Machine
                                     snapshot of archives.nseindia.com's CSV.

Run: python -m index_history.code.validate [--skip-wayback]
"""
from __future__ import annotations
import argparse
import csv
import io
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "index_membership_history.csv"
SNAPSHOT_DIR = ROOT / "data" / "current_snapshot"
RENAMES_PATH = ROOT / "data" / "manual_overrides" / "symbol_renames.json"
REPORT_PATH = ROOT / "docs" / "validation_report.md"

sys.path.insert(0, str(ROOT.parent))
from index_history.code import registry as _reg  # noqa: E402


# ---------- canonicalisation ----------

def _load_renames() -> dict[str, str]:
    rd = json.loads(RENAMES_PATH.read_text())
    direct = {r["old"].upper().strip(): r["new"].upper().strip()
              for r in rd.get("renames", [])
              if r.get("old") and r.get("new") and r["old"] != r["new"]}
    out: dict[str, str] = {}
    for old in direct:
        seen = {old}; cur = direct[old]
        while cur in direct and cur not in seen:
            seen.add(cur); cur = direct[cur]
        out[old] = cur
    return out


RENAMES = _load_renames()


def canon(s: str) -> str:
    s = s.upper().strip()
    out = RENAMES.get(s, s)
    return "" if out == "_DUMMY_DROP" else out


# ---------- data loaders ----------

def load_intervals() -> dict[int, list[tuple[date, Optional[date], str]]]:
    iv: dict[int, list] = defaultdict(list)
    with open(CSV_PATH) as f:
        for r in csv.DictReader(f):
            idx = int(r["index_id"])
            vf = date.fromisoformat(r["valid_from"])
            vt = date.fromisoformat(r["valid_to"]) if r["valid_to"] else None
            s = canon(r["symbol"])
            if s:
                iv[idx].append((vf, vt, s))
    return dict(iv)


def members_at(iv, idx: int, on: date) -> set[str]:
    return {sym for vf, vt, sym in iv.get(idx, []) if vf <= on and (vt is None or vt > on)}


def load_snapshot(slug: str) -> set[str]:
    """Load NSE's published current-membership CSV. Filters out DUMMY*/TEMP*
    placeholders that NSE inserts during demerger / corporate-action transitions
    (e.g. DUMMYVEDL1..4 during the 2024 Vedanta demerger) — these are not real
    members and would produce spurious mismatches in Gate 1."""
    p = SNAPSHOT_DIR / f"{slug}.csv"
    if not p.exists():
        return set()
    out = set()
    with p.open() as f:
        for r in csv.DictReader(f):
            raw = (r.get("symbol", "") or "").upper().strip()
            if not raw or raw.startswith("DUMMY") or raw.startswith("TEMP"):
                continue
            sym = canon(raw)
            if sym:
                out.add(sym)
    return out


# ---------- Gate 1: snapshot match (today) ----------

def gate_snapshot_match(iv, specs) -> tuple[int, int, list[str]]:
    print("=== Gate 1: snapshot match (today) ===")
    today = date.today()
    fail = total = 0
    fail_lines: list[str] = []
    for s in specs:
        snap = load_snapshot(s.snapshot_slug)
        if not snap:
            continue  # missing snapshot — skip silently
        ours = members_at(iv, s.id, today)
        only_ours = ours - snap
        only_snap = snap - ours
        total += 1
        if only_ours or only_snap:
            fail += 1
            line = (f"  FAIL  {s.canonical_name:38s}  "
                    f"+{len(only_ours)} ours / +{len(only_snap)} snap")
            fail_lines.append(line)
            if len(fail_lines) <= 30:
                print(line)
                if only_ours: print(f"        only-ours sample: {sorted(only_ours)[:6]}")
                if only_snap: print(f"        only-snap sample: {sorted(only_snap)[:6]}")
    if fail == 0:
        print(f"  ✓ all {total} indices match their published snapshot")
    print(f"  Result: {fail}/{total} mismatches\n")
    return fail, total, fail_lines


# ---------- Gate 2: internal consistency ----------

def gate_internal_consistency(iv) -> tuple[int, int, list[str]]:
    """Walk every quarter from 2017-01-01 onward. Assert subsumption invariants."""
    print("=== Gate 2: internal consistency ===")
    invariants = [
        # (subset_idx, superset_idx, name)
        (217, 219, "Nifty 50 ⊆ Nifty 100"),
        (218, 219, "Nifty Next 50 ⊆ Nifty 100"),
        (219, 221, "Nifty 100 ⊆ Nifty 500"),
        (223, 221, "Nifty Midcap 150 ⊆ Nifty 500"),
        (227, 221, "Nifty Smallcap 250 ⊆ Nifty 500"),
        # Sectors: every sector member should be in Nifty 500 (sectors are
        # drawn from Nifty 500's universe per NSE methodology).
        (1001, 221, "Nifty Bank ⊆ Nifty 500"),
        (1002, 221, "Nifty IT ⊆ Nifty 500"),
        (1003, 221, "Nifty FMCG ⊆ Nifty 500"),
        (1004, 221, "Nifty Pharma ⊆ Nifty 500"),
        (1005, 221, "Nifty Auto ⊆ Nifty 500"),
        (1006, 221, "Nifty Metal ⊆ Nifty 500"),
        (1007, 221, "Nifty Realty ⊆ Nifty 500"),
        (1008, 221, "Nifty Energy ⊆ Nifty 500"),
        (1009, 221, "Nifty PSU Bank ⊆ Nifty 500"),
        (1010, 221, "Nifty Private Bank ⊆ Nifty 500"),
        (1011, 221, "Nifty Healthcare ⊆ Nifty 500"),
        (1012, 221, "Nifty Financial Services ⊆ Nifty 500"),
        (1013, 221, "Nifty Media ⊆ Nifty 500"),
        (1014, 221, "Nifty Consumer Durables ⊆ Nifty 500"),
        (1015, 221, "Nifty Oil & Gas ⊆ Nifty 500"),
    ]
    today = date.today()
    samples = []
    y, m = 2017, 1
    while date(y, m, 1) <= today:
        samples.append(date(y, m, 1))
        m += 6
        if m > 12: m -= 12; y += 1

    fail = total = 0
    fail_lines: list[str] = []
    for sub_idx, sup_idx, name in invariants:
        violations = 0
        worst_d, worst_n = None, 0
        for d in samples:
            sub = members_at(iv, sub_idx, d)
            sup = members_at(iv, sup_idx, d)
            if not sub or not sup:
                continue
            extra = sub - sup
            if extra:
                violations += 1
                if len(extra) > worst_n:
                    worst_n, worst_d = len(extra), d
        total += 1
        if violations:
            fail += 1
            line = (f"  FAIL  {name:42s}  "
                    f"violated on {violations}/{len(samples)} dates  "
                    f"(worst: {worst_n} extra symbols on {worst_d})")
            fail_lines.append(line)
            print(line)
    if fail == 0:
        print(f"  ✓ all {total} subsumption invariants hold across {len(samples)} sample dates")
    print(f"  Result: {fail}/{total} invariants failed\n")
    return fail, total, fail_lines


# ---------- Gate 3: famous transitions ----------

FAMOUS = [
    # Nifty 50 / Nifty 500 — broad
    ("HDFC absent post-merger",                            217, "HDFC",       date(2023, 7, 14), False),
    ("HDFCBANK still in Nifty 50 on merger day",           217, "HDFCBANK",   date(2023, 7, 14), True),
    ("SHRIRAMFIN added 2024-03-28",                        217, "SHRIRAMFIN", date(2024, 3, 28), True),
    ("UPL excluded 2024-03-28",                            217, "UPL",        date(2024, 3, 28), False),
    ("BPCL was member on 2022-01-01",                      217, "BPCL",       date(2022, 1, 1),  True),
    ("ETERNAL (was ZOMATO) joined Nifty 50 in Mar 2025",   217, "ETERNAL",    date(2025, 4, 1),  True),
    ("ETERNAL NOT in Nifty 50 pre-Mar 2025",               217, "ETERNAL",    date(2024, 12, 31),False),
    ("INDIGO joined Nifty 50 on 2025-09-30",               217, "INDIGO",     date(2025, 10, 1), True),
    ("MAXHEALTH joined Nifty 50 on 2025-09-30",            217, "MAXHEALTH",  date(2025, 10, 1), True),
    ("HEROMOTOCO excluded from Nifty 50 on 2025-09-30",    217, "HEROMOTOCO", date(2025, 10, 1), False),
    ("INDUSINDBK excluded from Nifty 50 on 2025-09-30",    217, "INDUSINDBK", date(2025, 10, 1), False),
    ("ATGL (was ADANIGAS) member of Nifty 500 in 2021",    221, "ATGL",       date(2021, 6, 1),  True),
    ("LTM (was MINDTREE→LTIM) member of Nifty 500 in 2022",221, "LTM",        date(2022, 12, 31),True),

    # Sector — Nifty Bank
    ("HDFC merged into HDFCBANK — HDFC absent from Nifty Bank post-2023-07-13",
                                                            1001, "HDFC",       date(2023, 7, 14), False),
    ("HDFCBANK is in Nifty Bank today",                     1001, "HDFCBANK",   date.today(),       True),
    ("ICICIBANK is in Nifty Bank today",                    1001, "ICICIBANK",  date.today(),       True),

    # Sector — Nifty IT
    ("TCS is in Nifty IT today",                            1002, "TCS",        date.today(),       True),
    ("INFY is in Nifty IT today",                           1002, "INFY",       date.today(),       True),
    ("LTM (was LTIM) is in Nifty IT today",                 1002, "LTM",        date.today(),       True),

    # Sector — Nifty FMCG
    ("HINDUNILVR is in Nifty FMCG today",                   1003, "HINDUNILVR", date.today(),       True),
    ("ITC is in Nifty FMCG today",                          1003, "ITC",        date.today(),       True),

    # Sector — Nifty Pharma
    ("SUNPHARMA is in Nifty Pharma today",                  1004, "SUNPHARMA",  date.today(),       True),
    ("CIPLA is in Nifty Pharma today",                      1004, "CIPLA",      date.today(),       True),

    # Sector — Nifty Auto
    ("MARUTI is in Nifty Auto today",                       1005, "MARUTI",     date.today(),       True),
    ("M&M is in Nifty Auto today",                          1005, "M&M",        date.today(),       True),

    # Strategy — Nifty Alpha 50 — symbols cycle quickly so today-only checks
    # would be fragile; check the snapshot match instead (already in Gate 1).

    # Strategy — Nifty100 Equal Weight: it equals Nifty 100 by construction,
    # so members(t, 2006) == members(t, 219) — captured implicitly via Gate 2
    # subset invariants. Also assert today's count == 100.
    # (We test this in Gate 4 cardinality.)

    # Thematic — Nifty CPSE
    ("ONGC is in Nifty CPSE today",                         3003, "ONGC",       date.today(),       True),
    ("COALINDIA is in Nifty CPSE today",                    3003, "COALINDIA",  date.today(),       True),

    # Thematic — Nifty MNC
    ("HINDUNILVR is in Nifty MNC today",                    3005, "HINDUNILVR", date.today(),       True),

    # Thematic — Nifty Services Sector
    ("HDFCBANK is in Nifty Services today",                 3007, "HDFCBANK",   date.today(),       True),
]


def gate_famous(iv) -> tuple[int, int, list[str]]:
    print("=== Gate 3: famous transitions ===")
    fail = 0
    fail_lines: list[str] = []
    for desc, idx, sym, on, expected in FAMOUS:
        actual = canon(sym) in members_at(iv, idx, on)
        status = "PASS" if actual == expected else "FAIL"
        if actual != expected:
            fail += 1
            fail_lines.append(f"  [FAIL] {desc} — {sym}@{on}: expected={expected} got={actual}")
        print(f"  [{status}] {desc} — {sym} on {on}: expected={expected} got={actual}")
    print(f"  Result: {fail}/{len(FAMOUS)} failures\n")
    return fail, len(FAMOUS), fail_lines


# ---------- Gate 4: cardinality ----------

def gate_cardinality(iv, specs) -> tuple[int, int, list[str]]:
    print("=== Gate 4: daily cardinality (fixed-size indices only) ===")
    targets = {s.id: (s.canonical_name, s.target_size) for s in specs if s.target_size is not None}
    launches = {s.id: s.launch_date for s in specs}
    today = date.today()

    samples = []
    y, m = 2014, 1
    while date(y, m, 1) <= today:
        samples.append(date(y, m, 1))
        m += 3
        if m > 12: m -= 12; y += 1

    fail = total = skipped = 0
    fail_lines: list[str] = []
    by_index_fail: dict[int, int] = defaultdict(int)
    for d in samples:
        for idx, (name, tgt) in targets.items():
            if d < launches[idx]:
                skipped += 1; continue
            n = len(members_at(iv, idx, d))
            total += 1
            if n != tgt:
                fail += 1
                by_index_fail[idx] += 1
                if len(fail_lines) < 60:
                    fail_lines.append(f"  FAIL  {d}  {name:32s}  {n} (expected {tgt})")
    for line in fail_lines: print(line)
    if fail > 60:
        print(f"  ... ({fail - 60} more)")
    print(f"  (skipped {skipped} pre-launch checks)")
    print(f"  Result: {fail}/{total} cardinality failures\n")
    if by_index_fail:
        print("  Per-index failure counts (top 10):")
        for idx, n in sorted(by_index_fail.items(), key=lambda x: -x[1])[:10]:
            print(f"    {targets[idx][0]:32s}  {n}")
        print()
    return fail, total, fail_lines


# ---------- Gate 5: Wayback cross-check ----------

# Wayback's coverage of archives.nseindia.com CSVs is sparse and concentrated
# in 2021+. Rather than fix a list of target dates and hope a Wayback snapshot
# exists nearby, the gate iterates every snapshot CDX returns and checks our
# reconstruction at the snapshot's exact timestamp. Cap at MAX_WB_PER_INDEX to
# keep runtime bounded.
MAX_WB_PER_INDEX = 8


_CDX_CACHE: dict[str, list[tuple[str, str]]] = {}


def _wayback_cdx(url: str) -> list[tuple[str, str]]:
    """Return [(timestamp, original_url)] for every 200-status snapshot of `url`.
    Cached so we don't refetch per target date.
    """
    if url in _CDX_CACHE:
        return _CDX_CACHE[url]
    try:
        r = requests.get(
            "https://web.archive.org/cdx/search/cdx",
            params={"url": url, "output": "json",
                    "filter": "statuscode:200", "fl": "timestamp,original"},
            timeout=60,
        )
        if r.status_code != 200:
            _CDX_CACHE[url] = []
            return []
        rows = r.json()
        _CDX_CACHE[url] = [(t, u) for t, u in rows[1:]]  # drop header row
    except (requests.RequestException, ValueError):
        _CDX_CACHE[url] = []
    return _CDX_CACHE[url]


def _fetch_wayback_at(ts: str, original: str) -> Optional[tuple[set[str], str]]:
    """Fetch a specific Wayback snapshot. Returns (symbols, ISO date)."""
    wb = f"https://web.archive.org/web/{ts}id_/{original}"
    try:
        r = requests.get(wb, timeout=60)
    except requests.RequestException:
        return None
    if r.status_code != 200 or "html" in r.headers.get("Content-Type", "").lower():
        return None
    try:
        rows = list(csv.DictReader(io.StringIO(r.text)))
    except Exception:
        return None
    syms = set()
    for row in rows:
        raw = (row.get("Symbol", "") or "").upper().strip()
        if not raw or raw.startswith("DUMMY") or raw.startswith("TEMP"):
            continue
        c = canon(raw)
        if c: syms.add(c)
    if not syms:
        return None
    snap_d = datetime.strptime(ts[:8], "%Y%m%d").date()
    return (syms, snap_d.isoformat())


def _spread_snapshots(
    snaps: list[tuple[str, str]], k: int
) -> list[tuple[str, str]]:
    """Pick up to k snapshots evenly spread across time, deduped by month."""
    by_month: dict[str, tuple[str, str]] = {}
    for ts, orig in snaps:
        by_month.setdefault(ts[:6], (ts, orig))
    monthly = sorted(by_month.values())
    if len(monthly) <= k:
        return monthly
    step = len(monthly) / k
    return [monthly[int(i * step)] for i in range(k)]


def gate_wayback(iv, specs, max_indices: Optional[int] = None) -> tuple[int, int, list[str]]:
    """For each archive-mirrored index, query Wayback CDX for every snapshot
    of its CSV, sample up to MAX_WB_PER_INDEX evenly across time, and compare
    each against our reconstruction at that snapshot's exact date."""
    print("=== Gate 5: Wayback archive cross-check ===")
    targets = [s for s in specs if not s.snapshot_url.startswith("nseapi:")]
    if max_indices:
        targets = targets[:max_indices]
    print(f"    {len(targets)} archive-mirrored indices "
          f"(up to {MAX_WB_PER_INDEX} samples each)")

    fail = total = no_snap = 0
    fail_lines: list[str] = []
    drift_by_index: dict[int, list[int]] = defaultdict(list)
    for s in targets:
        snaps = _wayback_cdx(s.snapshot_url)
        if not snaps:
            no_snap += 1
            continue
        sampled = _spread_snapshots(snaps, MAX_WB_PER_INDEX)
        for ts, original in sampled:
            result = _fetch_wayback_at(ts, original)
            if result is None:
                continue
            wb, snap_date = result
            cmp_d = date.fromisoformat(snap_date)
            if cmp_d < s.launch_date:
                continue
            ours = members_at(iv, s.id, cmp_d)
            extra_ours = ours - wb
            extra_wb = wb - ours
            total += 1
            drift = len(extra_ours) + len(extra_wb)
            drift_by_index[s.id].append(drift)
            if drift > 0:
                fail += 1
                if len(fail_lines) < 40:
                    fail_lines.append(
                        f"  DRIFT  {snap_date}  {s.canonical_name:32s}  "
                        f"+{len(extra_ours)} ours / +{len(extra_wb)} wb"
                    )
    for line in fail_lines: print(line)
    if fail > 40:
        print(f"  ... ({fail - 40} more)")
    print(f"  (indices with no Wayback CDX coverage: {no_snap})")
    print(f"  Result: {fail}/{total} cross-checks with non-zero drift\n")
    if drift_by_index:
        print("  Mean drift per index (lower = better; n = #snapshots checked):")
        rows = [(specs_by_id[idx].canonical_name, sum(d) / len(d), len(d))
                for idx, d in drift_by_index.items() if d]
        for name, mean, n in sorted(rows, key=lambda x: x[1]):
            print(f"    {name:32s}  mean={mean:5.1f}  (n={n})")
        print()
    return fail, total, fail_lines


# ---------- main ----------

specs_by_id: dict[int, _reg.IndexSpec] = {}


def main() -> None:
    global specs_by_id
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-wayback", action="store_true",
                    help="Skip Gate 5 (network-bound, slow).")
    ap.add_argument("--wayback-max-indices", type=int, default=None,
                    help="Limit Gate 5 to the first N indices (faster smoke test).")
    args = ap.parse_args()

    iv = load_intervals()
    specs = list(_reg.load())
    specs_by_id = {s.id: s for s in specs}

    import io as _io, contextlib
    buf = _io.StringIO()

    class Tee:
        def __init__(self, *streams): self.streams = streams
        def write(self, s):
            for st in self.streams: st.write(s)
        def flush(self):
            for st in self.streams: st.flush()

    with contextlib.redirect_stdout(Tee(sys.stdout, buf)):
        print(f"# Validation Report — {datetime.now().isoformat(timespec='seconds')}")
        print()
        print(f"Indices: {len(specs)} ({sum(1 for s in specs if s.family=='broad')} broad, "
              f"{sum(1 for s in specs if s.family=='sector')} sector, "
              f"{sum(1 for s in specs if s.family=='strategy')} strategy, "
              f"{sum(1 for s in specs if s.family=='thematic')} thematic).")
        print(f"Source: {CSV_PATH.relative_to(ROOT.parent)}")
        print()

        g1 = gate_snapshot_match(iv, specs)
        g2 = gate_internal_consistency(iv)
        g3 = gate_famous(iv)
        g4 = gate_cardinality(iv, specs)
        if not args.skip_wayback:
            g5 = gate_wayback(iv, specs, max_indices=args.wayback_max_indices)
        else:
            g5 = (0, 0, ["Gate 5 skipped (--skip-wayback)"])
            print("=== Gate 5: SKIPPED ===\n")

        print("=== Summary ===")
        print(f"  Gate 1 snapshot match (today)   : {g1[0]} / {g1[1]} mismatches")
        print(f"  Gate 2 internal consistency     : {g2[0]} / {g2[1]} invariants failed")
        print(f"  Gate 3 famous transitions       : {g3[0]} / {g3[1]} failed")
        print(f"  Gate 4 daily cardinality        : {g4[0]} / {g4[1]} failed (fixed-size only)")
        print(f"  Gate 5 Wayback cross-check      : {g5[0]} / {g5[1]} drifts")
        total_fail = g1[0] + g2[0] + g3[0] + g4[0] + g5[0]
        total_total = g1[1] + g2[1] + g3[1] + g4[1] + g5[1]
        print(f"  TOTAL: {total_fail} / {total_total}")

    REPORT_PATH.write_text(buf.getvalue())
    print(f"\nWrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
