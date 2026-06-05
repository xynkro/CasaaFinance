# tests/test_daily_plan_mf.py
from scripts.build_daily_plan import _mf_core_candidates, MF_CORE_CAP

CURATED = [
    {"date":"2026-06-05","ticker":"AMZN","role":"core","source":"motley_fool"},
    {"date":"2026-06-05","ticker":"INTC","role":"core","source":"motley_fool"},
    {"date":"2026-06-05","ticker":"DDOG","role":"core","source":"motley_fool"},
    {"date":"2026-06-05","ticker":"FIX","role":"core","source":"motley_fool"},
    {"date":"2026-06-05","ticker":"GLW","role":"watchlist","source":"motley_fool"},  # not core
]

def test_caps_number_of_names():
    rows = _mf_core_candidates(CURATED, "2026-06-05", nlv=10000.0)
    assert len(rows) <= MF_CORE_CAP

def test_equal_weight_and_tagged():
    rows = _mf_core_candidates(CURATED, "2026-06-05", nlv=10000.0)
    notionals = {r["notional"] for r in rows}
    assert len(notionals) == 1                      # equal-weight
    assert all(r["source"] == "motley_fool" for r in rows)
    assert all(r["leg"] == "mf_core" for r in rows)

def test_ignores_non_core_and_other_days():
    rows = _mf_core_candidates(CURATED, "2026-06-05", nlv=10000.0)
    tickers = {r["ticker"] for r in rows}
    assert "GLW" not in tickers
    assert _mf_core_candidates(CURATED, "2026-06-04", nlv=10000.0) == []
