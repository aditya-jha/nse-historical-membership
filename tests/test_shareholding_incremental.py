"""Shareholding incremental refresh — a re-fetch or re-parse may only add data."""
from __future__ import annotations

import pytest

from shareholding_history.code.parse_xbrl import merge_rows


def test_refetch_never_drops_cached_filings():
    pytest.importorskip("requests")
    from shareholding_history.code.fetch_filings import merge_filings
    old = [{"xbrl": "a.xml", "date": "31-MAR-2026"}, {"xbrl": "z.xml", "date": "31-MAR-2005"}]
    new = [{"xbrl": "n.xml", "date": "30-SEP-2026"}, {"xbrl": "a.xml", "date": "31-MAR-2026"}]
    assert [f["xbrl"] for f in merge_filings(old, new)] == ["n.xml", "a.xml", "z.xml"]


def test_append_keeps_history_and_replaces_reparsed():
    old = [{"ticker": "X", "source_filename": "a.xml", "fii_pct": "1"},
           {"ticker": "X", "source_filename": "b.xml", "fii_pct": "2"}]
    new = [{"ticker": "X", "source_filename": "b.xml", "fii_pct": "3"},
           {"ticker": "X", "source_filename": "c.xml", "fii_pct": "4"},
           {"ticker": "X", "source_filename": "c.xml", "fii_pct": "4"}]  # NSE lists some filings twice
    assert [(r["source_filename"], r["fii_pct"]) for r in merge_rows(old, new)] == [
        ("a.xml", "1"), ("b.xml", "3"), ("c.xml", "4")]


def test_fetch_since_merges_both_segments_per_symbol(tmp_path, monkeypatch):
    pytest.importorskip("requests")
    import json
    from shareholding_history.code import fetch_filings as ff

    monkeypatch.setattr(ff, "INDEX_DIR", tmp_path)
    (tmp_path / "OLD.json").write_text(json.dumps({"filings": [{"xbrl": "old-2005.xml"}]}))
    responses = {
        "equities": [{"symbol": "OLD", "xbrl": "old-2026.xml", "date": "30-SEP-2026"},
                     {"symbol": "NEWCO", "xbrl": "", "date": "30-SEP-2026"}],  # no XBRL: skipped
        "sme": [{"symbol": "SMECO", "xbrl": "sme.xml", "date": "30-SEP-2026"}],
    }

    class Resp:
        def __init__(self, body): self.body = body
        def raise_for_status(self): pass
        def json(self): return self.body

    class Session:
        def get(self, url, params, **kw): return Resp(responses[params["index"]])

    res = ff.fetch_since(Session(), "01-05-2026", "31-10-2026")
    assert res["new_symbols"] == ["SMECO"]
    old = json.loads((tmp_path / "OLD.json").read_text())["filings"]
    assert [f["xbrl"] for f in old] == ["old-2026.xml", "old-2005.xml"]
    assert not (tmp_path / "NEWCO.json").exists()
