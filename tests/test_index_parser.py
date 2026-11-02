"""Index press-release parser — section headers seen in 2026 PRs."""
from __future__ import annotations

import pytest

pytest.importorskip("pdfplumber")  # parse_press_release imports it at module level

from index_history.code.parse_press_release import _split_sections  # noqa: E402

# Shape of ind_prs15092026.pdf: a "B. Replacement in <index> index:" sub-heading
# after a numbered thematic section; it used to be swallowed by the section above.
TEXT = """A. Replacement on account of semi-annual review of thematic indices:
1) Nifty India Consumption
The following companies are being included:
1 Fortis Healthcare Ltd. FORTIS
B. Replacement in Nifty50 Value 20 index:
The following company is being excluded on account of exclusion from Nifty 50:
1 Wipro Ltd. WIPRO
C. Replacements on account of quarterly review of strategy and thematic indices:
1) Nifty Alpha 50
"""


def test_replacement_in_index_subheading_is_its_own_section():
    names = [n for n, _ in _split_sections(TEXT)]
    assert names == ["Nifty India Consumption", "Nifty50 Value 20", "Nifty Alpha 50"]


def test_symbol_rows_digit_leading_and_footnote_mark():
    from index_history.code.parse_press_release import EXCLUDE_MARKER, _extract_symbols_block
    body = """The following companies are being excluded:
Sr. No. Company Name Symbol
1 3M India Ltd. 3MINDIA
2 Vedanta Ltd.* VEDL
*Dummy symbols (DUMMYVEDL1, DUMMYVEDL2) representing the demerged entities shall be retained.
effective from March 31, 2014
"""
    assert _extract_symbols_block(body, EXCLUDE_MARKER) == ["3MINDIA", "VEDL"]
