"""Tests for dealer Gamma Exposure (GEX) regime math (src/gex.py)."""
from __future__ import annotations

from src import gex


def _opt(strike, right, oi, T=0.05, sigma=0.15):
    return {"strike": strike, "right": right, "oi": oi, "T": T, "sigma": sigma}


def test_call_contributes_positive_put_negative():
    """Dealer-long-calls / short-puts convention: calls +, puts −."""
    spot = 500.0
    assert gex.signed_dollar_gamma(_opt(510, "C", 1000), spot) > 0
    assert gex.signed_dollar_gamma(_opt(490, "P", 1000), spot) < 0


def test_call_heavy_book_is_positive_pinned():
    spot = 500.0
    book = [_opt(505, "C", 5000), _opt(510, "C", 4000), _opt(495, "P", 300)]
    net = gex.net_gex(book, spot)
    gross = gex.gross_gex(book, spot)
    assert net > 0
    assert gex.classify_regime(net, gross) == "POSITIVE_PINNED"
    assert gex.premium_gate("POSITIVE_PINNED") == "SELL_OK"


def test_put_heavy_book_is_negative_trend():
    spot = 500.0
    book = [_opt(495, "P", 5000), _opt(490, "P", 4000), _opt(505, "C", 300)]
    net = gex.net_gex(book, spot)
    gross = gex.gross_gex(book, spot)
    assert net < 0
    assert gex.classify_regime(net, gross) == "NEGATIVE_TREND"
    assert gex.premium_gate("NEGATIVE_TREND") == "SELL_CAUTION"


def test_balanced_book_is_neutral():
    """Symmetric call/put OI roughly cancels → NEUTRAL, no decisive signal."""
    spot = 500.0
    book = [_opt(505, "C", 2000), _opt(495, "P", 2000)]
    net = gex.net_gex(book, spot)
    gross = gex.gross_gex(book, spot)
    assert gex.classify_regime(net, gross) == "NEUTRAL"
    assert gex.premium_gate("NEUTRAL") == "NORMAL"


def test_gamma_flip_between_walls():
    """Symmetric put wall below / call wall above → zero-gamma flip near spot."""
    spot = 500.0
    book = [_opt(520, "C", 5000), _opt(480, "P", 5000)]
    flip = gex.gamma_flip_level(book, spot)
    assert flip is not None
    assert 488 < flip < 512        # crossing sits near the symmetric centre


def test_walls_pick_right_strikes():
    spot = 500.0
    book = [
        _opt(515, "C", 8000), _opt(525, "C", 1000),   # call wall at 515
        _opt(480, "P", 9000), _opt(470, "P", 1000),   # put wall at 480
    ]
    assert gex.call_wall(book, spot) == 515
    assert gex.put_wall(book, spot) == 480


def test_empty_book_is_safe():
    assert gex.net_gex([], 500) == 0.0
    assert gex.gamma_flip_level([], 500) is None
    assert gex.classify_regime(0.0, 0.0) == "NEUTRAL"
    assert gex.call_wall([], 500) is None


def test_regime_note_is_human_readable():
    note = gex.regime_note("SPY", 500.0, -1.2e9, 498.0, 510.0, 480.0, "NEGATIVE_TREND")
    assert "SPY" in note and "GEX" in note
    assert "caution" in note.lower()
