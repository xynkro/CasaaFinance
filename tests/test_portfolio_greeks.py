"""Tests for book-level Greek aggregation (F1)."""
from __future__ import annotations

from datetime import date, timedelta
import pytest


def _opt(**kw):
    """Build an OptionRow-shaped dict with sensible defaults."""
    base = {
        "ticker": "TEST", "right": "P", "strike": 95.0, "qty": -1,
        "underlying_last": 100.0, "last": 2.50, "volatility_annual": 0.30,
        "dte": 35,
    }
    base.update(kw)
    return base


def test_solve_iv_recovers_known_vol():
    """solve_iv should recover the vol used to price the option."""
    from src.portfolio_greeks import solve_iv, _bsm_price
    S, K, T, sigma, r, right = 100.0, 95.0, 35 / 365, 0.35, 0.045, "P"
    price = _bsm_price(S, K, T, sigma, r, right)
    iv = solve_iv(price, S, K, T, right, r)
    assert abs(iv - 0.35) < 0.01


def test_solve_iv_unsolvable_returns_zero():
    """Price below intrinsic or bad inputs → 0.0."""
    from src.portfolio_greeks import solve_iv
    # Deep ITM put worth at least intrinsic 40; price 1.0 is below intrinsic
    assert solve_iv(1.0, 100.0, 140.0, 35 / 365, "P", 0.045) == 0.0
    assert solve_iv(0.0, 100.0, 95.0, 35 / 365, "P") == 0.0


def test_short_put_has_negative_vega_positive_theta():
    """A short put: vol up hurts (neg vega), time decay helps (pos theta)."""
    from src.portfolio_greeks import position_greeks
    g = position_greeks(_opt(right="P", qty=-1))
    assert g["valid"]
    assert g["vega"] < 0      # short option → negative vega
    assert g["theta"] > 0     # short option → collects theta
    assert g["gamma"] < 0     # short option → negative gamma


def test_long_call_has_positive_vega_negative_theta():
    """A long call: vol up helps (pos vega), time decay hurts (neg theta)."""
    from src.portfolio_greeks import position_greeks
    g = position_greeks(_opt(right="C", strike=105.0, qty=1, last=2.0))
    assert g["valid"]
    assert g["vega"] > 0
    assert g["theta"] < 0
    assert g["gamma"] > 0


def test_stock_row_ignored():
    """Non-option rows (no right) produce no Greeks."""
    from src.portfolio_greeks import position_greeks
    g = position_greeks({"ticker": "AAPL", "right": "", "qty": 100,
                         "underlying_last": 100.0})
    assert not g["valid"]
    assert g["vega"] == 0.0


def test_expired_position_ignored():
    """dte <= 0 → no Greeks (avoids div-by-zero)."""
    from src.portfolio_greeks import position_greeks
    g = position_greeks(_opt(dte=0))
    assert not g["valid"]


def test_rv_fallback_when_no_last_price():
    """With no option last price, IV falls back to realized vol."""
    from src.portfolio_greeks import position_greeks
    g = position_greeks(_opt(last=0.0, volatility_annual=0.40))
    assert g["valid"]
    assert g["iv_source"] == "rv_fallback"
    assert g["iv"] == 0.40


def test_aggregate_net_short_vega_book():
    """A book of short puts should net negative vega and a negative VIX-shock P&L."""
    from src.portfolio_greeks import aggregate_book_greeks
    book = [
        _opt(ticker="AAPL", qty=-2),
        _opt(ticker="NVDA", strike=120.0, underlying_last=130.0, qty=-1, last=3.0),
    ]
    agg = aggregate_book_greeks(book, vix_shock_pts=5.0)
    assert agg["net_vega"] < 0
    assert agg["vix_shock_pnl"] < 0          # vol spike hurts a short-vol book
    assert agg["vix_shock_pnl"] == round(agg["net_vega"] * 5.0, 2)
    assert agg["n_valued"] == 2
    assert set(agg["by_ticker"]) == {"AAPL", "NVDA"}


def test_aggregate_skips_invalid_positions():
    """Stock rows and expired options are excluded from the book totals."""
    from src.portfolio_greeks import aggregate_book_greeks
    book = [
        _opt(ticker="AAPL", qty=-1),
        {"ticker": "CASH", "right": "", "qty": 0},   # not an option
        _opt(ticker="OLD", dte=-3),                   # expired
    ]
    agg = aggregate_book_greeks(book)
    assert agg["n_positions"] == 3
    assert agg["n_valued"] == 1


def test_expiry_string_parsing():
    """dte can be derived from a YYYYMMDD expiry when dte field is absent."""
    from src.portfolio_greeks import position_greeks
    future = (date.today() + timedelta(days=35)).strftime("%Y%m%d")
    g = position_greeks(_opt(dte="", expiry=future))
    assert g["valid"]
