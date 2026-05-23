"""Tests for daily scan unified scoring integration."""
from __future__ import annotations

from unittest.mock import MagicMock
import numpy as np
import pandas as pd
import pytest


def _make_hist(n: int = 250) -> pd.DataFrame:
    """Create synthetic uptrending price history."""
    np.random.seed(42)
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


def test_technical_context_uses_compute_indicators():
    """_technical_context should delegate to compute_indicators and expose _scores."""
    from scripts.daily_options_scan import _technical_context

    hist = _make_hist()
    mock_yt = MagicMock()
    mock_yt.history.return_value = hist

    ctx = _technical_context(mock_yt)

    assert "hv30" in ctx
    assert "rsi_14" in ctx
    assert "support" in ctx
    assert "resistance" in ctx
    # Should include full indicator dict for downstream use
    assert "_indicators" in ctx
    assert isinstance(ctx["_indicators"], dict)
    # Should include unified strategy scores
    assert "_scores" in ctx
    scores = ctx["_scores"]
    assert "CSP" in scores
    assert "CC" in scores
    assert "BUY" in scores
    assert "LONG_CALL" in scores


def test_technical_context_scores_are_floats():
    """Unified scores should be numeric floats in valid range."""
    from scripts.daily_options_scan import _technical_context

    hist = _make_hist()
    mock_yt = MagicMock()
    mock_yt.history.return_value = hist

    ctx = _technical_context(mock_yt)
    scores = ctx["_scores"]

    for strat, score in scores.items():
        assert isinstance(score, float), f"{strat} score is not float"
        assert -100.0 <= score <= 100.0, f"{strat} score {score} out of range"


def test_technical_context_backward_compat_keys():
    """Existing callers that read hv30/rsi_14/support/resistance must still work."""
    from scripts.daily_options_scan import _technical_context

    hist = _make_hist()
    mock_yt = MagicMock()
    mock_yt.history.return_value = hist

    ctx = _technical_context(mock_yt)

    assert isinstance(ctx["hv30"], float)
    assert ctx["hv30"] >= 0.0
    assert 0.0 <= ctx["rsi_14"] <= 100.0
    assert ctx["support"] >= 0.0
    assert ctx["resistance"] >= 0.0


def test_technical_context_empty_history():
    """Should return defaults when history is empty."""
    from scripts.daily_options_scan import _technical_context

    mock_yt = MagicMock()
    mock_yt.history.return_value = pd.DataFrame()

    ctx = _technical_context(mock_yt)
    assert ctx["hv30"] == 0.0
    assert ctx["rsi_14"] == 50.0
    assert ctx["_indicators"] == {}
    assert ctx["_scores"] == {}


def test_technical_context_too_short_history():
    """Should return defaults when fewer than 20 bars."""
    from scripts.daily_options_scan import _technical_context

    hist = _make_hist(n=15)
    mock_yt = MagicMock()
    mock_yt.history.return_value = hist

    ctx = _technical_context(mock_yt)
    assert ctx["hv30"] == 0.0
    assert ctx["rsi_14"] == 50.0


def test_estimate_ivr_equal_iv_hv():
    """When IV equals HV, IVR proxy should be near 50."""
    from scripts.daily_options_scan import _estimate_ivr

    result = _estimate_ivr(30.0, 30.0)
    assert 45 < result < 55


def test_estimate_ivr_elevated_iv():
    """When IV is 1.5x HV, IVR proxy should be near 75."""
    from scripts.daily_options_scan import _estimate_ivr

    result = _estimate_ivr(45.0, 30.0)
    assert 70 < result < 80


def test_estimate_ivr_suppressed_iv():
    """When IV is 0.7x HV, IVR proxy should be near 35."""
    from scripts.daily_options_scan import _estimate_ivr

    result = _estimate_ivr(21.0, 30.0)
    assert 30 < result < 40


def test_estimate_ivr_zero_hv():
    """Zero HV should return neutral 50.0."""
    from scripts.daily_options_scan import _estimate_ivr

    assert _estimate_ivr(30.0, 0.0) == 50.0


def test_estimate_ivr_clamps_to_zero():
    """Very low IV vs HV should not go below 0."""
    from scripts.daily_options_scan import _estimate_ivr

    result = _estimate_ivr(1.0, 100.0)
    assert result >= 0.0


def test_estimate_ivr_clamps_to_hundred():
    """Very high IV vs HV should not exceed 100."""
    from scripts.daily_options_scan import _estimate_ivr

    result = _estimate_ivr(500.0, 10.0)
    assert result <= 100.0


def test_technical_context_fetches_250d():
    """Should request 250d of history (enough for indicators including SMA200)."""
    from scripts.daily_options_scan import _technical_context

    mock_yt = MagicMock()
    mock_yt.history.return_value = pd.DataFrame()  # empty is fine; testing call args

    _technical_context(mock_yt)

    call_kwargs = mock_yt.history.call_args
    # Accept positional or keyword period argument
    if call_kwargs.kwargs.get("period"):
        assert call_kwargs.kwargs["period"] == "250d"
    else:
        assert call_kwargs.args[0] == "250d"
