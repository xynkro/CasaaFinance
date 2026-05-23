"""Tests for term structure analysis and signal."""
from __future__ import annotations

import pytest


def test_ts_slope_contango():
    """Contango (long IV > short IV) should produce positive slope."""
    from src.term_structure import compute_ts_slope
    slope = compute_ts_slope(iv_short=0.25, iv_long=0.30, dte_short=30, dte_long=60)
    assert slope > 0


def test_ts_slope_backwardation():
    """Backwardation (short IV > long IV) should produce negative slope."""
    from src.term_structure import compute_ts_slope
    slope = compute_ts_slope(iv_short=0.35, iv_long=0.25, dte_short=30, dte_long=60)
    assert slope < 0


def test_ts_slope_flat():
    """Equal IV across maturities should produce ~0 slope."""
    from src.term_structure import compute_ts_slope
    slope = compute_ts_slope(iv_short=0.30, iv_long=0.30, dte_short=30, dte_long=60)
    assert slope == 0.0


def test_ts_slope_invalid_inputs():
    """Invalid inputs should return 0."""
    from src.term_structure import compute_ts_slope
    assert compute_ts_slope(0, 0.30, 30, 60) == 0.0
    assert compute_ts_slope(0.25, 0.30, 0, 60) == 0.0
    assert compute_ts_slope(0.25, 0.30, 60, 30) == 0.0  # long DTE < short DTE


def test_rank_expiries_basic():
    """rank_expiries should sort by VRP-per-day descending."""
    from src.term_structure import rank_expiries
    expiries = [
        {"expiry": "2026-06-20", "dte": 28, "atm_iv": 0.35, "credit": 1.50},
        {"expiry": "2026-07-18", "dte": 56, "atm_iv": 0.28, "credit": 2.10},
    ]
    ranked = rank_expiries(expiries, rv_forecast=0.25)
    assert len(ranked) == 2
    assert "vrp_per_day" in ranked[0]
    # Shorter DTE with higher IV should have more VRP per day
    assert ranked[0]["dte"] == 28


def test_rank_expiries_skips_invalid():
    """Expiries with zero IV or DTE should be skipped."""
    from src.term_structure import rank_expiries
    expiries = [
        {"expiry": "2026-06-20", "dte": 28, "atm_iv": 0.35},
        {"expiry": "2026-07-18", "dte": 0, "atm_iv": 0.28},   # zero DTE
        {"expiry": "2026-08-15", "dte": 84, "atm_iv": 0.0},   # zero IV
    ]
    ranked = rank_expiries(expiries, rv_forecast=0.25)
    assert len(ranked) == 1
    assert ranked[0]["dte"] == 28


def test_term_structure_signal_contango():
    """Positive slope (contango) should produce positive signal."""
    from src.technical_score import _sig_term_structure
    assert _sig_term_structure(0.3) > 0


def test_term_structure_signal_backwardation():
    """Negative slope should produce negative signal."""
    from src.technical_score import _sig_term_structure
    assert _sig_term_structure(-0.3) < 0


def test_term_structure_signal_clamp():
    """Extreme values should be clamped to [-1, +1]."""
    from src.technical_score import _sig_term_structure
    assert _sig_term_structure(10.0) == 1.0
    assert _sig_term_structure(-10.0) == -1.0


def test_term_structure_in_strategy_weights():
    """term_structure should be in all strategy weights."""
    from src.technical_score import STRATEGY_WEIGHTS
    for strat, weights in STRATEGY_WEIGHTS.items():
        assert "term_structure" in weights, f"Missing term_structure weight for {strat}"
    assert STRATEGY_WEIGHTS["CSP"]["term_structure"] >= 3


def test_compute_signals_includes_term_structure():
    """compute_signals should include term_structure key."""
    from src.technical_score import compute_signals
    signals = compute_signals({"close": 100, "rsi_14": 50})
    assert "term_structure" in signals
