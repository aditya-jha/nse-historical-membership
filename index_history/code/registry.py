"""Single loader for index_registry.json — the source of truth for which
indices we track. Used by parse_press_release, build_history, validate, and
fetch_nse_snapshot. Adding a new index = appending one record + running
fetch_nse_snapshot.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "data" / "index_registry.json"


@dataclass(frozen=True)
class IndexSpec:
    id: int
    canonical_name: str
    family: str
    launch_date: date
    target_size: Optional[int]
    aliases: tuple[str, ...]
    snapshot_slug: str
    snapshot_url: str


@lru_cache(maxsize=1)
def load() -> tuple[IndexSpec, ...]:
    raw = json.loads(REGISTRY_PATH.read_text())
    out: list[IndexSpec] = []
    for r in raw["indices"]:
        out.append(IndexSpec(
            id=int(r["id"]),
            canonical_name=r["canonical_name"],
            family=r["family"],
            launch_date=datetime.fromisoformat(r["launch_date"]).date(),
            target_size=r.get("target_size"),
            aliases=tuple(r.get("aliases", [])),
            snapshot_slug=r["snapshot_slug"],
            snapshot_url=r["snapshot_url"],
        ))
    return tuple(out)


def by_id() -> dict[int, IndexSpec]:
    return {s.id: s for s in load()}


def index_name_to_id() -> dict[str, int]:
    """Canonical name → id."""
    return {s.canonical_name: s.id for s in load()}


def alias_to_canonical() -> dict[str, str]:
    """Every alias (case preserved) → canonical name. Use the case-insensitive
    helper at parse-time."""
    out: dict[str, str] = {}
    for s in load():
        for a in s.aliases:
            out[a] = s.canonical_name
    return out


def target_index_ids() -> tuple[int, ...]:
    return tuple(s.id for s in load())


def index_launch() -> dict[int, date]:
    return {s.id: s.launch_date for s in load()}
