"""Tests for src.paper_exits — the paper executor's autonomous exit discipline.

The safety property that matters most: plan_exits NEVER emits an intent for a
symbol we didn't open (not in casaa_syms), nor for a long / equity position.
"""
from __future__ import annotations

from datetime import date

from src.paper_exits import ExitIntent, exit_action, plan_exits

TODAY = date(2026, 6, 30)


# ── exit_action (pure decision) ──────────────────────────────────────────────
def test_take_profit_at_50pct():
    assert exit_action(0.50, dte=40) == "take_profit"
    assert exit_action(0.72, dte=40) == "take_profit"


def test_hold_below_target_with_time_left():
    assert exit_action(0.49, dte=40) is None
    assert exit_action(-1.5, dte=40) is None


def test_stop_at_2x_credit():
    assert exit_action(-2.0, dte=40) == "stop"
    assert exit_action(-3.1, dte=40) == "stop"


def test_dte_close_is_the_fallback():
    assert exit_action(0.20, dte=21) == "dte_close"
    assert exit_action(0.20, dte=5) == "dte_close"
    assert exit_action(0.20, dte=22) is None


def test_take_profit_wins_over_dte():
    assert exit_action(0.60, dte=3) == "take_profit"


def test_stop_wins_over_dte():
    assert exit_action(-2.5, dte=3) == "stop"


def test_missing_dte_only_acts_on_price():
    assert exit_action(0.20, dte=None) is None
    assert exit_action(0.55, dte=None) == "take_profit"


# ── plan_exits (filtering + safety) ──────────────────────────────────────────
def _pos(symbol, qty, avg_entry, current):
    return {"symbol": symbol, "qty": str(qty),
            "avg_entry_price": str(avg_entry), "current_price": str(current)}


NVDA_PUT = "NVDA260821P00100000"      # exp 2026-08-21 → ~52 DTE from TODAY
NVDA_PUT_SOON = "NVDA260710P00100000"  # exp 2026-07-10 → 10 DTE from TODAY


def test_take_profit_intent_for_our_short_leg():
    pos = [_pos(NVDA_PUT, -2, 1.50, 0.70)]  # captured (1.50-0.70)/1.50 = 0.533
    out = plan_exits(pos, {NVDA_PUT}, today=TODAY)
    assert out == [ExitIntent(NVDA_PUT, 2, "take_profit", 0.5333, 52)]


def test_never_touches_a_symbol_we_did_not_open():
    # A profitable short we could close — but it is NOT in casaa_syms.
    pos = [_pos("SPY260630P00500000", -1, 2.00, 0.10)]
    assert plan_exits(pos, casaa_syms=set(), today=TODAY) == []


def test_skips_long_positions():
    pos = [_pos(NVDA_PUT, +1, 1.50, 3.00)]  # long option, not a short we manage
    assert plan_exits(pos, {NVDA_PUT}, today=TODAY) == []


def test_skips_equities():
    pos = [{"symbol": "AMD", "qty": "-10", "avg_entry_price": "100", "current_price": "40"}]
    assert plan_exits(pos, {"AMD"}, today=TODAY) == []


def test_dte_close_when_short_dated_and_not_at_target():
    pos = [_pos(NVDA_PUT_SOON, -1, 1.50, 1.20)]  # captured 0.20, dte 10
    out = plan_exits(pos, {NVDA_PUT_SOON}, today=TODAY)
    assert len(out) == 1 and out[0].action == "dte_close" and out[0].dte == 10


def test_stop_intent_when_short_blew_out():
    pos = [_pos(NVDA_PUT, -1, 1.50, 4.60)]  # captured (1.5-4.6)/1.5 = -2.07
    out = plan_exits(pos, {NVDA_PUT}, today=TODAY)
    assert len(out) == 1 and out[0].action == "stop"


def test_holding_winner_below_target_emits_nothing():
    pos = [_pos(NVDA_PUT, -1, 1.50, 0.90)]  # captured 0.40, 52 DTE → hold
    assert plan_exits(pos, {NVDA_PUT}, today=TODAY) == []
