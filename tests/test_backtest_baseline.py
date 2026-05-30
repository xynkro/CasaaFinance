"""Tests for the dumb-heuristic CSP baseline in backtest_scoring."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _make_df(n=400):
    np.random.seed(7)
    close = 100 + np.cumsum(np.random.randn(n) * 1.5)
    close = np.abs(close) + 10  # keep positive
    high = close + np.abs(np.random.randn(n))
    low = close - np.abs(np.random.randn(n))
    open_ = close + np.random.randn(n) * 0.3
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close,
         "Volume": [1_000_000] * n},
        index=idx,
    )


def test_vol_rank_series_bounds():
    """IV-rank proxy must be within [0, 100] where defined."""
    from scripts.backtest_scoring import _vol_rank_series
    s = _make_df()
    ranks = _vol_rank_series(s).dropna()
    assert len(ranks) > 0
    assert ranks.min() >= 0.0
    assert ranks.max() <= 100.0


def test_heuristic_csp_only_fires_above_gate():
    """All heuristic trades should carry a score (= IVR proxy) >= the gate."""
    from scripts.backtest_scoring import _heuristic_csp_trades
    df = _make_df()
    gate = 50.0
    trades = _heuristic_csp_trades("TEST", df, hold_days=35, ivr_gate=gate)
    # Should produce at least some trades on 400 bars of noisy data
    assert len(trades) > 0
    assert all(t.score >= gate for t in trades)
    assert all(t.strategy == "CSP_IVR" for t in trades)


def test_heuristic_high_gate_fires_less():
    """A higher IVR gate should never produce MORE trades than a lower one."""
    from scripts.backtest_scoring import _heuristic_csp_trades
    df = _make_df()
    low = _heuristic_csp_trades("TEST", df, hold_days=35, ivr_gate=40.0)
    high = _heuristic_csp_trades("TEST", df, hold_days=35, ivr_gate=80.0)
    assert len(high) <= len(low)
