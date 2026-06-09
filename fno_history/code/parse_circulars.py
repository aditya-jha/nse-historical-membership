"""Parse FAOP introduction/exclusion circulars → structured events.

Output JSON per PDF in data/parsed/<stem>.json:

  {
    "source_pdf":     "FAOP73205.pdf",
    "source_url":     "https://nsearchives.nseindia.com/...",
    "circular_no":    "NSE/FAOP/73205",
    "circular_date":  "2026-03-09",
    "kind":           "introduction" | "exclusion",
    "effective_date": "2026-04-01",
    "symbols":        ["ADANIPOWER", "COCHINSHIP", ...],
  }

Run: python -m fno_history.code.parse_circulars
"""
from __future__ import annotations
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
CIRC_DIR = ROOT / "data" / "circulars"
PARSED_DIR = ROOT / "data" / "parsed"
PARSED_DIR.mkdir(parents=True, exist_ok=True)

INDEX_FILE = CIRC_DIR / "_index.json"

# Effective-date patterns, in priority order:
#   "would be available for trading w.e.f. April 01, 2026"
#   "no contracts shall be available for trading ... w.e.f. July 01, 2026"
#   "with effect from April 27, 2018."
#   "will be available for trading from November 29, 2024"
#   "available for trading from August 01, 2025"
EFFECTIVE_PATTERNS = [
    re.compile(r"w\.e\.f\.?\s+([A-Z][a-z]+\s+\d{1,2}\s*,?\s*\d{4})", re.I),
    re.compile(r"with\s+effect\s+from\s+([A-Z][a-z]+\s+\d{1,2}\s*,?\s*\d{4})", re.I | re.S),
    re.compile(r"available\s+for\s+trading\s+(?:w\.e\.f\.?|from)\s+([A-Z][a-z]+\s+\d{1,2}\s*,?\s*\d{4})", re.I | re.S),
    re.compile(r"new\s+contracts\s+will\s+be\s+available\s+for\s+trading\s+from\s+([A-Z][a-z]+\s+\d{1,2}\s*,?\s*\d{4})", re.I | re.S),
    re.compile(r"shall\s+be\s+made\s+available\s+for\s+trading\s+(?:in[^,.]*\s+)?(?:w\.e\.f\.?|from)\s+([A-Z][a-z]+\s+\d{1,2}\s*,?\s*\d{4})", re.I | re.S),
    re.compile(r"trading\s+from\s+([A-Z][a-z]+\s+\d{1,2}\s*,?\s*\d{4})", re.I | re.S),
    re.compile(r"effective\s+date\s*[:\-]?\s*([A-Z][a-z]+\s+\d{1,2}\s*,?\s*\d{4})", re.I),
]

# Also recognise "introduction" of an INDEX-level F&O contract (Nifty Midcap
# Select etc.) — we skip those for stock-level F&O membership.
INDEX_INTRO_RE = re.compile(
    r"Introduction of Futures (?:&|and) Options Contracts? on\s+(Nifty[A-Za-z0-9 ]+Index|BANK ?NIFTY|FINNIFTY)",
    re.I,
)
CIRC_NO_RE = re.compile(r"Download Ref No:\s*(NSE/FAOP/\d+)", re.I)
DATE_RE = re.compile(r"Date:\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4})")
SUBJ_INTRO = re.compile(r"Introduction of Futures\s*(?:&|and)\s*Options", re.I)
SUBJ_EXCL = re.compile(r"Exclusion of Futures\s*(?:&|and)\s*Options", re.I)
# Symbol-row patterns (table column order varies year-to-year).
# Tried in order; results union-ed.
SYMBOL_ROW_PATTERNS = [
    # "1 ADANIPOWER Adani Power Limited"  (Sr|Symbol|Security)
    re.compile(r"^\s*\d+\s+([A-Z][A-Z0-9&\-\.]{1,19})\s+[A-Z]", re.M),
    # "1 ADANI POWER LTD ADANIPOWER 625 12000"  (Sr|Name|Symbol|Lot[|QtyFreeze])
    re.compile(r"^\s*\d+\s+.+?\s+([A-Z][A-Z0-9&\-\.]{1,19})\s+\d{1,7}(?:\s+\d{1,8})?\s*$", re.M),
    # "1 Aditya Birla Fashion and Retail Limited ABFRL"  (Sr|Name|Symbol — no numbers)
    re.compile(r"^\s*\d+\s+[A-Z][A-Za-z0-9&\-\.\s]+?\s+([A-Z][A-Z0-9&\-\.]{1,19})\s*$", re.M),
]


