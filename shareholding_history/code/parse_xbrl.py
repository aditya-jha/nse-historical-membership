"""Parse SHP XBRL files in data/xbrl/ → flat CSV (ticker, period, %s).

Handles two SEBI taxonomy generations transparently:

  * **2018-03-31 to 2025-10-30**: percentages stored as basis-points × 100
    (e.g. promoter 50.49% appears as 5049.0).
  * **2025-10-31 onward (V1.1)**: percentages stored as fractions
    (e.g. promoter 50% appears as 0.5).

Auto-detection: if (promoter + public) > 1000, divide all by 100.  If
(promoter + public) < 2, multiply all by 100.  Otherwise as-is.

Output: data/parsed/_flat.csv
    ticker, period, promoter_pct, fii_pct, dii_pct, public_pct, noninst_pct,
    taxonomy, source_filename

`period` is YYYY-MM (extracted from the filing date in filings_index, since
that is the period the filing reports on).

Run:
    python -m shareholding_history.code.parse_xbrl
    python -m shareholding_history.code.parse_xbrl --tickers RELIANCE
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "data" / "filings_index"
XBRL_DIR = ROOT / "data" / "xbrl"
OUT_DIR = ROOT / "data" / "parsed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CATEGORY_MEMBERS = {
    "promoter": "ShareholdingOfPromoterAndPromoterGroupMember",
    "public":   "PublicShareholdingMember",
    "fii":      "InstitutionsForeignMember",
    "dii":      "InstitutionsDomesticMember",
    "noninst":  "NonInstitutionsMember",
}

# Same dimension names; different XBRL fact tag — gives raw share counts
# per category, which we sum to derive total_shares_outstanding.
SHARES_TAG = "NumberOfShares"

PCT_TAGS = (
    "ShareholdingAsAPercentageOfTotalNumberOfShares",
    # Older taxonomy may use a slightly different tag — leave room to extend.
)

CTX_RE = re.compile(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', re.DOTALL)
DIM_RE = re.compile(r'<xbrldi:explicitMember[^>]*>([^<]+)</xbrldi:explicitMember>')
TAXONOMY_RE = re.compile(r'xmlns:in-bse-shp="(http://[^"]+)"')


def _parse_period_from_date_str(date_str: str) -> str | None:
    """e.g. '31-MAR-2026' → '2026-03'."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str.strip(), "%d-%b-%Y")
    except ValueError:
        try:
            dt = datetime.strptime(date_str.strip(), "%d-%B-%Y")
        except ValueError:
            return None
    return dt.strftime("%Y-%m")


