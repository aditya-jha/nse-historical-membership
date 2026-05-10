"""Empirically detect candidate symbol renames.

Heuristic:
  - For each archive snapshot date D and each index I:
    - ARCH(I, D) = symbol set in index_equity_map_archive at that date.
    - WALKED(I, D) = symbol set our walk-back produces.
    - extra = WALKED - ARCH      (symbols we wrongly think were members)
    - missing = ARCH - WALKED    (symbols we missed)
  - If a symbol X is in `extra` at every date AND a symbol Y is in `missing`
    at every date for the same index, AND X is in current snapshot AND Y is
    NOT in current snapshot, then Y → X is a likely rename.

Output: data/manual_overrides/symbol_renames_detected.json
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
from tools.postgres.connection import engine  # noqa: E402

OUT = ROOT / "data" / "manual_overrides" / "symbol_renames_detected.json"

TARGETS = (217, 218, 219, 221, 223, 227)


def main():
    with engine.connect() as c:
        # All snapshot dates
        snap_dates = [r[0] for r in c.execute(text(
            "SELECT DISTINCT created::date FROM index_equity_map_archive ORDER BY 1"
        ))]
        # Current snapshot global
        current_global: set[str] = {r[0].upper().strip() for r in c.execute(text(
            "SELECT DISTINCT symbol FROM index_equity_map"
        ))}

        candidates_by_idx: dict[int, dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        # For each (index, date), collect extra and missing
        for idx in TARGETS:
            extras_per_date = []
            missing_per_date = []
            for d in snap_dates:
                arch = {r[0].upper().strip() for r in c.execute(text(
                    "SELECT symbol FROM index_equity_map_archive "
                    "WHERE index_id=:i AND created::date=:d"
                ), {"i": idx, "d": d})}
                if not arch:
                    continue
                walked = {r[0] for r in c.execute(text("""
                    SELECT symbol FROM index_membership_history
                    WHERE index_id=:i AND valid_from<=:d AND (valid_to IS NULL OR valid_to>:d)
                """), {"i": idx, "d": d})}
                extras_per_date.append(walked - arch)
                missing_per_date.append(arch - walked)

            if not extras_per_date:
                continue

            # Symbols always extra (in our walk but not arch, every date)
            always_extra = set.intersection(*extras_per_date) if extras_per_date else set()
            # Symbols always missing
            always_missing = set.intersection(*missing_per_date) if missing_per_date else set()
            candidates_by_idx[idx]["always_extra"] = always_extra
            candidates_by_idx[idx]["always_missing"] = always_missing
            print(f"index={idx}:")
            print(f"  always extra (in current, never in arch): {sorted(always_extra)}")
            print(f"  always missing (in arch, never in our walk): {sorted(always_missing)}")

        # Cross-correlate to suggest renames: for each "always_missing" Y,
        # if Y is NOT in current_global AND there's an "always_extra" X in
        # current_global, X→Y is a candidate.
        suggestions: dict[str, list[str]] = {}
        for idx, d in candidates_by_idx.items():
            extras_in_current = [s for s in d["always_extra"] if s in current_global]
            missing_not_current = [s for s in d["always_missing"] if s not in current_global]
            # Pair them by 1:1 match — best-effort heuristic; may need human review
            for s in missing_not_current:
                suggestions.setdefault(s, [])
            print(f"\nindex={idx} rename candidates:")
            print(f"  unmapped 'always extra' (in current): {sorted(extras_in_current)}")
            print(f"  unmapped 'always missing' (not in current): {sorted(missing_not_current)}")

        OUT.write_text(json.dumps({
            k: sorted(v.get("always_missing", set()))
            for k, v in candidates_by_idx.items()
        }, indent=2, default=list))
        print(f"\n→ Wrote raw diagnostics to {OUT}")


if __name__ == "__main__":
    main()
