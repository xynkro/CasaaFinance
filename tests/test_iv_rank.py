"""Tests for robust IV Rank and IV Percentile."""
from __future__ import annotations

import pytest


def test_iv_rank_basic():
    """IV Rank should compute (current - low) / (high - low) * 100."""
    from src.iv_rank import compute_iv_rank

    history = list(range(10, 60))  # IV ranged 10 to 59
    current = 40.0
    rank = compute_iv_rank(current, history)
    # (40 - 10) / (59 - 10) = 30 / 49 = 61.2%
    assert 60 < rank < 63


def test_iv_percentile_basic():
    """IV Percentile = % of days below current."""
    from src.iv_rank import compute_iv_percentile

    history = list(range(10, 60))  # 50 values: 10,11,...,59
    current = 40.0
    pctile = compute_iv_percentile(current, history)
    # 30 values (10-39) are below 40 -> 30/50 = 60%
    assert pctile == 60.0


def test_iv_rank_insufficient_history():
    """With < 30 data points, should return -1 (insufficient data)."""
    from src.iv_rank import compute_iv_rank
    assert compute_iv_rank(30.0, [25.0, 35.0]) == -1.0


def test_iv_percentile_insufficient_history():
    """With < 30 data points, should return -1."""
    from src.iv_rank import compute_iv_percentile
    assert compute_iv_percentile(30.0, [25.0, 35.0]) == -1.0


def test_iv_rank_zero_current():
    """Zero current IV should return -1."""
    from src.iv_rank import compute_iv_rank
    assert compute_iv_rank(0.0, list(range(10, 60))) == -1.0


def test_iv_rank_flat_history():
    """All same values in history should return 50."""
    from src.iv_rank import compute_iv_rank
    assert compute_iv_rank(30.0, [30.0] * 50) == 50.0


def test_iv_percentile_all_below():
    """When current is above all history, percentile should be ~100."""
    from src.iv_rank import compute_iv_percentile
    history = list(range(10, 41))  # 31 values: 10-40
    pctile = compute_iv_percentile(100.0, history)
    assert pctile == 100.0


def test_iv_percentile_all_above():
    """When current is below all history, percentile should be 0."""
    from src.iv_rank import compute_iv_percentile
    history = list(range(50, 81))  # 31 values: 50-80
    pctile = compute_iv_percentile(5.0, history)
    assert pctile == 0.0


def test_iv_rank_cleans_zeroes():
    """Zero/None values in history should be filtered out."""
    from src.iv_rank import compute_iv_rank
    history = [0, 0, None] + list(range(10, 50))  # 40 clean values
    rank = compute_iv_rank(30.0, history)
    assert rank > 0  # should compute from clean values only


def test_option_scanner_uses_robust_rank():
    """option_scanner._iv_rank should delegate to iv_rank module."""
    from src.option_scanner import _iv_rank
    # Should return -1 for insufficient data (not 0.0 like before)
    result = _iv_rank(30.0, [25.0, 35.0])
    assert result == -1.0
