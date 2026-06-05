# tests/test_daily_plan_mf.py
from scripts.build_daily_plan import _mf_core_candidates, MF_CORE_CAP, mf_core_alerts

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


def test_core_add_detects_new_name():
    prev = [{"date": "2026-06-04", "leg": "mf_core", "ticker": "AMZN"}]
    new = [{"leg": "mf_core", "ticker": "AMZN"}, {"leg": "mf_core", "ticker": "INTC"},
           {"leg": "core", "ticker": "QQQ"}]
    assert mf_core_alerts(prev, new) == ["INTC"]   # only the newly-added MF name

def test_core_add_idempotent_same_day():
    # prev already holds today's mf_core (an earlier run today) → no repeat ping
    prev = [{"date": "2026-06-05", "leg": "mf_core", "ticker": "AMZN"}]
    new = [{"leg": "mf_core", "ticker": "AMZN"}]
    assert mf_core_alerts(prev, new) == []

def test_core_add_empty_prev_pings_all():
    new = [{"leg": "mf_core", "ticker": "AMZN"}, {"leg": "growth", "ticker": "NVDA"}]
    assert mf_core_alerts([], new) == ["AMZN"]
