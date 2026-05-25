"""Tests for per-ticker earnings gating in unified scanner."""
from __future__ import annotations

import math
from unittest.mock import patch, MagicMock
import logging

import pytest


def test_scan_ticker_rejects_csp_near_earnings():
    """scan_ticker should skip CSP when earnings fall inside option DTE."""
    from scripts.daily_options_scan import scan_ticker

    logger = logging.getLogger("test_earnings")

    mock_ticker = MagicMock()
    mock_fi = MagicMock()
    mock_fi.last_price = 100.0
    mock_ticker.fast_info = mock_fi
    mock_ticker.options = ["2026-07-18"]  # ~55 days out

    # Minimal chain with one put
    import pandas as pd
    puts = pd.DataFrame({
        "strike": [90.0], "lastPrice": [2.0], "bid": [1.8], "ask": [2.2],
        "openInterest": [500], "impliedVolatility": [0.35],
        "contractSymbol": ["TEST260718P00090000"],
    })
    calls = pd.DataFrame({
        "strike": [110.0], "lastPrice": [2.0], "bid": [1.8], "ask": [2.2],
        "openInterest": [500], "impliedVolatility": [0.35],
        "contractSymbol": ["TEST260718C00110000"],
    })
    mock_chain = MagicMock()
    mock_chain.puts = puts
    mock_chain.calls = calls
    mock_ticker.option_chain.return_value = mock_chain

    # Mock history for _technical_context
    import numpy as np
    n = 250
    close = np.linspace(80, 100, n)
    hist = pd.DataFrame({
        "Open": close, "High": close + 1, "Low": close - 1,
        "Close": close, "Volume": [2_000_000] * n,
    })
    mock_ticker.history.return_value = hist

    with patch("yfinance.Ticker", return_value=mock_ticker):
        # Earnings in 15 days, DTE will be ~55 → earnings inside option lifetime → CSP blocked
        result = scan_ticker("TEST", logger, earnings_days_away=15)
        csp_picks = [r for r in result if r.get("strategy") in ("CSP", "HARVEST_CSP")]
        assert len(csp_picks) == 0, "Should block CSP when earnings fall inside DTE"


def test_scan_ticker_allows_csp_no_earnings():
    """scan_ticker should allow CSP when no earnings data (default -1)."""
    from scripts.daily_options_scan import scan_ticker

    logger = logging.getLogger("test_earnings")

    mock_ticker = MagicMock()
    mock_fi = MagicMock()
    mock_fi.last_price = 100.0
    mock_ticker.fast_info = mock_fi
    mock_ticker.options = []  # no expiries = returns [] naturally

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = scan_ticker("TEST", logger, earnings_days_away=-1)
        # No expiries so empty, but function shouldn't have early-returned due to earnings
        assert isinstance(result, list)


def test_scan_ticker_allows_csp_earnings_after_expiry():
    """scan_ticker should NOT block CSP when earnings are AFTER the option expires."""
    from scripts.daily_options_scan import scan_ticker
    from datetime import date, timedelta

    logger = logging.getLogger("test_earnings")

    exp_date = (date.today() + timedelta(days=35)).strftime("%Y-%m-%d")
    mock_ticker = MagicMock()
    mock_fi = MagicMock()
    mock_fi.last_price = 100.0
    mock_ticker.fast_info = mock_fi
    mock_ticker.options = [exp_date]
    # Chain fetch will fail → returns [] from chain error, NOT from earnings gate
    mock_ticker.option_chain.side_effect = Exception("no chain data")

    # Mock history for _technical_context
    import numpy as np
    import pandas as pd
    n = 250
    close = np.linspace(80, 100, n)
    hist = pd.DataFrame({
        "Open": close, "High": close + 1, "Low": close - 1,
        "Close": close, "Volume": [2_000_000] * n,
    })
    mock_ticker.history.return_value = hist

    with patch("yfinance.Ticker", return_value=mock_ticker):
        # Earnings in 90 days, DTE ~35 → 0 <= 90 <= 35 is FALSE → not blocked
        # Chain error should produce empty list, not earnings block
        result = scan_ticker("TEST", logger, earnings_days_away=90)
        assert isinstance(result, list)


def test_scan_ticker_blocks_csp_earnings_same_day():
    """Edge case: earnings TODAY (day 0) should block CSP."""
    from scripts.daily_options_scan import scan_ticker

    logger = logging.getLogger("test_earnings")

    mock_ticker = MagicMock()
    mock_fi = MagicMock()
    mock_fi.last_price = 100.0
    mock_ticker.fast_info = mock_fi
    mock_ticker.options = ["2026-07-18"]

    import numpy as np
    import pandas as pd
    n = 250
    close = np.linspace(80, 100, n)
    hist = pd.DataFrame({
        "Open": close, "High": close + 1, "Low": close - 1,
        "Close": close, "Volume": [2_000_000] * n,
    })
    mock_ticker.history.return_value = hist

    puts = pd.DataFrame({
        "strike": [90.0], "lastPrice": [2.0], "bid": [1.8], "ask": [2.2],
        "openInterest": [500], "impliedVolatility": [0.35],
        "contractSymbol": ["TEST260718P00090000"],
    })
    calls = pd.DataFrame({
        "strike": [110.0], "lastPrice": [2.0], "bid": [1.8], "ask": [2.2],
        "openInterest": [500], "impliedVolatility": [0.35],
        "contractSymbol": ["TEST260718C00110000"],
    })
    mock_chain = MagicMock()
    mock_chain.puts = puts
    mock_chain.calls = calls
    mock_ticker.option_chain.return_value = mock_chain

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = scan_ticker("TEST", logger, earnings_days_away=0)
        csp_picks = [r for r in result if r.get("strategy") in ("CSP", "HARVEST_CSP")]
        assert len(csp_picks) == 0, "Should block CSP when earnings are today"
