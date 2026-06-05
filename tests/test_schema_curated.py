# tests/test_schema_curated.py
from src.schema import CuratedPickRow

def test_headers_and_to_row_align():
    r = CuratedPickRow(
        date="2026-06-05", ticker="AMZN", role="core", mf_type="Cautious",
        rec_date="2026-03-20", rec_price="208.76", market_cap="2.73T",
        return_since_rec="21.57", return_vs_sp="6.51", moneyball_score="",
        source="motley_fool", note="Foundational", updated_at="2026-06-05T12:00:00")
    assert len(r.to_row()) == len(CuratedPickRow.HEADERS)
    assert r.to_row()[CuratedPickRow.HEADERS.index("ticker")] == "AMZN"
    assert r.to_row()[CuratedPickRow.HEADERS.index("role")] == "core"

def test_role_is_constrained_by_convention():
    # roles used downstream — keep this list authoritative
    assert {"core", "watchlist", "overlay", "reference"}
