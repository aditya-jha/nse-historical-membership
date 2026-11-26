"""Corporate-action parsing in nse_eod.build_market_cap, on known answers."""
from nse_eod.code.build_market_cap import _bc_row, share_factor


def test_share_factor():
    assert share_factor("BONUS 1:1") == 2.0            # 1 new for every 1 held
    assert share_factor("BONUS 1:2 /DIV-RS 0.50") == 1.5
    assert share_factor("BONUS 3:1") == 4.0
    assert share_factor("FVSPLT FRM RS 10 TO RE 1") == 10.0
    assert share_factor("FV SPLT FRM RS 5 TO RS 2") == 2.5
    assert share_factor("AGM/DIV-RS 21.1 PER SH") == 1.0
    assert share_factor("CAPITAL REDUCTION") is None    # ratio unknown: backfill stops


def test_bc_row_with_commas():
    row = "EQ,XYZ,X, Y AND Z LTD,26/07/2024, , ,26/07/2024, , ,DIV - RS 3, SPL DIV".split(",")
    assert _bc_row(row) == [("XYZ", "26/07/2024", "DIV - RS 3, SPL DIV")]
    assert _bc_row(["EQ", "ABC"]) == []
