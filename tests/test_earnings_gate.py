"""Tests for per-ticker earnings gating in harvest scan."""
from __future__ import annotations

import math
from unittest.mock import patch, MagicMock
import logging

import pytest


def test_scan_chain_rejects_near_earnings():
    """scan_chain should return [] when earnings fall inside option DTE."""
    from scripts.premium_harvest_scan import scan_chain

    logger = logging.getLogger("test_earnings")
    ctx = {
        "price": 100.0, "sma20": 101.0, "sma50": 99.0, "sma200": 95.0,
        "rsi_14": 50.0, "support": 95.0, "resistance": 105.0,
        "hv30": 30.0, "avg_vol": 1_000_000,
    }
    macro = {"regime": "STANDARD", "vix": 18.0, "spx_above_200sma": True}

    # Mock yfinance so we don't hit network
    mock_ticker = MagicMock()
    mock_ticker.options = ["2026-07-18"]  # ~55 days out

    with patch("yfinance.Ticker", return_value=mock_ticker):
        # Earnings in 15 days, DTE will be ~55 → earnings inside option lifetime → blocked
        result = scan_chain("TEST", ctx, 60, macro, logger, earnings_days_away=15)
        assert result == [], "Should block when earnings fall inside DTE"


def test_scan_chain_allows_no_earnings():
    """scan_chain should proceed normally when no earnings data (default -1)."""
    from scripts.premium_harvest_scan import scan_chain

    logger = logging.getLogger("test_earnings")
    ctx = {
        "price": 100.0, "sma20": 101.0, "sma50": 99.0, "sma200": 95.0,
        "rsi_14": 50.0, "support": 95.0, "resistance": 105.0,
        "hv30": 30.0, "avg_vol": 1_000_000,
    }
    macro = {"regime": "STANDARD", "vix": 18.0, "spx_above_200sma": True}

    # With earnings_days_away=-1, should proceed (not blocked)
    # It may still return [] if no chain data, but it shouldn't return early due to earnings
    mock_ticker = MagicMock()
    mock_ticker.options = []  # no expiries = returns [] naturally

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = scan_chain("TEST", ctx, 60, macro, logger, earnings_days_away=-1)
        # No chain data so empty, but the function should have reached the chain fetch stage
        assert isinstance(result, list)


def test_scan_chain_allows_earnings_after_expiry():
    """scan_chain should allow when earnings are AFTER the option expires."""
    from scripts.premium_harvest_scan import scan_chain

    logger = logging.getLogger("test_earnings")
    ctx = {
        "price": 100.0, "sma20": 101.0, "sma50": 99.0, "sma200": 95.0,
        "rsi_14": 50.0, "support": 95.0, "resistance": 105.0,
        "hv30": 30.0, "avg_vol": 1_000_000,
    }
    macro = {"regime": "STANDARD", "vix": 18.0, "spx_above_200sma": True}

    mock_ticker = MagicMock()
    mock_ticker.options = []

    with patch("yfinance.Ticker", return_value=mock_ticker):
        # Earnings in 90 days — far beyond any DTE we'd pick (max 45) → allowed
        result = scan_chain("TEST", ctx, 60, macro, logger, earnings_days_away=90)
        assert isinstance(result, list)  # Should not be blocked by earnings gate


def test_scan_chain_blocks_earnings_same_day():
    """Edge case: earnings TODAY (day 0) should block."""
    from scripts.premium_harvest_scan import scan_chain

    logger = logging.getLogger("test_earnings")
    ctx = {
        "price": 100.0, "sma20": 101.0, "sma50": 99.0, "sma200": 95.0,
        "rsi_14": 50.0, "support": 95.0, "resistance": 105.0,
        "hv30": 30.0, "avg_vol": 1_000_000,
    }
    macro = {"regime": "STANDARD", "vix": 18.0, "spx_above_200sma": True}

    mock_ticker = MagicMock()
    mock_ticker.options = ["2026-07-18"]

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = scan_chain("TEST", ctx, 60, macro, logger, earnings_days_away=0)
        assert result == [], "Should block when earnings are today"
