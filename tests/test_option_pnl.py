"""Tests for src/option_pnl.py — the single-source option P&L settlement model.

Covers both entry points:
  • settle_*  — REAL strike + premium (used by the live signal_feedback loop)
  • *_pnl_pct — BSM-synthesized strike + premium (used by the backtest)

The settlement invariant under test: a profitable trade is POSITIVE and a
losing trade is NEGATIVE, premium included, with the payoff capped at the strike.
"""
from __future__ import annotations

import math

import pytest

from src.option_pnl import (
    _RT_COST, _bsm_put,
    csp_settle_pct, cc_settle_pct, csp_pnl_pct, cc_pnl_pct,
)


# ── CSP settlement (real strike + premium) ───────────────────────────────────

class TestCspSettle:
    def test_otm_keeps_full_premium(self):
        """Put expires OTM (exit >= strike) → keep the credit minus friction."""
        pnl = csp_settle_pct(strike=190, premium=3.50, exit_price=195)
        assert pnl == pytest.approx((3.50 - _RT_COST) / 190 * 100)
        assert pnl > 0

    def test_at_strike_still_keeps_premium(self):
        """Pinned exactly at the strike is OTM for a put — the premium is NOT
        thrown away (the old price-distance scratch band wrongly logged 0)."""
        pnl = csp_settle_pct(strike=190, premium=3.50, exit_price=190)
        assert pnl == pytest.approx((3.50 - _RT_COST) / 190 * 100)
        assert pnl > 0

    def test_itm_nets_assignment_loss(self):
        """Assigned: premium minus (strike - exit). Deep enough → negative."""
        pnl = csp_settle_pct(strike=190, premium=3.50, exit_price=180)
        assert pnl == pytest.approx((3.50 - (190 - 180) - _RT_COST) / 190 * 100)
        assert pnl < 0

    def test_shallow_assignment_premium_still_wins(self):
        """Assigned but the credit covers the small loss → still positive."""
        pnl = csp_settle_pct(strike=190, premium=3.50, exit_price=188)
        # 3.50 - 2.00 - 0.02 = +1.48 / 190
        assert pnl > 0

    def test_pct_base_is_strike(self):
        """% is of the strike, so a smaller strike yields a larger %."""
        big = csp_settle_pct(strike=50, premium=2.0, exit_price=60)
        small = csp_settle_pct(strike=200, premium=2.0, exit_price=210)
        assert big > small

    def test_zero_strike_guard(self):
        assert csp_settle_pct(strike=0, premium=2.0, exit_price=10) == 0.0


# ── CC settlement (real strike + premium) — the two inversions the proxy made ─

class TestCcSettle:
    def test_called_away_above_cost_is_a_profit(self):
        """OTM call assigned above cost = MAX profit (capped gain + premium),
        NOT a loss. The old proxy logged a positive return but labelled it LOSS."""
        pnl = cc_settle_pct(entry=195, strike=200, premium=5.0, exit_price=210)
        # capped at strike 200: (200-195) + 5 - 0.02 = 9.98 / 195
        assert pnl == pytest.approx((200 - 195 + 5.0 - _RT_COST) / 195 * 100)
        assert pnl > 0

    def test_payoff_capped_at_strike(self):
        """Above the strike the gain stops climbing — capping must bind."""
        capped = cc_settle_pct(entry=195, strike=200, premium=5.0, exit_price=210)
        uncapped = (210 - 195 + 5.0 - _RT_COST) / 195 * 100
        assert capped < uncapped

    def test_sideways_down_win_premium_covers_drop(self):
        """Stock fell but stayed below strike and the premium covers it →
        POSITIVE. The old proxy logged the raw (negative) stock return here."""
        pnl = cc_settle_pct(entry=195, strike=200, premium=5.0, exit_price=192)
        assert pnl == pytest.approx((192 - 195 + 5.0 - _RT_COST) / 195 * 100)
        assert pnl > 0

    def test_drop_exceeds_premium_is_a_real_loss(self):
        """Down more than the premium → NEGATIVE, even though the call expired
        worthless and the shares were kept. Label must follow P&L, not assignment."""
        pnl = cc_settle_pct(entry=195, strike=200, premium=5.0, exit_price=180)
        assert pnl == pytest.approx((180 - 195 + 5.0 - _RT_COST) / 195 * 100)
        assert pnl < 0

    def test_zero_entry_guard(self):
        assert cc_settle_pct(entry=0, strike=10, premium=1.0, exit_price=9) == 0.0


# ── Synthesized path (backtest) — refactor preserved the exact formula ───────

class TestSynthesizedPnl:
    def test_csp_pnl_pct_matches_legacy_inline_formula(self):
        """Regression pin: csp_pnl_pct must equal the original pre-refactor inline
        arithmetic from backtest_scoring, so the backtest's numbers are unchanged."""
        entry, exit_price, sigma, hold = 100.0, 105.0, 0.4, 35
        T = max(hold / 365.0, 1e-6)
        s = sigma if sigma > 0 else 0.4
        otm = 0.67 * s * math.sqrt(T)
        strike = entry * (1 - otm)
        prem = _bsm_put(entry, strike, T, s)
        expected = ((prem - _RT_COST) if exit_price >= strike
                    else (prem - (strike - exit_price) - _RT_COST)) / strike * 100
        assert csp_pnl_pct(entry, exit_price, sigma, hold) == pytest.approx(expected)

    def test_cc_pnl_pct_caps_and_nets_premium(self):
        """A big up-move is capped; result stays a sane single/double-digit %."""
        up = cc_pnl_pct(entry=100, exit_price=130, sigma=0.4, hold_days=35)
        down = cc_pnl_pct(entry=100, exit_price=80, sigma=0.4, hold_days=35)
        assert up > 0 and up < 30        # capped well below the raw +30%
        assert down < 0                  # drop exceeds the synthesized premium

    def test_csp_pnl_pct_positive_when_otm(self):
        assert csp_pnl_pct(entry=100, exit_price=110, sigma=0.4, hold_days=35) > 0
