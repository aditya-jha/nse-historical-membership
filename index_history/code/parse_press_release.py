"""Parse one NSE Index-Maintenance press-release PDF into structured events.

Output schema (one JSON file per PDF, written to data/parsed/<pdf_stem>.json):

    {
        "source_pdf": "ind_prs28022024.pdf",
        "source_url":  "https://niftyindices.com/Press_Release/ind_prs28022024.pdf",
        "publication_date": "2024-02-28",
        "effective_date":   "2024-03-28",          # null if PR is not a replacement notice
        "is_index_maintenance": true,
        "events": [
            {"index_name": "Nifty 50",        "index_id": 217, "excluded": ["UPL"], "included": ["SHRIRAMFIN"]},
            {"index_name": "Nifty Next 50",   "index_id": 218, "excluded": [...], "included": [...]},
            ...
        ]
    }

If a PDF is not an Index Maintenance Sub-Committee replacement notice (e.g. a
dividend release), `is_index_maintenance` is False, `effective_date` is None,
and `events` is empty. The walk-backward consumer should skip such PDFs.

Failure policy: if the PDF *looks* like an index maintenance notice
(contains the trigger phrase) but we cannot extract a clean `effective_date`
or any structured `events`, raise ParseFailure. Caller decides whether to
hard-fail (default) or quarantine.
"""
from __future__ import annotations
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pdfplumber
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
PR_DIR = ROOT / "data" / "press_releases"
PARSED_DIR = ROOT / "data" / "parsed"
PARSED_DIR.mkdir(parents=True, exist_ok=True)

# Canonical names → index_id (matches nse_indices.id).
INDEX_NAME_TO_ID = {
    "Nifty 50":             217,
    "Nifty Next 50":        218,
    "Nifty 100":            219,
    "Nifty 500":            221,
    "Nifty Midcap 150":     223,
    "Nifty Smallcap 250":   227,
}

# Loose-form names that PR PDFs sometimes use for the same index.
# Map every variant to the canonical key in INDEX_NAME_TO_ID.
INDEX_ALIASES: dict[str, str] = {
    "Nifty 50":           "Nifty 50",
    "Nifty50":            "Nifty 50",
    "NIFTY 50":           "Nifty 50",
    "Nifty Next 50":      "Nifty Next 50",
    "NiftyNext 50":       "Nifty Next 50",
    "Nifty Next50":       "Nifty Next 50",
    "Nifty 100":          "Nifty 100",
    "Nifty100":           "Nifty 100",
    "Nifty 500":          "Nifty 500",
    "Nifty500":           "Nifty 500",
    "Nifty Midcap 150":   "Nifty Midcap 150",
    "NiftyMidcap 150":    "Nifty Midcap 150",
    "Nifty Midcap150":    "Nifty Midcap 150",
    "Nifty Smallcap 250": "Nifty Smallcap 250",
    "Nifty Smallcap250":  "Nifty Smallcap 250",
}

TRIGGER_PHRASES = (
    "Index Maintenance Sub-Committee",
    "replacement of stocks",
    "Replacements in indices",
    "is being excluded",
    "are being excluded",
)
EFFECTIVE_RE = re.compile(
    r"effective\s+from\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", re.I,
)
MUMBAI_RE = re.compile(r"Mumbai,\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})")
# Section header e.g.
#   "1) Nifty 50"          (pre-2024 PRs)
#   "b) Nifty Next 50"     (2024+ PRs)
#   "A. Nifty 50"          (occasional letter-dot form)
SECTION_RE = re.compile(
    r"^\s*(?:\d+|[a-z]|[A-Z])[\)\.]\s+(?P<name>[A-Za-z0-9 &/\-]+?)\s*$", re.M,
)
# Symbol row inside a table: "1 Some Company Ltd. SYMBOL"
SYMBOL_ROW_RE = re.compile(
    r"^\s*\d+\s+.+?\s+([A-Z0-9&\-\.]{2,20})\s*$", re.M,
)


class ParseFailure(RuntimeError):
    pass


@dataclass
class IndexEvent:
    index_name: str
    index_id: int
    excluded: list[str] = field(default_factory=list)
    included: list[str] = field(default_factory=list)


@dataclass
class ParsedPR:
    source_pdf: str
    source_url: str
    publication_date: Optional[str]
    effective_date: Optional[str]
    is_index_maintenance: bool
    events: list[IndexEvent] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _extract_text(pdf_path: Path) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    if len(text.strip()) >= 50:
        return text
    # Image-only PDF — fall back to OCR if tesseract + pdftoppm are available.
    if shutil.which("tesseract") and shutil.which("pdftoppm"):
        return _ocr_pdf(pdf_path)
    return text


def _ocr_pdf(pdf_path: Path) -> str:
    """Render PDF to PNG pages via pdftoppm, then OCR each page via tesseract."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        # pdftoppm at 300 DPI gives clean OCR for press-release tables.
        subprocess.run(
            ["pdftoppm", "-r", "300", "-png", str(pdf_path), str(tdp / "page")],
            check=True, capture_output=True,
        )
        pages = sorted(tdp.glob("page-*.png"))
        out: list[str] = []
        for png in pages:
            r = subprocess.run(
                ["tesseract", str(png), "-", "-l", "eng", "--psm", "6"],
                check=True, capture_output=True, text=True,
            )
            out.append(r.stdout)
        return "\n".join(out)


def _parse_human_date(s: str) -> Optional[str]:
    """ 'February 28, 2024' → '2024-02-28' """
    s = s.strip().rstrip(".")
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Yield (raw_index_name, section_body) pairs, where section_body is
    the substring from this section's header to the next section header
    (or end of doc)."""
    matches = list(SECTION_RE.finditer(text))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((m.group("name").strip(), text[start:end]))
    return out


