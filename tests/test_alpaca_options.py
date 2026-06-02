"""Tests for the Alpaca options execution layer (OCC symbols + order bodies).
Pure builders only — no live API calls."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import alpaca  # noqa: E402


# ── OCC symbols ──────────────────────────────────────────────────────────────

def test_occ_symbol_put():
    assert alpaca.occ_symbol("NVDA", "2026-01-16", "P", 100) == "NVDA260116P00100000"


def test_occ_symbol_call_and_yyyymmdd_input():
    assert alpaca.occ_symbol("SPY", "20260116", "call", 470) == "SPY260116C00470000"


def test_occ_symbol_fractional_strike():
    # $7.50 strike → 7500 milli → 00007500
    assert alpaca.occ_symbol("F", "2026-06-19", "P", 7.5) == "F260619P00007500"


def test_occ_symbol_rejects_bad_input():
    with pytest.raises(ValueError):
        alpaca.occ_symbol("X", "2026-1-16", "P", 100)   # malformed date
    with pytest.raises(ValueError):
        alpaca.occ_symbol("X", "2026-01-16", "P", 0)    # non-positive strike


def test_parse_occ_roundtrip():
    occ = alpaca.occ_symbol("NVDA", "2026-01-16", "P", 100)
    p = alpaca.parse_occ_symbol(occ)
    assert p == {"underlying": "NVDA", "expiry": "2026-01-16", "right": "P", "strike": 100.0}


# ── single-leg order body ────────────────────────────────────────────────────

def test_single_leg_csp_body():
    # Sell-to-open a put for $1.50 credit (limit).
    b = alpaca._option_order_body(
        "NVDA260116P00100000", qty=1, side="sell", limit_price=1.5,
        time_in_force="day", client_order_id="csp-NVDA-x")
    assert b["symbol"] == "NVDA260116P00100000"
    assert b["qty"] == "1" and b["side"] == "sell"
    assert b["type"] == "limit" and b["limit_price"] == "1.5"
    assert b["client_order_id"] == "csp-NVDA-x"


def test_single_leg_market_when_no_limit():
    b = alpaca._option_order_body("X260116C00100000", 2, "buy", None, "day", None)
    assert b["type"] == "market" and "limit_price" not in b


# ── multi-leg (mleg) order body ──────────────────────────────────────────────

def test_pcs_mleg_body():
    # Put credit spread: sell the 95 put, buy the 90 put, $1.50 net credit.
    legs = [
        {"symbol": alpaca.occ_symbol("X", "2026-01-16", "P", 95), "position_intent": "sell_to_open"},
        {"symbol": alpaca.occ_symbol("X", "2026-01-16", "P", 90), "position_intent": "buy_to_open"},
    ]
    b = alpaca._mleg_order_body(legs, qty=1, limit_price=1.5, time_in_force="day", client_order_id=None)
    assert b["order_class"] == "mleg" and b["type"] == "limit"
    assert b["limit_price"] == "1.5"
    assert len(b["legs"]) == 2
    short, long_ = b["legs"]
    assert short["position_intent"] == "sell_to_open" and short["side"] == "sell"
    assert long_["position_intent"] == "buy_to_open" and long_["side"] == "buy"
    assert short["ratio_qty"] == "1"


def test_mleg_iron_condor_four_legs():
    legs = [
        {"symbol": alpaca.occ_symbol("X", "2026-01-16", "P", 90), "position_intent": "sell_to_open"},
        {"symbol": alpaca.occ_symbol("X", "2026-01-16", "P", 85), "position_intent": "buy_to_open"},
        {"symbol": alpaca.occ_symbol("X", "2026-01-16", "C", 110), "position_intent": "sell_to_open"},
        {"symbol": alpaca.occ_symbol("X", "2026-01-16", "C", 115), "position_intent": "buy_to_open"},
    ]
    b = alpaca._mleg_order_body(legs, 1, 2.0, "day", None)
    assert len(b["legs"]) == 4


def test_mleg_rejects_bad_leg_count():
    one = [{"symbol": "X260116P00095000", "position_intent": "sell_to_open"}]
    with pytest.raises(ValueError):
        alpaca._mleg_order_body(one, 1, 1.0, "day", None)


def test_notional_order_body():
    b = alpaca._notional_order_body("MU", 900.0, "buy", "casaa-GROWTH-MU")
    assert b["symbol"] == "MU" and b["notional"] == "900.0"
    assert b["type"] == "market" and b["time_in_force"] == "day"
    assert "qty" not in b and b["client_order_id"] == "casaa-GROWTH-MU"


def test_mleg_limit_price_uses_absolute():
    legs = [
        {"symbol": "X260116P00095000", "position_intent": "sell_to_open"},
        {"symbol": "X260116P00090000", "position_intent": "buy_to_open"},
    ]
    b = alpaca._mleg_order_body(legs, 1, -1.5, "day", None)  # negative net → abs
    assert b["limit_price"] == "1.5"


# ── Shared-account attribution (financepwa_symbols) ──────────────────────────

def test_financepwa_symbols_captures_singles_and_mleg_legs():
    orders = [
        {"client_order_id": "casaa-2026-06-01-GROWTH-MRVL", "symbol": "MRVL"},
        {"client_order_id": "casaa-2026-06-01-CCS-TQQQ", "symbol": "",
         "legs": [{"symbol": "TQQQ260710C00090000"},
                  {"symbol": "TQQQ260710C00095000"}]},
    ]
    syms = alpaca.financepwa_symbols(orders)
    assert syms == {"MRVL", "TQQQ260710C00090000", "TQQQ260710C00095000"}


def test_financepwa_symbols_excludes_other_bots():
    """ZeroDTE's UUID-id SPY 0-DTE order and the untagged decision-queue order
    are NOT attributed to FinancePWA."""
    orders = [
        {"client_order_id": "casaa-2026-06-01-PCS-META", "symbol": "",
         "legs": [{"symbol": "META260710P00585000"}]},
        {"client_order_id": "68e855c1-4f27-4782-9b7d-4cb135a7abb4",
         "symbol": "SPY260601C00759000"},                 # ZeroDTE 0-DTE
        {"client_order_id": "9f0a-uuid-decision", "symbol": "LMT260626C00505000"},
    ]
    syms = alpaca.financepwa_symbols(orders)
    assert syms == {"META260710P00585000"}
    assert "SPY260601C00759000" not in syms
    assert "LMT260626C00505000" not in syms


def test_financepwa_symbols_empty_is_empty_set():
    assert alpaca.financepwa_symbols([]) == set()
    assert alpaca.financepwa_symbols(None) == set()


def test_parse_occ_returns_none_for_equity():
    """Plain equity tickers (fractional growth buys) aren't OCC symbols → None,
    not a crash."""
    assert alpaca.parse_occ_symbol("AMD") is None
    assert alpaca.parse_occ_symbol("AVGO") is None
    assert alpaca.parse_occ_symbol("") is None
    parsed = alpaca.parse_occ_symbol("IBM260717C00340000")
    assert parsed and parsed["underlying"] == "IBM" and parsed["right"] == "C"
    assert parsed["strike"] == 340.0 and parsed["expiry"] == "2026-07-17"