def _parse_date(s: str) -> Optional[str]:
    s = re.sub(r"\s+", " ", s.strip().rstrip("."))
    # Normalise "29,2024" → "29, 2024"
    s = re.sub(r",(\d)", r", \1", s)
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_pdf(pdf_path: Path, source_url: str = "") -> dict:
    # CMPT (Clearing) circulars are not F&O segment changes — skip without parsing.
    if pdf_path.stem.upper().startswith(("CMPT", "SURV")):
        return {
            "source_pdf": pdf_path.name, "source_url": source_url,
            "kind": None, "effective_date": None, "symbols": [],
            "notes": "non-FAOP department (clearing/surveillance)",
        }
    with pdfplumber.open(pdf_path) as pdf:
        full = "\n".join((p.extract_text() or "") for p in pdf.pages)
    if not full.strip() or len(full) < 100:
        return {
            "source_pdf": pdf_path.name, "source_url": source_url,
            "kind": None, "effective_date": None, "symbols": [],
            "notes": "image-only or empty",
        }

    if INDEX_INTRO_RE.search(full):
        return {
            "source_pdf": pdf_path.name, "source_url": source_url,
            "kind": None, "effective_date": None, "symbols": [],
            "notes": "index-level F&O introduction (not stock)",
        }
    if SUBJ_INTRO.search(full):
        kind = "introduction"
    elif SUBJ_EXCL.search(full):
        kind = "exclusion"
    else:
        return {
            "source_pdf": pdf_path.name, "source_url": source_url,
            "kind": None, "effective_date": None, "symbols": [],
            "notes": "subject not introduction/exclusion",
        }

    # Effective date — try patterns in order
    eff = None
    for pat in EFFECTIVE_PATTERNS:
        m = pat.search(full)
        if m:
            eff = _parse_date(m.group(1))
            if eff:
                break

    # Circular number + date for traceability
    cm = CIRC_NO_RE.search(full)
    circ_no = cm.group(1) if cm else None
    dm = DATE_RE.search(full)
    circular_date = _parse_date(dm.group(1)) if dm else None

    # Symbols. Bound the search region to the table area to reduce false hits
    # from boilerplate elsewhere.
    if kind == "introduction":
        # Find the table region. Header may be "Sr. No. Symbol Security Name"
        # OR "Sr. No. Security Name Symbol Lot Size" — column ORDER matters
        # because using SYMBOL_FIRST when the table is Security|Symbol order
        # produces false positives (matches "APL Apollo" → "APL", etc.).
        m1 = re.search(r"Sr\.?\s*No\.?\s+(Symbol|Security|Name|Particulars)", full, re.I)
        first_col = m1.group(1).lower() if m1 else None
        if m1:
            tail = full[m1.end():]
            stop = re.search(
                r"(Other Important Points|Accordingly,\s*members|For and on behalf"
                r"|Page\s*\d+\s*of\s*\d+|The scheme of strikes|The Quantity freeze"
                r"|National Stock Exchange of India Limited\s*\n*\s*For)",
                tail, re.I,
            )
            tail = tail[: stop.start()] if stop else tail
        else:
            tail = full
        # Pattern 0 = SYMBOL_FIRST (only safe when header has Symbol first).
        # Patterns 1-2 = name-then-symbol (with or without trailing numbers).
        if first_col == "symbol":
            patterns_to_try = SYMBOL_ROW_PATTERNS
        else:
            patterns_to_try = SYMBOL_ROW_PATTERNS[1:]  # skip SYMBOL_FIRST
        syms = []
        for pat in patterns_to_try:
            syms.extend(pat.findall(tail))
    else:
        # Exclusion is usually "on SYMBOL" in subject line itself
        # Plus tabular form for multi-symbol exclusions
        syms: list[str] = []
        # First try subject line
        sub_m = re.search(
            r"Exclusion of Futures (?:and|&) Options contracts? on\s+"
            r"([A-Z][A-Z0-9&\-\.,\s]+?)(?:\s+w\.e\.f|\s*\n|\s*$)", full, re.I,
        )
        if sub_m:
            chunk = sub_m.group(1)
            # Could be 'SAMMAANCAP' or 'Four Securities' (just a count)
            for tok in re.findall(r"\b[A-Z][A-Z0-9&\-\.]{1,19}\b", chunk):
                # Filter out the 'Securities'/'Symbol' words
                if tok not in {"Securities", "Symbol", "Symbols"} and len(tok) >= 2:
                    syms.append(tok)
        # Then table
        m1 = re.search(r"Sr\.?\s*No\.?\s+Symbol", full, re.I)
        if m1:
            tail = full[m1.end():]
            stop = re.search(r"(However|For and on behalf|Page\s*\d+\s*of)",
                             tail, re.I)
            tail = tail[: stop.start()] if stop else tail
            for pat in SYMBOL_ROW_PATTERNS:
                hits = pat.findall(tail)
                if hits:
                    syms = hits or syms
                    break

    # Subject-line fallback for single-symbol introductions
    # e.g. "Introduction of Futures & Options Contracts on ICICIGI"
    if not syms:
        subj_m = re.search(
            r"(?:Introduction|Exclusion) of Futures (?:and|&) Options Contracts? on\s+"
            r"([A-Z][A-Z0-9&\-\.,\s]+?)(?:\s+w\.e\.f|\s*-?\s*Update|\s*\n|\s*$)",
            full, re.I,
        )
        if subj_m:
            for tok in re.findall(r"\b[A-Z][A-Z0-9&\-\.]{1,19}\b", subj_m.group(1)):
                if tok not in {"Securities", "Symbol", "Symbols", "Two", "Three",
                               "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
                               "Individual", "Additional"} and len(tok) >= 2:
                    syms.append(tok)

    # Final cleanup — uppercase, dedup, drop common false positives
    BAD = {"NSE", "SEBI", "MRD", "POD", "FAOP", "MII", "PDF", "CSV"}
    cleaned = []
    seen = set()
    for s in syms:
        s = s.upper().strip()
        if s in BAD or s in seen:
            continue
        seen.add(s)
        cleaned.append(s)

    return {
        "source_pdf":     pdf_path.name,
        "source_url":     source_url,
        "circular_no":    circ_no,
        "circular_date":  circular_date,
        "kind":           kind,
        "effective_date": eff,
        "symbols":        cleaned,
    }