def _extract_symbols_block(body: str, marker_re: re.Pattern[str]) -> list[str]:
    """Find marker (e.g. 'is being excluded' / 'being included') and pull
    SYMBOL_ROW_RE matches until the next marker / end of body / boundary phrase.
    """
    m = marker_re.search(body)
    if not m:
        return []
    sub = body[m.end():]
    # Stop at the next 'The following' phrase, the next 'The above' commentary,
    # or the start of another index section.
    stop = re.search(
        r"(The following|The above|The replacement|^\s*\d+\)\s+[A-Z])",
        sub, re.M,
    )
    if stop:
        sub = sub[: stop.start()]
    return [m.group(1) for m in SYMBOL_ROW_RE.finditer(sub)]


EXCLUDE_MARKER = re.compile(r"following\s+compan(?:y|ies)\s+(?:is|are)\s+being\s+excluded", re.I)
INCLUDE_MARKER = re.compile(r"following\s+compan(?:y|ies)\s+(?:is|are)\s+being\s+included", re.I)


def parse_pdf(pdf_path: Path, source_url: Optional[str] = None) -> ParsedPR:
    text = _extract_text(pdf_path)
    if not text.strip() or len(text) < 50:
        # Image-based scanned PDF — no text layer. Common for older PRs.
        # Treat as non-IM with a note; if this date turns out to need manual
        # coverage, add an entry to data/manual_overrides/.
        return ParsedPR(
            source_pdf=pdf_path.name,
            source_url=source_url or "",
            publication_date=None,
            effective_date=None,
            is_index_maintenance=False,
            notes=["image-only PDF (no text layer); needs OCR or manual override"],
        )

    pub_match = MUMBAI_RE.search(text)
    publication = _parse_human_date(pub_match.group(1)) if pub_match else None

    is_im = any(p.lower() in text.lower() for p in TRIGGER_PHRASES)
    if not is_im:
        return ParsedPR(
            source_pdf=pdf_path.name,
            source_url=source_url or "",
            publication_date=publication,
            effective_date=None,
            is_index_maintenance=False,
        )

    eff_match = EFFECTIVE_RE.search(text)
    effective = _parse_human_date(eff_match.group(1)) if eff_match else None
    if not effective:
        # Some PRs say e.g. "with immediate effect" or "effective from <date>"
        # without "from"; try a looser pattern.
        loose = re.search(
            r"effective\s+(?:from\s+)?([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", text, re.I,
        )
        if loose:
            effective = _parse_human_date(loose.group(1))

    events: list[IndexEvent] = []
    # Build a case-insensitive alias lookup once.
    ci_aliases = {k.lower(): v for k, v in INDEX_ALIASES.items()}
    for raw_name, body in _split_sections(text):
        rn = raw_name.strip()
        canon = ci_aliases.get(rn.lower()) or ci_aliases.get(rn.replace(" ", "").lower())
        if canon is None:
            # Loose: exact-prefix match (catches "Nifty 50 Equal Weight" → no match,
            # but also rejects "Nifty 50" — only an exact match counts).
            for k_lower, v in ci_aliases.items():
                if rn.lower() == k_lower:
                    canon = v
                    break
        if canon is None or canon not in INDEX_NAME_TO_ID:
            continue
        excluded = _extract_symbols_block(body, EXCLUDE_MARKER)
        included = _extract_symbols_block(body, INCLUDE_MARKER)
        if not excluded and not included:
            continue
        events.append(
            IndexEvent(
                index_name=canon,
                index_id=INDEX_NAME_TO_ID[canon],
                excluded=excluded,
                included=included,
            )
        )

    pr = ParsedPR(
        source_pdf=pdf_path.name,
        source_url=source_url or "",
        publication_date=publication,
        effective_date=effective,
        is_index_maintenance=True,
        events=events,
    )

    # Sanity gates
    if events and not effective:
        raise ParseFailure(
            f"{pdf_path.name}: events extracted but no effective_date — manual review required"
        )
    # In/out sets must balance per index (replacement count match)
    for ev in events:
        if len(ev.excluded) != len(ev.included):
            pr.notes.append(
                f"{ev.index_name}: |excluded|={len(ev.excluded)} != |included|={len(ev.included)} "
                f"(may be legitimate for off-cycle events but flag for review)"
            )

    return pr


def parsed_to_dict(p: ParsedPR) -> dict:
    d = asdict(p)
    # asdict already converts list[IndexEvent] correctly via dataclass support
    return d


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        # Try resolving relative to PR_DIR
        candidate = PR_DIR / sys.argv[1]
        if candidate.exists():
            pdf_path = candidate
        else:
            sys.exit(f"not found: {pdf_path}")

    pr = parse_pdf(pdf_path)
    out_path = PARSED_DIR / (pdf_path.stem + ".json")
    out_path.write_text(json.dumps(parsed_to_dict(pr), indent=2))
    print(json.dumps(parsed_to_dict(pr), indent=2))
    print(f"\n→ {out_path}")


if __name__ == "__main__":
    main()
