"""Tests for Black-Scholes Greeks (delta, gamma, theta, vega)."""
from __future__ import annotations

import math
import pytest


# Standard test case: ATM put, S=K=100, T=35/365, sigma=30%, r=4.5%
S, K, T, SIGMA, R = 100.0, 100.0, 35/365, 0.30, 0.045


def test_bs_delta_atm_put():
    """ATM put delta should be approximately -0.50."""
    from src.wheel_continuation import bs_delta
    d = bs_delta(S, K, T, SIGMA, R, "P")
    assert -0.55 < d < -0.45


def test_bs_delta_atm_call():
    """ATM call delta should be approximately +0.50."""
    from src.wheel_continuation import bs_delta
    d = bs_delta(S, K, T, SIGMA, R, "C")
    assert 0.45 < d < 0.55


def test_bs_gamma_positive():
    """Gamma is always positive for both calls and puts."""
    from src.wheel_continuation import bs_gamma
    g = bs_gamma(S, K, T, SIGMA, R)
    assert g > 0


def test_bs_gamma_atm_range():
    """ATM gamma for typical values should be in reasonable range."""
    from src.wheel_continuation import bs_gamma
    g = bs_gamma(S, K, T, SIGMA, R)
    # For S=100, sigma=30%, T=35/365, gamma should be ~0.04-0.06
    assert 0.02 < g < 0.10


def test_bs_theta_put_negative():
    """Long put theta should be negative (time decay hurts long options)."""
    from src.wheel_continuation import bs_theta
    t = bs_theta(S, K, T, SIGMA, R, "P")
    assert t < 0


def test_bs_theta_call_negative():
    """Long call theta should be negative."""
    from src.wheel_continuation import bs_theta
    t = bs_theta(S, K, T, SIGMA, R, "C")
    assert t < 0


def test_bs_theta_daily_magnitude():
    """Daily theta for ATM $100 stock should be a few cents."""
    from src.wheel_continuation import bs_theta
    t = bs_theta(S, K, T, SIGMA, R, "P")
    # Should be roughly -$0.05 to -$0.15 per day for ATM
    assert -0.25 < t < -0.01


def test_bs_vega_positive():
    """Vega is always positive (more IV = higher option price)."""
    from src.wheel_continuation import bs_vega
    v = bs_vega(S, K, T, SIGMA, R)
    assert v > 0


def test_bs_vega_atm_range():
    """ATM vega per 1% IV change for $100 stock, ~35 DTE."""
    from src.wheel_continuation import bs_vega
    v = bs_vega(S, K, T, SIGMA, R)
    # Should be roughly $0.10-$0.20 per 1% IV change
    assert 0.05 < v < 0.40


def test_greeks_zero_inputs():
    """All Greeks should return 0.0 for zero/invalid inputs."""
    from src.wheel_continuation import bs_delta, bs_gamma, bs_theta, bs_vega
    # Zero time
    assert bs_delta(100, 100, 0, 0.30, 0.045, "P") == 0.0
    assert bs_gamma(100, 100, 0, 0.30, 0.045) == 0.0
    assert bs_theta(100, 100, 0, 0.30, 0.045, "P") == 0.0
    assert bs_vega(100, 100, 0, 0.30, 0.045) == 0.0
    # Zero sigma
    assert bs_gamma(100, 100, 0.1, 0, 0.045) == 0.0
    # Zero price
    assert bs_gamma(0, 100, 0.1, 0.30, 0.045) == 0.0


def test_put_call_parity_delta():
    """Put-call parity: call_delta - put_delta should equal ~1.0 (adjusted for r)."""
    from src.wheel_continuation import bs_delta
    call_d = bs_delta(S, K, T, SIGMA, R, "C")
    put_d = bs_delta(S, K, T, SIGMA, R, "P")
    # call_delta - put_delta ≈ 1.0 (exact: e^(-qT) but we have no dividends)
    diff = call_d - put_d
    assert 0.95 < diff < 1.05


def test_deep_otm_put_greeks():
    """Deep OTM put: small delta, small gamma/theta/vega."""
    from src.wheel_continuation import bs_delta, bs_gamma, bs_theta, bs_vega
    # 20% OTM put: K=80, S=100
    d = bs_delta(100, 80, 35/365, 0.30, 0.045, "P")
    g = bs_gamma(100, 80, 35/365, 0.30, 0.045)
    assert -0.10 < d < 0  # small negative delta
    assert 0 < g < 0.01   # small gamma
