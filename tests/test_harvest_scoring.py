"""Tests for harvest scan unified scoring."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
import logging
import numpy as np
import pandas as pd
import pytest


def _make_bullish_hist(n=250):
    """Create synthetic bullish price history (uptrend, healthy RSI)."""
    np.random.seed(42)
    # Trending up: start 80, end ~120
    base = np.linspace(80, 120, n)
    noise = np.random.randn(n) * 1.5
    close = base + noise
    high = close + np.abs(np.random.randn(n)) * 1.0
    low = close - np.abs(np.random.randn(n)) * 1.0
    open_ = close + np.random.randn(n) * 0.3

    return pd.DataFrame({
        "Open": open_, "High": high, "Low": low,
        "Close": close, "Volume": [2_000_000] * n,
    })


def test_conviction_uses_compute_scores():
    """technical_conviction should use compute_scores, not ad-hoc scoring."""
    from scripts.daily_options_scan import technical_conviction_gate as technical_conviction

    logger = logging.getLogger("test_harvest_scoring")
    hist = _make_bullish_hist()

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist

    with patch("yfinance.Ticker", return_value=mock_ticker):
        ok, conviction, ctx = technical_conviction("TEST", logger)

    # Should pass gates for bullish data
    assert ok is True
    # Conviction should be derived from CSP score, mapped to 0-100
    assert 0 <= conviction <= 100
    # Should have ctx with standard keys
    assert "price" in ctx
    assert "hv30" in ctx


def test_conviction_rejects_below_sma50():
    """Should reject when price < SMA50."""
    from scripts.daily_options_scan import technical_conviction_gate as technical_conviction

    logger = logging.getLogger("test_harvest_scoring")
    # Create bearish data: price trending down, below SMA50
    np.random.seed(42)
    n = 250
    close = np.linspace(120, 60, n) + np.random.randn(n) * 1.0
    hist = pd.DataFrame({
        "Open": close + 0.5, "High": close + 1, "Low": close - 1,
        "Close": close, "Volume": [2_000_000] * n,
    })

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist

    with patch("yfinance.Ticker", return_value=mock_ticker):
        ok, conviction, ctx = technical_conviction("TEST", logger)

    assert ok is False


def test_conviction_rejects_low_volume():
    """Should reject when average volume < 200K."""
    from scripts.daily_options_scan import technical_conviction_gate as technical_conviction

    logger = logging.getLogger("test_harvest_scoring")
    hist = _make_bullish_hist()
    hist["Volume"] = 50_000  # low volume

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist

    with patch("yfinance.Ticker", return_value=mock_ticker):
        ok, conviction, ctx = technical_conviction("TEST", logger)

    assert ok is False


def test_conviction_delegates_to_compute_scores():
    """Conviction value must come from compute_scores CSP output, not ad-hoc."""
    from scripts.daily_options_scan import technical_conviction_gate as technical_conviction
    from src.indicators import compute_indicators
    from src.technical_score import compute_scores

    logger = logging.getLogger("test_harvest_scoring")
    hist = _make_bullish_hist()

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist

    with patch("yfinance.Ticker", return_value=mock_ticker):
        ok, conviction, ctx = technical_conviction("TEST", logger)

    assert ok is True
    # Verify the conviction value matches the expected mapping
    ind = compute_indicators(hist)
    scores = compute_scores(ind)
    csp_score = scores.get("CSP", 0)
    expected_conviction = max(0, min(100, int((csp_score + 100) / 2)))
    assert conviction == expected_conviction


def test_conviction_rejects_rsi_too_low():
    """Should reject RSI < 30 (deeply oversold, falling knife risk)."""
    from scripts.daily_options_scan import technical_conviction_gate as technical_conviction
    from src.indicators import compute_indicators
    from src.technical_score import compute_scores

    logger = logging.getLogger("test_harvest_scoring")
    # Strongly downtrending: RSI will be very low
    np.random.seed(0)
    n = 250
    close = np.linspace(100, 40, n) + np.random.randn(n) * 0.5
    close = np.maximum(close, 1)  # no negative prices
    hist = pd.DataFrame({
        "Open": close + 0.2, "High": close + 0.5, "Low": close - 0.5,
        "Close": close, "Volume": [2_000_000] * n,
    })

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist

    with patch("yfinance.Ticker", return_value=mock_ticker):
        ok, conviction, ctx = technical_conviction("TEST", logger)

    assert ok is False


def test_conviction_rejects_rsi_too_high():
    """Should reject RSI > 75 (overbought, momentum chasing risk for CSP)."""
    from scripts.daily_options_scan import technical_conviction_gate as technical_conviction

    logger = logging.getLogger("test_harvest_scoring")
    # Extremely parabolic up: RSI will be very high
    np.random.seed(1)
    n = 250
    close = np.linspace(10, 300, n) + np.random.randn(n) * 0.2
    hist = pd.DataFrame({
        "Open": close + 0.1, "High": close + 0.3, "Low": close - 0.3,
        "Close": close, "Volume": [2_000_000] * n,
    })

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist

    with patch("yfinance.Ticker", return_value=mock_ticker):
        ok, conviction, ctx = technical_conviction("TEST", logger)

    assert ok is False


def test_conviction_ctx_has_required_keys():
    """Returned ctx dict should have all expected keys."""
    from scripts.daily_options_scan import technical_conviction_gate as technical_conviction

    logger = logging.getLogger("test_harvest_scoring")
    hist = _make_bullish_hist()

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist

    with patch("yfinance.Ticker", return_value=mock_ticker):
        ok, conviction, ctx = technical_conviction("TEST", logger)

    assert ok is True
    required_keys = {"price", "sma20", "sma50", "sma200", "rsi_14", "support",
                     "resistance", "hv30", "avg_vol"}
    assert required_keys.issubset(ctx.keys())


def test_conviction_rejects_empty_history():
    """Should return (False, 0, {}) on empty history."""
    from scripts.daily_options_scan import technical_conviction_gate as technical_conviction

    logger = logging.getLogger("test_harvest_scoring")

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()

    with patch("yfinance.Ticker", return_value=mock_ticker):
        ok, conviction, ctx = technical_conviction("TEST", logger)

    assert ok is False
    assert conviction == 0
    assert ctx == {}


def test_conviction_rejects_insufficient_history():
    """Should return (False, 0, {}) when history < 50 bars."""
    from scripts.daily_options_scan import technical_conviction_gate as technical_conviction

    logger = logging.getLogger("test_harvest_scoring")
    n = 30
    close = np.linspace(100, 110, n)
    hist = pd.DataFrame({
        "Open": close, "High": close + 1, "Low": close - 1,
        "Close": close, "Volume": [2_000_000] * n,
    })

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist

    with patch("yfinance.Ticker", return_value=mock_ticker):
        ok, conviction, ctx = technical_conviction("TEST", logger)

    assert ok is False
    assert conviction == 0
