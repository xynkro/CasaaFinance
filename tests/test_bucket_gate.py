"""Tests for A2 — bucket eligibility gate (wheel discipline) wired live."""
from __future__ import annotations

import pytest


def test_core_compounder_cc_blocked():
    """Never CC a core compounder (SCHD)."""
    from src.trading_rules import cc_blocked_by_bucket
    blocked, reason = cc_blocked_by_bucket("SCHD")
    assert blocked
    assert "core" in reason.lower()


def test_blue_chip_cc_blocked():
    """Never CC a blue-chip without cost basis (AAPL)."""
    from src.trading_rules import cc_blocked_by_bucket
    blocked, reason = cc_blocked_by_bucket("AAPL")
    assert blocked
    assert "blue_chip" in reason.lower()


def test_lottery_csp_blocked():
    """Never CSP a lottery name (BBAI)."""
    from src.trading_rules import csp_blocked_by_bucket
    blocked, reason = csp_blocked_by_bucket("BBAI")
    assert blocked
    assert "lottery" in reason.lower()


def test_leveraged_etf_both_blocked():
    """Leveraged ETFs blocked for both CC and CSP (TQQQ)."""
    from src.trading_rules import cc_blocked_by_bucket, csp_blocked_by_bucket
    assert cc_blocked_by_bucket("TQQQ")[0]
    assert csp_blocked_by_bucket("TQQQ")[0]


def test_core_csp_allowed():
    """CSP on core IS allowed (paid to accumulate the compounder)."""
    from src.trading_rules import csp_blocked_by_bucket
    blocked, _ = csp_blocked_by_bucket("SCHD")
    assert not blocked


def test_spec_growth_both_allowed():
    """Natural wheel target (SOFI) — both CC and CSP allowed."""
    from src.trading_rules import cc_blocked_by_bucket, csp_blocked_by_bucket
    assert not cc_blocked_by_bucket("SOFI")[0]
    assert not csp_blocked_by_bucket("SOFI")[0]


def test_unknown_ticker_defaults_eligible():
    """Unknown/discovery ticker defaults to spec_growth → not over-suppressed."""
    from src.trading_rules import cc_blocked_by_bucket, csp_blocked_by_bucket, bucket_for
    assert bucket_for("ZZZZ_UNKNOWN") == "spec_growth"
    assert not cc_blocked_by_bucket("ZZZZ_UNKNOWN")[0]
    assert not csp_blocked_by_bucket("ZZZZ_UNKNOWN")[0]


def test_case_insensitive():
    """Lookup is case-insensitive."""
    from src.trading_rules import cc_blocked_by_bucket
    assert cc_blocked_by_bucket("schd")[0]


def test_screener_reexport_still_works():
    """options_yield_screener must still expose the gate names (backward compat)."""
    import importlib
    mod = importlib.import_module("scripts.options_yield_screener")
    assert mod.cc_blocked_by_bucket("SCHD")[0]
    assert mod.csp_blocked_by_bucket("BBAI")[0]
    # _bucket_for alias still resolves
    assert mod._bucket_for("SCHD") == "core"


def test_scanner_imports_gate():
    """daily_options_scan must import the gate helpers it now uses."""
    src = open("scripts/daily_options_scan.py").read()
    assert "cc_blocked_by_bucket" in src
    assert "csp_blocked_by_bucket" in src
    assert "csp_bucket_blocked" in src
    assert "cc_bucket_blocked" in src