def _process(args):
    pdf_path_str, source_url = args
    pdf_path = Path(pdf_path_str)
    out = PARSED_DIR / (pdf_path.stem + ".json")
    if out.exists():
        return (pdf_path.name, "cached")
    try:
        rec = parse_pdf(pdf_path, source_url)
        out.write_text(json.dumps(rec, indent=2))
        if rec["kind"] is None:
            return (pdf_path.name, "skip")
        if not rec["effective_date"] or not rec["symbols"]:
            return (pdf_path.name, "incomplete")
        return (pdf_path.name, rec["kind"])
    except Exception as e:
        return (pdf_path.name, f"ERR_{type(e).__name__}")


def main():
    inv = json.loads(INDEX_FILE.read_text())
    url_by_pdf = {Path(r["circFilelink"]).stem: r["circFilelink"]
                  for r in inv if r.get("circFilelink")}

    pdfs = sorted(CIRC_DIR.glob("*.pdf"))
    print(f"PDFs: {len(pdfs)}")
    args = [(str(p), url_by_pdf.get(p.stem, "")) for p in pdfs]

    counts = {"cached": 0, "introduction": 0, "exclusion": 0,
              "skip": 0, "incomplete": 0}
    failed: list[tuple[str, str]] = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        for name, status in pool.map(_process, args):
            if status in counts:
                counts[status] += 1
            else:
                failed.append((name, status))
    print()
    for k, v in counts.items():
        print(f"  {k:20s}: {v}")
    print(f"  errors            : {len(failed)}")
    for n, e in failed[:10]:
        print(f"    {n}: {e}")


if __name__ == "__main__":
    main()
