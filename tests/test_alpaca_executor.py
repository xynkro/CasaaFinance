"""Tests for the Alpaca paper executor's pure logic (selection / parsing /
pick→order mapping). No live API."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "alpaca_paper_execute",
    Path(__file__).resolve().parent.parent / "scripts" / "alpaca_paper_execute.py")
ex = importlib.util.module_from_spec(_spec)
sys.modules["alpaca_paper_execute"] = ex
_spec.loader.exec_module(ex)


def _pick(**kw):
    base = {"date": "2026-05-30", "ticker": "NVDA", "strategy": "CSP",
            "strike": "100", "expiry": "20260116", "premium": "1.50",
            "composite_score": "60", "notes": "", "underlying_last": "112",
            "cash_required": "10000"}
    base.update(kw)
    return base


# ── parsing / normalization ──────────────────────────────────────────────────

def test_norm_expiry():
    assert ex.norm_expiry("20260116") == "2026-01-16"
    assert ex.norm_expiry("2026-01-16") == "2026-01-16"


def test_parse_leg_strikes_ic_with_sizing_tag():
    notes = "SP:90/LP:85/SC:110/LC:115 W:$5 | size C:1x S:3x"
    assert ex.parse_leg_strikes(notes) == {"SP": 90, "LP": 85, "SC": 110, "LC": 115}


def test_parse_leg_strikes_pcs():
    assert ex.parse_leg_strikes("SP:95/LP:90 W:$5") == {"SP": 95, "LP": 90}


# ── selection ────────────────────────────────────────────────────────────────

def test_select_matches_audit_timestamped_dates():
    # scan_results stores dates with an audit suffix ("2026-05-30T103045").
    # The executor's today is a clean ISO date — must still match.
    picks = [_pick(strategy="CSP", ticker="Z", date="2026-05-30T103045", composite_score="80")]
    top = ex.select_top_per_strategy(picks, "2026-05-30")
    assert len(top) == 1 and top[0]["ticker"] == "Z"


def test_select_top_per_strategy_keeps_best_and_folds_harvest():
    picks = [
        _pick(strategy="CSP", ticker="A", composite_score="40"),
        _pick(strategy="CSP", ticker="B", composite_score="70"),     # best CSP
        _pick(strategy="HARVEST_CSP", ticker="C", composite_score="55"),  # folds to CSP (<70)
        _pick(strategy="CC", ticker="D", composite_score="50"),
        _pick(strategy="PCS", ticker="E", composite_score="30", date="2026-05-29"),  # wrong day
    ]
    top = ex.select_top_per_strategy(picks, "2026-05-30")
    by = {p["strategy"] if p["strategy"] != "HARVEST_CSP" else "CSP": p["ticker"] for p in top}
    assert by.get("CSP") == "B"          # highest composite across CSP + HARVEST_CSP
    assert by.get("CC") == "D"
    assert "PCS" not in by               # filtered out (different date)


# ── pick → order mapping ─────────────────────────────────────────────────────

def test_map_csp_single_leg():
    spec, reason = ex.pick_to_order(_pick(strategy="CSP", strike="100", premium="1.50"))
    assert spec["kind"] == "single" and spec["side"] == "sell"
    assert spec["occ"] == "NVDA260116P00100000" and spec["limit_price"] == 1.5


def test_map_long_call_buy():
    spec, _ = ex.pick_to_order(_pick(strategy="LONG_CALL", right="C", strike="120"))
    assert spec["kind"] == "single" and spec["side"] == "buy"
    assert spec["occ"].endswith("C00120000")


def test_map_pcs_mleg_two_legs():
    spec, _ = ex.pick_to_order(_pick(strategy="PCS", notes="SP:95/LP:90 W:$5", premium="1.50"))
    assert spec["kind"] == "mleg" and len(spec["legs"]) == 2
    assert spec["legs"][0]["position_intent"] == "sell_to_open"   # short put
    assert spec["legs"][1]["position_intent"] == "buy_to_open"    # long put
    assert spec["legs"][0]["symbol"].endswith("P00095000")


def test_map_ic_mleg_four_legs():
    spec, _ = ex.pick_to_order(_pick(strategy="IC", notes="SP:90/LP:85/SC:110/LC:115 W:$5"))
    assert spec["kind"] == "mleg" and len(spec["legs"]) == 4
    intents = [l["position_intent"] for l in spec["legs"]]
    assert intents == ["sell_to_open", "buy_to_open", "sell_to_open", "buy_to_open"]


def test_map_pmcc_skipped():
    spec, reason = ex.pick_to_order(_pick(strategy="PMCC", notes="LEAPS:90C/Short:110C"))
    assert spec is None and "not yet supported" in reason


def test_map_unparseable_spread_skipped():
    spec, reason = ex.pick_to_order(_pick(strategy="PCS", notes="no legs here"))
    assert spec is None and "unparseable" in reason


def _gpick(**kw):
    base = {"date": "2026-05-30", "source": "momentum", "ticker": "NVDA",
            "score": "70", "trigger_price": "120"}
    base.update(kw)
    return base


def test_select_growth_picks_filters_and_ranks():
    rows = [
        _gpick(ticker="A", score="60"),
        _gpick(ticker="B", score="90"),
        _gpick(ticker="C", score="80", source="vcp"),       # wrong source
        _gpick(ticker="D", score="95", date="2026-05-29"),  # wrong day
    ]
    out = ex.select_growth_picks(rows, "2026-05-30", top_n=5)
    assert [r["ticker"] for r in out] == ["B", "A"]          # momentum + today, score desc


def test_stock_order_spec_sizes_to_10pct_nlv():
    spec, reason = ex.stock_order_spec(_gpick(ticker="NVDA", trigger_price="120"), nlv=9000)
    # 10% of 9000 = $900; $900 // $120 = 7 shares
    assert spec["kind"] == "equity" and spec["symbol"] == "NVDA" and spec["qty"] == 7
    assert spec["side"] == "buy" and spec["limit_price"] == 120.0


def test_stock_order_spec_skips_when_one_share_exceeds_budget():
    spec, reason = ex.stock_order_spec(_gpick(ticker="X", trigger_price="1000"), nlv=9000)
    assert spec is None and "budget" in reason


def test_client_order_id_deterministic_and_bounded():
    p = _pick(strategy="CSP", ticker="NVDA")
    cid = ex.client_order_id("2026-05-30", p)
    assert cid == "casaa-2026-05-30-CSP-NVDA" and len(cid) <= 48
    assert ex.client_order_id("2026-05-30", p) == cid  # stable
