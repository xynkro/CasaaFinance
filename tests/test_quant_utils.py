"""Tests for src/quant_utils.py — vetted quant primitives harvested from the OpenClaw audit."""
from __future__ import annotations

import math

import numpy as np
import pytest


def test_yang_zhang_recovers_known_vol():
    from src.quant_utils import yang_zhang_volatility

    rng = np.random.default_rng(1)
    n, true_vol = 252, 0.16
    daily = true_vol / math.sqrt(252)
    close = 100 * np.exp(np.cumsum(rng.normal(0, daily, n)))
    open_ = close * np.exp(rng.normal(0, daily / 3, n))
    high = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, daily / 3, n)))
    low = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, daily / 3, n)))

    vol = yang_zhang_volatility(open_, high, low, close)
    assert 0.08 < vol < 0.30  # right order of magnitude


def test_yang_zhang_requires_min_bars():
    from src.quant_utils import yang_zhang_volatility

    with pytest.raises(ValueError):
        yang_zhang_volatility([1, 2], [1, 2], [1, 2], [1, 2])


def test_expected_shortfall_is_worse_than_var():
    from src.quant_utils import expected_shortfall

    rng = np.random.default_rng(2)
    returns = rng.normal(0.001, 0.01, 500)
    returns[:10] = -0.05  # fat left tail
    es, var = expected_shortfall(returns, confidence=0.95)
    assert es <= var <= 0.0  # ES (tail mean) is at least as bad as VaR


def test_expected_shortfall_needs_enough_data():
    from src.quant_utils import expected_shortfall

    with pytest.raises(ValueError):
        expected_shortfall([0.01] * 5)


def test_beta_binomial_mean_and_lower_bound():
    from src.quant_utils import BetaBinomialWinRate

    wr = BetaBinomialWinRate()
    for w in [True, True, True, True, True, True, True, False]:  # 7-1
        wr.update(w)
    assert 0.7 < wr.mean < 0.85
    assert wr.lower_bound() < wr.mean  # conservative floor sits below the point estimate
    assert wr.n_effective == pytest.approx(8.0)


def test_beta_binomial_forgetting_decays_old_evidence():
    from src.quant_utils import BetaBinomialWinRate

    wr = BetaBinomialWinRate(forgetting=0.90)
    for _ in range(100):
        wr.update(True)
    # with forgetting, effective sample size saturates instead of growing unbounded
    assert wr.n_effective < 12.0


def test_shrink_to_prior_lands_between_empirical_and_prior():
    from src.quant_utils import shrink_to_prior

    s = shrink_to_prior(7, 1, prior_mean=0.55, prior_strength=10.0)
    assert 0.55 < s < 0.875  # between prior and empirical 7/8
    assert shrink_to_prior(0, 0) == 0.55  # no data -> prior


def test_correlation_clusters_collapses_redundant_pairs():
    from src.quant_utils import correlation_clusters

    labels = ["SPY", "VOO", "GLD", "GDX"]
    corr = [
        [1.00, 0.98, 0.10, 0.12],
        [0.98, 1.00, 0.08, 0.11],
        [0.10, 0.08, 1.00, 0.90],
        [0.12, 0.11, 0.90, 1.00],
    ]
    out = correlation_clusters(corr, labels, threshold=0.85)
    assert out["n_independent"] == 2
    assert sorted(out["redundant"]) == ["GDX", "VOO"]


def test_correlation_clusters_all_independent_when_threshold_high():
    from src.quant_utils import correlation_clusters

    labels = ["A", "B", "C"]
    corr = [[1.0, 0.5, 0.4], [0.5, 1.0, 0.3], [0.4, 0.3, 1.0]]
    out = correlation_clusters(corr, labels, threshold=0.85)
    assert out["n_independent"] == 3
    assert out["redundant"] == []


def test_touch_probability_matches_monte_carlo():
    from src.quant_utils import touch_probability

    rng = np.random.default_rng(3)
    spot, barrier, sig, T = 100.0, 99.0, 0.16, 1.0 / 252.0
    analytic = touch_probability(spot, barrier, sig, T)

    steps, paths = 300, 40000
    dt = T / steps
    incr = rng.normal((-0.5 * sig ** 2) * dt, sig * math.sqrt(dt), (paths, steps))
    mc = ((spot * np.exp(np.cumsum(incr, axis=1))).min(axis=1) <= barrier).mean()
    assert abs(analytic - mc) < 0.05


def test_touch_probability_monotonic_in_distance():
    from src.quant_utils import touch_probability

    # a closer barrier must be more likely to touch
    near = touch_probability(100.0, 99.0, 0.16, 1 / 252)
    far = touch_probability(100.0, 95.0, 0.16, 1 / 252)
    assert near > far


def test_touch_probability_rejects_bad_input():
    from src.quant_utils import touch_probability

    with pytest.raises(ValueError):
        touch_probability(100.0, 99.0, 0.0, 1 / 252)
