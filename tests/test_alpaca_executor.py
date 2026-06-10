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


def test_stock_order_spec_is_notional_10pct_nlv():
    spec, reason = ex.stock_order_spec(_gpick(ticker="NVDA", trigger_price="120"), nlv=9000)
    # 10% of 9000 = $900 notional (fractional), not integer shares
    assert spec["kind"] == "equity" and spec["symbol"] == "NVDA"
    assert spec["notional"] == 900.0 and spec["side"] == "buy"
    assert "qty" not in spec


def test_stock_order_spec_buys_pricey_name_fractionally_no_skip():
    # A $1000 share is NOT skipped — notional buys ~0.9 sh of it.
    spec, reason = ex.stock_order_spec(_gpick(ticker="MU", trigger_price="1000"), nlv=9000)
    assert spec is not None and spec["notional"] == 900.0


def test_client_order_id_deterministic_and_bounded():
    p = _pick(strategy="CSP", ticker="NVDA")
    cid = ex.client_order_id("2026-05-30", p)
    assert cid == "casaa-2026-05-30-CSP-NVDA" and len(cid) <= 48
    assert ex.client_order_id("2026-05-30", p) == cid  # stable


# ── macro-tab parsing: latest by PARSED timestamp, fail-safe defaults ────────
# (2026-06-08/09 incident fixes: the executor read a non-existent
# spx_above_200sma column → always True, and defaulted VIX→16.0.)

def test_parse_audit_ts_formats():
    from datetime import datetime
    assert ex.parse_audit_ts("2026-06-09T180409") == datetime(2026, 6, 9, 18, 4, 9)
    assert ex.parse_audit_ts("2026-06-09 18:04:09") == datetime(2026, 6, 9, 18, 4, 9)
    assert ex.parse_audit_ts("2026-06-09") == datetime(2026, 6, 9)
    assert ex.parse_audit_ts("") is None and ex.parse_audit_ts(None) is None


def test_latest_by_parsed_ts_beats_physical_order():
    # The macro tab's proven shape: T180409 physically precedes T005009.
    rows = [
        {"date": "2026-06-09T180409", "vix": "21.81"},
        {"date": "2026-06-09T005009", "vix": "19.87"},
    ]
    assert ex.latest_by_parsed_ts(rows)["vix"] == "21.81"
    assert ex.latest_by_parsed_ts([]) is None


def test_merge_macro_rows_field_level_newest_nonblank():
    from datetime import datetime, timedelta

    def ts(hours_ago):
        return (datetime.now() - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H%M%S")

    rows = [
        {"date": ts(10), "vix": "20.50", "spx_above_200sma": "TRUE"},   # macro_grab row
        {"date": ts(1), "vix": "21.81"},                                # tracker row, newest, no flag
        {"date": ts(24 * 9), "vix": "33.0", "spx_above_200sma": "FALSE"},  # ancient — ignored
    ]
    m = ex.merge_macro_rows(rows)
    assert m["vix"] == "21.81"                  # newest VIX wins
    assert m["spx_above_200sma"] == "TRUE"      # flag survives from the older fresh row
    assert ex.merge_macro_rows([rows[2]]) == {}     # all-stale → {} → fully degraded
    vix, spx_ok, degraded = ex.macro_sizing_context(m)
    assert (vix, spx_ok, degraded) == (21.81, True, False)


def test_macro_sizing_context_full_data_not_degraded():
    vix, spx_ok, degraded = ex.macro_sizing_context(
        {"vix": "21.5", "spx_above_200sma": "TRUE"})
    assert (vix, spx_ok, degraded) == (21.5, True, False)
    vix, spx_ok, degraded = ex.macro_sizing_context(
        {"vix": "18.0", "spx_above_200sma": "FALSE"})
    assert (vix, spx_ok, degraded) == (18.0, False, False)   # known-bad halts via sizing


def test_macro_sizing_context_missing_vix_is_degraded():
    vix, spx_ok, degraded = ex.macro_sizing_context({"spx_above_200sma": "TRUE"})
    assert degraded is True and vix == 0.0


def test_macro_sizing_context_missing_spx_state_is_degraded():
    # Legacy macro rows have no spx_above_200sma column at all.
    vix, spx_ok, degraded = ex.macro_sizing_context({"vix": "21.5"})
    assert degraded is True and vix == 21.5
    # Present-but-blank cell (column added, grab failed) is also unknown.
    vix, spx_ok, degraded = ex.macro_sizing_context({"vix": "21.5", "spx_above_200sma": ""})
    assert degraded is True


def test_macro_sizing_context_empty_row_fully_degraded():
    vix, spx_ok, degraded = ex.macro_sizing_context({})
    assert degraded is True and vix == 0.0


def test_contracts_for_degraded_halves_count():
    pick = _pick(strategy="CSP", strike="100", underlying_last="112", premium="1.50")
    full = ex.contracts_for(pick, nlv=100_000, excess_liq=None, vix=12.0,
                            spx_above_200dma=True, degraded=False)
    assert full >= 2, "fixture must size ≥2 contracts for a meaningful halve"
    deg = ex.contracts_for(pick, nlv=100_000, excess_liq=None, vix=0.0,
                           spx_above_200dma=True, degraded=True)
    assert deg == int(full * 0.5)
    assert 0 < deg < full          # reduced, never full-size on missing data


# ── event blackout: NEW premium legs skipped inside 48h of high-impact ──────

def test_income_skip_reason_gex_and_blackout():
    ev = {"event": "FOMC", "_minutes_until": 120}
    assert ex.income_skip_reason("CSP", True, None) == "skipped:GEX SELL_CAUTION"
    assert ex.income_skip_reason("CSP", False, ev) == "skipped:EVENT_BLACKOUT"
    for strat in ("CC", "PCS", "CCS", "IC"):
        assert ex.income_skip_reason(strat, False, ev) == "skipped:EVENT_BLACKOUT"
    # GEX caution takes precedence when both fire (existing behavior preserved)
    assert ex.income_skip_reason("IC", True, ev) == "skipped:GEX SELL_CAUTION"
    # Debit strategies are NOT premium selling — unaffected by either gate
    assert ex.income_skip_reason("LONG_CALL", True, ev) is None
    assert ex.income_skip_reason("CSP", False, None) is None


def test_macrofeed_next_high_impact_drives_blackout_skip():
    """End-to-end through the real MacroFeed API on a synthetic calendar."""
    from datetime import datetime, timedelta, timezone
    from src.macro_blackouts import MacroFeed

    in_2h = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    in_5d = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")

    feed = MacroFeed(calendar=[
        {"impact": "low", "time": in_2h, "event": "Wholesale Inventories", "country": "US"},
        {"impact": "high", "time": in_2h, "event": "FOMC Rate Decision", "country": "US"},
    ])
    ev = feed.next_high_impact(within_hours=48)
    assert ev and ev["event"] == "FOMC Rate Decision"
    assert ex.income_skip_reason("PCS", False, ev) == "skipped:EVENT_BLACKOUT"

    # High-impact but outside the 48h window → no blackout, leg proceeds.
    far = MacroFeed(calendar=[
        {"impact": "high", "time": in_5d, "event": "CPI", "country": "US"}])
    assert far.next_high_impact(within_hours=48) is None
    assert ex.income_skip_reason("PCS", False, far.next_high_impact(within_hours=48)) is None
