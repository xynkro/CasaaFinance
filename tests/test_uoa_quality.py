"""Tests for src.uoa_quality — separating informed flow from noise.

Anchored on the real 2026-08-24 digest, where 4 of the 10 loudest alerts were
deep-ITM parity contracts and 3 ranked loudest only because open interest was
1-4. Those exact rows are regression cases here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.uoa_quality import (
    adverse_flow, aggressor_side, classify_open_close, directional_read, extrinsic_pct,
    extrinsic_value, is_near_parity, persistence, quality_score, safe_vol_oi,
)


# ── extrinsic value: the parity detector ────────────────────────────────────
def test_arm_deep_itm_put_is_parity():
    """ARM $430 put, premium $193.32, spot $237.53 → $0.85 of time value."""
    assert extrinsic_value("PUT", 430, 237.53, 193.32) == pytest.approx(0.85, abs=0.01)
    assert extrinsic_pct("PUT", 430, 237.53, 193.32) < 1.0
    assert is_near_parity("PUT", 430, 237.53, 193.32)


def test_amzn_deep_itm_call_is_parity():
    """AMZN $220 call, premium $42.08, spot $261.76 → $0.32 of time value."""
    assert extrinsic_value("CALL", 220, 261.76, 42.08) == pytest.approx(0.32, abs=0.01)
    assert is_near_parity("CALL", 220, 261.76, 42.08)


def test_nvda_atm_call_is_all_time_value():
    """NVDA $210 call, premium $8.12, spot $209.19 → 100% extrinsic."""
    assert extrinsic_pct("CALL", 210, 209.19, 8.12) == pytest.approx(100.0)
    assert not is_near_parity("CALL", 210, 209.19, 8.12)


def test_tsla_partial_itm_is_not_parity():
    """TSLA $340 call, $20.20, spot $357.91 → $2.29 (11%) — real optionality."""
    assert extrinsic_pct("CALL", 340, 357.91, 20.20) == pytest.approx(11.34, abs=0.1)
    assert not is_near_parity("CALL", 340, 357.91, 20.20)


def test_zero_premium_is_safe():
    assert extrinsic_pct("CALL", 100, 110, 0) == 0.0
    assert is_near_parity("CALL", 100, 110, 0)


# ── Vol/OI floor: the division-artifact guard ───────────────────────────────
def test_vol_oi_suppressed_on_tiny_open_interest():
    """AMZN 620 contracts vs OI=1 gave a meaningless 620x."""
    assert safe_vol_oi(620, 1) is None
    assert safe_vol_oi(507, 1) is None      # ARM
    assert safe_vol_oi(700, 4) is None      # SPY


def test_vol_oi_computed_when_oi_is_meaningful():
    assert safe_vol_oi(9865, 797) == pytest.approx(12.38, abs=0.01)   # NVDA
    assert safe_vol_oi(10582, 10440) == pytest.approx(1.01, abs=0.01)  # AVGO


# ── aggressor side: the long/short question ─────────────────────────────────
def test_print_at_ask_is_buyer_initiated():
    assert aggressor_side(last=5.00, bid=4.50, ask=5.00) == "BUY_INITIATED"


def test_print_at_bid_is_seller_initiated():
    assert aggressor_side(last=4.50, bid=4.50, ask=5.00) == "SELL_INITIATED"


def test_print_at_mid_is_mid():
    assert aggressor_side(last=4.75, bid=4.50, ask=5.00) == "MID"


def test_bad_quotes_return_unknown_never_a_guess():
    assert aggressor_side(0, 4.5, 5.0) == "UNKNOWN"
    assert aggressor_side(4.7, 0, 5.0) == "UNKNOWN"
    assert aggressor_side(4.7, 5.0, 4.5) == "UNKNOWN"   # crossed
    assert aggressor_side(4.7, 4.7, 4.7) == "UNKNOWN"   # zero span


# ── directional read: what he actually asked for ────────────────────────────
def test_the_four_structures():
    assert directional_read("CALL", "BUY_INITIATED") == ("LONG_CALL", "BULLISH")
    assert directional_read("CALL", "SELL_INITIATED") == ("SHORT_CALL", "BEARISH")
    assert directional_read("PUT", "BUY_INITIATED") == ("LONG_PUT", "BEARISH")
    assert directional_read("PUT", "SELL_INITIATED") == ("SHORT_PUT", "BULLISH")


def test_same_contract_opposite_conclusion():
    """The whole point: one row, two opposite meanings by aggressor."""
    bought = directional_read("PUT", "BUY_INITIATED")
    sold = directional_read("PUT", "SELL_INITIATED")
    assert bought[1] == "BEARISH" and sold[1] == "BULLISH"


def test_unreadable_aggressor_yields_no_view():
    assert directional_read("CALL", "UNKNOWN") == ("UNCLEAR", "UNKNOWN")
    assert directional_read("PUT", "MID") == ("UNCLEAR", "UNKNOWN")


# ── opening vs closing ──────────────────────────────────────────────────────
def test_oi_jump_means_opening():
    assert classify_open_close(1000, 500, 1500) == "OPENING"


def test_oi_collapse_means_closing():
    assert classify_open_close(1000, 1500, 500) == "CLOSING"


def test_flat_oi_is_mixed_not_opening():
    assert classify_open_close(1000, 500, 520) == "MIXED"


def test_without_next_day_oi_we_say_unknown():
    assert classify_open_close(1000, 500, None) == "UNKNOWN"


# ── persistence ─────────────────────────────────────────────────────────────
def test_persistence_counts_distinct_days_same_bias():
    alerts = [
        {"date": "2026-08-22", "ticker": "NVDA", "bias": "BULLISH"},
        {"date": "2026-08-23", "ticker": "NVDA", "bias": "BULLISH"},
        {"date": "2026-08-23", "ticker": "NVDA", "bias": "BULLISH"},   # same day
        {"date": "2026-08-24", "ticker": "NVDA", "bias": "BEARISH"},   # other bias
        {"date": "2026-08-24", "ticker": "AMD", "bias": "BULLISH"},    # other name
    ]
    assert persistence(alerts, "NVDA", "BULLISH") == 2
    assert persistence(alerts, "NVDA", "BEARISH") == 1
    assert persistence(alerts, "TSLA", "BULLISH") == 0


# ── quality score ───────────────────────────────────────────────────────────
def test_parity_trade_scores_near_zero_despite_huge_notional():
    """ARM: $9.8M notional but 0.4% extrinsic, OI=1, unreadable → junk."""
    s = quality_score(extrinsic_pct_val=0.4, vol_oi=None,
                      aggressor="UNKNOWN", notional=9.8e6, persist_days=1)
    assert s <= 20


def test_real_option_bet_with_readable_side_scores_high():
    """NVDA ATM call: 100% extrinsic, trustworthy Vol/OI, buyer-initiated."""
    s = quality_score(extrinsic_pct_val=100.0, vol_oi=12.4,
                      aggressor="BUY_INITIATED", notional=8.0e6, persist_days=3)
    assert s >= 80


def test_score_ranks_real_above_parity():
    junk = quality_score(extrinsic_pct_val=0.4, vol_oi=None,
                         aggressor="UNKNOWN", notional=9.8e6, persist_days=1)
    real = quality_score(extrinsic_pct_val=100.0, vol_oi=12.4,
                         aggressor="BUY_INITIATED", notional=8.0e6, persist_days=3)
    assert real > junk * 3


def test_score_is_bounded():
    assert 0 <= quality_score(extrinsic_pct_val=999, vol_oi=999,
                              aggressor="BUY_INITIATED", notional=1e12,
                              persist_days=99) <= 100


# ── adverse_flow: UOA as a risk filter on the wheel ─────────────────────────
def _a(date, ticker, structure, quality=60, volume=1000, notional=2e6):
    return {"date": date, "ticker": ticker, "structure": structure,
            "quality": quality, "volume": volume, "notional": notional}


def test_csp_warned_when_someone_is_buying_puts():
    """Selling a put = short downside. Buy-initiated puts = they want that downside."""
    alerts = [_a("2026-08-24", "NVDA", "LONG_PUT")]
    w = adverse_flow("CSP", "NVDA", alerts)
    assert w and w["level"] == "WARN" and w["structure"] == "LONG_PUT"
    assert "downside" in w["reason"]


def test_repeat_days_escalate_to_alert():
    alerts = [_a("2026-08-22", "NVDA", "LONG_PUT"), _a("2026-08-24", "NVDA", "LONG_PUT")]
    w = adverse_flow("CSP", "NVDA", alerts)
    assert w["level"] == "ALERT" and w["days"] == 2


def test_cc_warned_on_call_buying_not_put_buying():
    """Covered call = short upside; only call buying conflicts."""
    assert adverse_flow("CC", "NVDA", [_a("2026-08-24", "NVDA", "LONG_CALL")])
    assert adverse_flow("CC", "NVDA", [_a("2026-08-24", "NVDA", "LONG_PUT")]) is None


def test_csp_not_warned_by_call_buying():
    assert adverse_flow("CSP", "NVDA", [_a("2026-08-24", "NVDA", "LONG_CALL")]) is None


def test_someone_selling_puts_is_not_adverse_to_a_csp():
    """SHORT_PUT flow agrees with our position — no conflict."""
    assert adverse_flow("CSP", "NVDA", [_a("2026-08-24", "NVDA", "SHORT_PUT")]) is None


def test_harvest_csp_alias_is_covered():
    assert adverse_flow("HARVEST_CSP", "NVDA", [_a("2026-08-24", "NVDA", "LONG_PUT")])


def test_low_quality_flow_is_ignored():
    assert adverse_flow("CSP", "NVDA", [_a("2026-08-24", "NVDA", "LONG_PUT", quality=10)]) is None


def test_other_tickers_do_not_warn():
    assert adverse_flow("CSP", "AMD", [_a("2026-08-24", "NVDA", "LONG_PUT")]) is None


def test_non_premium_strategy_never_warns():
    assert adverse_flow("LONG_CALL", "NVDA", [_a("2026-08-24", "NVDA", "LONG_PUT")]) is None


def test_lookback_window_is_respected():
    alerts = [_a("2026-07-01", "NVDA", "LONG_PUT")]
    assert adverse_flow("CSP", "NVDA", alerts, recent_days=["2026-08-24"]) is None
    assert adverse_flow("CSP", "NVDA", alerts, recent_days=["2026-07-01"])


def test_aggregates_contracts_and_notional():
    alerts = [_a("2026-08-23", "NVDA", "LONG_PUT", volume=1000, notional=2e6),
              _a("2026-08-24", "NVDA", "LONG_PUT", volume=1500, notional=3e6)]
    w = adverse_flow("CSP", "NVDA", alerts)
    assert w["contracts"] == 2500 and w["notional"] == 5e6