def parse_xbrl(path: Path) -> dict | None:
    """Parse a single SHP XBRL → {category: pct, taxonomy: url}.

    Returns None if no recognisable shareholding facts found.
    """
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    if not txt.startswith("<?xml") and not txt.lstrip().startswith("<"):
        return None

    # Build context_id → set of dimension members.
    ctx_members: dict[str, set[str]] = {}
    for cid, body in CTX_RE.findall(txt):
        ctx_members[cid] = set(DIM_RE.findall(body))

    facts: dict[str, float] = {}
    for tag in PCT_TAGS:
        pattern = re.compile(
            rf'<in-bse-shp:{tag} contextRef="([^"]+)"[^>]*>([\d.\-]+)</in-bse-shp:{tag}>'
        )
        for m in pattern.finditer(txt):
            cid, raw_val = m.group(1), m.group(2)
            try:
                val = float(raw_val)
            except ValueError:
                continue
            members = ctx_members.get(cid, set())
            if len(members) > 2:
                continue  # composite sub-categories — ignore for the rollup
            for cat, member_name in CATEGORY_MEMBERS.items():
                target = f"in-bse-shp:{member_name}"
                if target in members and cat not in facts:
                    facts[cat] = val
                    break

    # Per-category share counts (separate dict — these are raw share counts,
    # not percentages, so don't go through the scale-normalisation below).
    shares: dict[str, int] = {}
    shares_pat = re.compile(
        rf'<in-bse-shp:{SHARES_TAG} contextRef="([^"]+)"[^>]*>(\d+)</in-bse-shp:{SHARES_TAG}>'
    )
    for m in shares_pat.finditer(txt):
        cid, raw_val = m.group(1), m.group(2)
        try:
            val = int(raw_val)
        except ValueError:
            continue
        members = ctx_members.get(cid, set())
        if len(members) > 2:
            continue
        for cat, member_name in CATEGORY_MEMBERS.items():
            target = f"in-bse-shp:{member_name}"
            if target in members and cat not in shares:
                shares[cat] = val
                break

    if not facts:
        return None

    # Auto-detect scale via (promoter + public) which should equal ~100%.
    promoter = facts.get("promoter")
    public = facts.get("public")
    scale = 1.0
    if promoter is not None and public is not None:
        total = promoter + public
        if total > 1000:
            scale = 0.01
        elif 0 < total < 2:
            scale = 100.0
    elif promoter is not None or public is not None:
        v = promoter if promoter is not None else public
        if v > 1000:
            scale = 0.01
        elif 0 < v < 2:
            scale = 100.0

    out = {k: round(v * scale, 4) for k, v in facts.items()}
    # Total shares outstanding = sum of Promoter + Public (the two roll-ups
    # whose pcts sum to ~100%).  Other dimensions (FII, DII, NonInst) are
    # subsets of Public.
    total_shares = None
    if "promoter" in shares and "public" in shares:
        total_shares = shares["promoter"] + shares["public"]
    elif "public" in shares and out.get("public"):
        # Fall back: derive from Public when promoter share count missing.
        if out["public"] > 0:
            total_shares = int(shares["public"] / (out["public"] / 100.0))
    out["total_shares"] = total_shares
    tax_match = TAXONOMY_RE.search(txt[:2000])
    out["taxonomy"] = tax_match.group(1) if tax_match else ""
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", help="Comma-separated subset (default: all)")
    ap.add_argument("--out", default=str(OUT_DIR / "_flat.csv"), help="Output CSV path")
    args = ap.parse_args()

    targets = set(t.strip().upper() for t in args.tickers.split(",")) if args.tickers else None
    rows: list[dict] = []
    n_files = 0
    n_parsed = 0
    n_missing = 0
    n_no_xbrl_on_disk = 0

    files = sorted(INDEX_DIR.glob("*.json"))
    if targets:
        files = [f for f in files if f.stem.upper() in targets]
    print(f"Walking {len(files)} ticker manifest(s) …")

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
            n_files += 1
            fn = url.rsplit("/", 1)[-1]
            xbrl_path = XBRL_DIR / fn
            if not xbrl_path.exists() or xbrl_path.stat().st_size < 1024:
                n_no_xbrl_on_disk += 1
                continue
            parsed = parse_xbrl(xbrl_path)
            if parsed is None:
                n_missing += 1
                continue
            period = _parse_period_from_date_str(fl.get("date") or "")
            rows.append({
                "ticker": ticker,
                "period": period,
                "filing_date": fl.get("date"),
                "submission_date": fl.get("submission_date"),
                "promoter_pct": parsed.get("promoter"),
                "fii_pct": parsed.get("fii"),
                "dii_pct": parsed.get("dii"),
                "public_pct": parsed.get("public"),
                "noninst_pct": parsed.get("noninst"),
                "total_shares": parsed.get("total_shares"),
                "taxonomy": parsed.get("taxonomy"),
                "source_filename": fn,
            })
            n_parsed += 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["ticker", "period", "filing_date", "submission_date",
              "promoter_pct", "fii_pct", "dii_pct", "public_pct", "noninst_pct",
              "total_shares", "taxonomy", "source_filename"]
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x["ticker"], x["period"] or "")):
            w.writerow(r)

    print(f"\nfilings_referenced={n_files}")
    print(f"  on_disk_parsed={n_parsed}")
    print(f"  on_disk_unparseable={n_missing}")
    print(f"  not_yet_downloaded={n_no_xbrl_on_disk}")
    print(f"  → {out_path}  ({len(rows)} rows)")


if __name__ == "__main__":
    main()
