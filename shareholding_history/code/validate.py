"""Cross-check NSE-XBRL parsed values against an external reference dataset.

This is an OPTIONAL validation step. It compares the parsed NSE-XBRL
shareholding values against a third-party reference (e.g. a StockEdge export)
that you supply via --reference. The reference file is NOT part of this repo —
the committed `validation_vs_stockedge.json` is the recorded result of a past
run against a StockEdge 9-quarter export (2024-06 → 2026-03).

For each overlapping (ticker, period) pair, promoter/FII/DII/public should
match within ±0.5 pp. Bigger discrepancies suggest:
  * Parser bug.
  * Revised filing on one side that the other hadn't ingested.
  * Universe-mismatch / taxonomy rollup difference.

The reference CSV must be long-format with columns: ticker, period, category
(promoter|fii|dii|public), pct.

Run:
    python -m shareholding_history.code.validate --reference /path/to/reference_flat.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARSED = ROOT / "data" / "parsed" / "_flat.csv"

OUT_REPORT = ROOT / "data" / "validation_vs_stockedge.json"

TOLERANCE_PP = 0.5  # percentage-point tolerance


def _load_nse(path: Path) -> dict[tuple[str, str], dict]:
    out = {}
    with path.open() as f:
        for row in csv.DictReader(f):
            t = row["ticker"]
            p = row["period"]
            if not t or not p:
                continue
            out[(t, p)] = {
                "promoter": float(row["promoter_pct"]) if row.get("promoter_pct") else None,
                "fii": float(row["fii_pct"]) if row.get("fii_pct") else None,
                "dii": float(row["dii_pct"]) if row.get("dii_pct") else None,
                "public": float(row["public_pct"]) if row.get("public_pct") else None,
            }
    return out


def _load_reference(path: Path) -> dict[tuple[str, str], dict]:
    """Reference `_flat.csv` is long-format: (ticker, period, category, pct).

    Categories used (case-insensitive substring match on category col):
      promoter → 'promoter'
      fii      → 'fii'
      dii      → 'dii'
      public   → 'public'
    """
    out: dict[tuple[str, str], dict] = {}
    if not path.exists():
        return out
    cat_map = [
        ("promoter", "promoter"),
        ("fii", "fii"),
        ("dii", "dii"),
        ("public", "public"),
    ]
    with path.open() as f:
        for row in csv.DictReader(f):
            t = (row.get("ticker") or "").strip().upper()
            p = (row.get("period") or "").strip()
            cat = (row.get("category") or "").strip().lower()
            pct_raw = row.get("pct") or row.get("value") or ""
            if not t or not p or not cat or pct_raw == "":
                continue
            try:
                v = float(pct_raw)
            except ValueError:
                continue
            target = None
            for needle, dest in cat_map:
                if cat == needle:
                    target = dest
                    break
            if target is None:
                continue
            d = out.setdefault((t, p), {})
            d[target] = v
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--reference", required=True,
        help="Path to an external reference _flat.csv (long-format: "
             "ticker, period, category, pct). Not shipped with this repo.",
    )
    args = ap.parse_args()

    ref_path = Path(args.reference).expanduser()
    if not ref_path.exists():
        print(f"Reference file not found: {ref_path}")
        print("Supply a long-format reference CSV via --reference. "
              "This step is optional and needs no external repo.")
        sys.exit(1)

    print("Loading datasets …")
    nse = _load_nse(PARSED)
    se = _load_reference(ref_path)
    print(f"  nse: {len(nse)} (ticker, period) rows")
    print(f"  reference: {len(se)} (ticker, period) rows")

    # Intersection
    keys_both = set(nse.keys()) & set(se.keys())
    print(f"  intersection: {len(keys_both)}")
    if not keys_both:
        print("No overlap. Check ticker normalisation or the reference file format.")
        return

    matches = {"promoter": 0, "fii": 0, "dii": 0, "public": 0}
    misses = {"promoter": [], "fii": [], "dii": [], "public": []}
    counts = {"promoter": 0, "fii": 0, "dii": 0, "public": 0}

    for k in keys_both:
        a = nse[k]
        b = se[k]
        for cat in ("promoter", "fii", "dii", "public"):
            va, vb = a.get(cat), b.get(cat)
            if va is None or vb is None:
                continue
            counts[cat] += 1
            if abs(va - vb) <= TOLERANCE_PP:
                matches[cat] += 1
            else:
                misses[cat].append({"key": list(k), "nse": va, "se": vb, "diff": round(va - vb, 3)})

    print("\nMatch rates (within ±0.5 pp):")
    summary = {}
    for cat in ("promoter", "fii", "dii", "public"):
        total = counts[cat]
        m = matches[cat]
        rate = (m / total * 100) if total else 0
        print(f"  {cat:<8} {m:>5}/{total:<5} {rate:5.1f}%   "
              f"top mismatches: {sorted(misses[cat], key=lambda x: -abs(x['diff']))[:3]}")
        summary[cat] = {"matched": m, "total": total, "rate_pct": round(rate, 2),
                        "n_misses": len(misses[cat])}

    OUT_REPORT.write_text(json.dumps({
        "n_overlap_keys": len(keys_both),
        "tolerance_pp": TOLERANCE_PP,
        "summary": summary,
        "top_mismatches_per_category": {
            cat: sorted(misses[cat], key=lambda x: -abs(x["diff"]))[:20] for cat in misses
        },
    }, indent=2))
    print(f"\n→ {OUT_REPORT}")


if __name__ == "__main__":
    main()
