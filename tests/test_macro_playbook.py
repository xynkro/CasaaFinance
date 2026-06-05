"""Tests for the macro-surprise playbook (structured actual-vs-forecast → so-what)."""
from __future__ import annotations

from src.macro_playbook import interpret_surprise


def test_hot_cpi_is_hawkish():
    r = interpret_surprise("CPI YoY", actual="3.5", forecast="3.2", previous="3.2", unit="%")
    assert r and r["direction"] == "BEAT" and r["lean"] == "hawkish"
    assert "rate-cut odds fall" in r["market_take"]
    assert "QQQ core" in r["book_note"]


def test_cool_cpi_flips_to_dovish():
    r = interpret_surprise("CPI YoY", actual="2.9", forecast="3.2", unit="%")
    assert r and r["direction"] == "MISS" and r["lean"] == "dovish"


def test_higher_unemployment_is_dovish():
    """Unemployment is inverted — a higher print is dovish (weak labour → cuts)."""
    r = interpret_surprise("Unemployment Rate", actual="4.5", forecast="4.1", unit="%")
    assert r and r["direction"] == "BEAT" and r["lean"] == "dovish"


def test_strong_payrolls_is_hawkish():
    r = interpret_surprise("Nonfarm Payrolls", actual="320", forecast="200", unit="K")
    assert r and r["lean"] == "hawkish"


def test_strong_gdp_is_risk_on():
    r = interpret_surprise("GDP Growth Rate QoQ", actual="3.1", forecast="2.2", unit="%")
    assert r and r["lean"] == "risk_on" and "supports QQQ core" in r["book_note"]


def test_inline_print_returns_none():
    """Actual ≈ forecast → no surprise → nothing to flag."""
    assert interpret_surprise("CPI YoY", actual="3.2", forecast="3.2", unit="%") is None
    assert interpret_surprise("Nonfarm Payrolls", actual="203", forecast="200") is None


def test_unknown_event_returns_none():
    assert interpret_surprise("German Buba Balz Speech", actual="1", forecast="0") is None


def test_missing_forecast_returns_none():
    assert interpret_surprise("CPI YoY", actual="3.5", forecast="") is None


def test_core_pce_matches_before_generic():
    r = interpret_surprise("Core PCE Price Index YoY", actual="3.0", forecast="2.6", unit="%")
    assert r and r["label"] == "Core PCE" and r["lean"] == "hawkish"
