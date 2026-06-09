"""Parse every cached PDF in data/press_releases/ and write data/parsed/<stem>.json.

Skips PDFs already parsed (idempotent). Records both Index Maintenance PRs
and non-IM PRs (latter as `is_index_maintenance=false`). Hard-fails only on
the failure mode where a PDF *looks* like an IM notice but cannot be
structurally parsed.

Run: python -m index_history.code.parse_all
"""
from __future__ import annotations
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from index_history.code.parse_press_release import (
    parse_pdf,
    parsed_to_dict,
    ParseFailure,
    PR_DIR,
    PARSED_DIR,
)

INDEX_FILE = PR_DIR / "_index.json"


def _url_for(pdf_name: str) -> str:
    return f"https://niftyindices.com/Press_Release/{pdf_name}"


def _process_one(pdf_path_str: str) -> tuple[str, str, str | None]:
    pdf_path = Path(pdf_path_str)
    out = PARSED_DIR / (pdf_path.stem + ".json")
    if out.exists():
        return (pdf_path.name, "cached", None)
    try:
        pr = parse_pdf(pdf_path, source_url=_url_for(pdf_path.name))
        out.write_text(json.dumps(parsed_to_dict(pr), indent=2))
        if pr.is_index_maintenance and pr.events:
            return (pdf_path.name, "im_with_events", None)
        if pr.is_index_maintenance and not pr.events:
            return (pdf_path.name, "im_no_target_indices", None)
        return (pdf_path.name, "non_im", None)
    except ParseFailure as e:
        return (pdf_path.name, "FAIL", str(e))
    except Exception as e:  # noqa: BLE001
        return (pdf_path.name, "ERROR", f"{type(e).__name__}: {e}")


def main():
    pdfs = sorted(PR_DIR.glob("ind_prs*.pdf"))
    print(f"PDFs cached: {len(pdfs)}")

    counts = {"cached": 0, "im_with_events": 0, "im_no_target_indices": 0, "non_im": 0}
    failures: list[tuple[str, str]] = []

    with ProcessPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(_process_one, str(p)): p.name for p in pdfs}
        for i, fut in enumerate(as_completed(futs), 1):
            name, status, err = fut.result()
            if status in counts:
                counts[status] += 1
            else:
                failures.append((name, err or status))
            if i % 50 == 0 or i == len(pdfs):
                print(f"  {i}/{len(pdfs)} processed")

    print()
    print("=== Summary ===")
    for k, v in counts.items():
        print(f"  {k:30s}: {v}")
    print(f"  failures                      : {len(failures)}")

    if failures:
        print()
        print("Failed PDFs (will halt walk-backward unless overridden):")
        for n, e in failures[:50]:
            print(f"  {n}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
