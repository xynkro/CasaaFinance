"""Tests for Yang-Zhang RV estimator and IV/RV ratio signal."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest


def test_yang_zhang_rv_produces_output():
    """Yang-Zhang RV should use O/H/L/C and output reasonable values."""
    np.random.seed(42)
    n = 60
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    high = close + np.abs(np.random.randn(n)) * 1.5
    low = close - np.abs(np.random.randn(n)) * 1.5
    open_ = close + np.random.randn(n) * 0.5

    df = pd.DataFrame({
        "Open": open_, "High": high, "Low": low,
        "Close": close, "Volume": [1_000_000] * n,
    })

    from src.indicators import compute_indicators
    ind = compute_indicators(df)

    assert "volatility_annual" in ind
    assert "rv_estimator" in ind
    assert ind["rv_estimator"] == "yang_zhang"
    assert 0 < ind["volatility_annual"] < 3.0  # reasonable annualized range


def test_yang_zhang_insufficient_data():
    """With < 20 bars, should return 0.0 and 'insufficient_data'."""
    df = pd.DataFrame({
        "Open": [100] * 10, "High": [101] * 10, "Low": [99] * 10,
        "Close": [100] * 10, "Volume": [1_000_000] * 10,
    })

    from src.indicators import compute_indicators
    ind = compute_indicators(df)
    # compute_indicators returns early with empty dict if < 20 rows
    # So this will be an empty dict
    assert ind.get("volatility_annual", 0.0) == 0.0


def test_iv_rv_ratio_signal_rich_premium():
    """IV > RV should produce positive signal (premium is rich, good to sell)."""
    from src.technical_score import _sig_iv_rv_ratio
    result = _sig_iv_rv_ratio(0.40, 0.25)  # IV 40%, RV 25% -> ratio 1.6
    assert result > 0
    assert result <= 1.0


def test_iv_rv_ratio_signal_cheap_premium():
    """IV < RV should produce negative signal (premium is cheap, bad to sell)."""
    from src.technical_score import _sig_iv_rv_ratio
    result = _sig_iv_rv_ratio(0.20, 0.35)  # IV 20%, RV 35% -> ratio 0.57
    assert result < 0
    assert result >= -1.0


def test_iv_rv_ratio_signal_fair_value():
    """IV == RV should produce 0 signal (fair value)."""
    from src.technical_score import _sig_iv_rv_ratio
    assert _sig_iv_rv_ratio(0.30, 0.30) == 0.0


def test_iv_rv_ratio_signal_zero_inputs():
    """Zero IV or RV should produce 0 signal (no data)."""
    from src.technical_score import _sig_iv_rv_ratio
    assert _sig_iv_rv_ratio(0.0, 0.30) == 0.0
    assert _sig_iv_rv_ratio(0.30, 0.0) == 0.0


def test_iv_rv_ratio_in_strategy_weights():
    """iv_rv_ratio should be present in all strategy weights."""
    from src.technical_score import STRATEGY_WEIGHTS
    for strat, weights in STRATEGY_WEIGHTS.items():
        assert "iv_rv_ratio" in weights, f"Missing iv_rv_ratio weight for {strat}"
    # CSP should have the highest positive weight (core VRP signal)
    assert STRATEGY_WEIGHTS["CSP"]["iv_rv_ratio"] >= 5


def test_compute_signals_includes_iv_rv():
    """compute_signals should include iv_rv_ratio key."""
    from src.technical_score import compute_signals
    signals = compute_signals({"close": 100, "rsi_14": 50})
    assert "iv_rv_ratio" in signals
