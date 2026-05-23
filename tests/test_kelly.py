"""Tests for fractional Kelly sizing recalibration."""
from __future__ import annotations

import pytest


def test_kelly_fraction_is_10_percent():
    """KELLY_FRACTION should be 0.10 (10% of full Kelly), not 0.50."""
    from src.option_scanner import KELLY_FRACTION
    assert KELLY_FRACTION == 0.10


def test_fractional_kelly_size_basic():
    """Fractional Kelly should produce smaller sizes than half-Kelly."""
    from src.option_scanner import _fractional_kelly_size
    # 60% win rate, avg_win $200, avg_loss $300, $100k account
    size = _fractional_kelly_size(0.60, 200, 300, 100_000)
    # Full Kelly f = (0.60*200 - 0.40*300)/200 = (120-120)/200 = 0 → edge is zero
    # So size should be 0 (no edge to size on)
    assert size == 0.0


def test_fractional_kelly_with_edge():
    """With positive edge, size should be 10% of full Kelly, capped at MAX_POSITION_PCT."""
    from src.option_scanner import _fractional_kelly_size, KELLY_FRACTION, MAX_POSITION_PCT
    # 70% win rate, avg_win $200, avg_loss $200, $100k account
    # Full Kelly f = (0.70*200 - 0.30*200)/200 = (140-60)/200 = 0.40
    # 10% of Kelly = 0.40 * 0.10 = 0.04 = 4% of account = $4,000
    size = _fractional_kelly_size(0.70, 200, 200, 100_000)
    assert 3500 < size < 5000  # ~$4,000


def test_fractional_kelly_cap():
    """Should never exceed MAX_POSITION_PCT regardless of edge."""
    from src.option_scanner import _fractional_kelly_size, MAX_POSITION_PCT
    # Extreme edge: 95% win rate
    size = _fractional_kelly_size(0.95, 500, 100, 100_000)
    assert size <= 100_000 * MAX_POSITION_PCT


def test_backward_compat_alias():
    """_half_kelly_size should still work (alias to _fractional_kelly_size)."""
    from src.option_scanner import _half_kelly_size, _fractional_kelly_size
    assert _half_kelly_size is _fractional_kelly_size
