"""Tests for src.mae_mfe — the MAE/MFE excursion math.

These cover the pure reducers only (no Sheets I/O). The headline behaviour we
care about: a position that spikes then round-trips must report a large
`given_back`, and the what-if exit rules must realise the right value on first
touch.
"""
from __future__ import annotations

import math

import pytest

from src.mae_mfe import (
    Excursions,
    compute_excursions,
    is_option,
    whatif_bracket,
    whatif_profit_take,
)


def test_is_option_true_for_occ_symbol():
    assert is_option("PSN260618C00050000") is True
    assert is_option("IBM260717P00285000") is True


def test_is_option_false_for_plain_ticker():
    assert is_option("AAPL") is False
    assert is_option("QCOM") is False


def test_compute_excursions_spike_then_roundtrip():
    # The PSN-shaped case: up to +50, gives it all back and then some.
    e = compute_excursions([10.0, 50.0, 30.0, -27.0])
    assert e.mfe == 50.0
    assert e.mae == -27.0
    assert e.exit == -27.0
    assert e.given_back == 77.0  # 50 - (-27)
    assert e.capture == pytest.approx(-27.0 / 50.0)


def test_compute_excursions_monotonic_up_gives_nothing_back():
    e = compute_excursions([5.0, 10.0, 20.0])
    assert e.mfe == 20.0
    assert e.given_back == 0.0
    assert e.capture == pytest.approx(1.0)


def test_compute_excursions_never_profitable_has_no_capture():
    e = compute_excursions([-5.0, -10.0, -3.0])
    assert e.mfe == -3.0
    assert e.mae == -10.0
    assert e.given_back == 0.0  # peak == exit, nothing surrendered
    assert e.capture is None  # never above water → capture undefined


def test_compute_excursions_rejects_empty_path():
    with pytest.raises(ValueError):
        compute_excursions([])


def test_whatif_profit_take_fills_on_first_touch():
    # Crosses +25 at the 50 mark → realises that day's mark (conservative: the
    # actual daily value, not the unobservable intraday peak).
    assert whatif_profit_take([10.0, 50.0, 30.0, -27.0], 25.0) == 50.0


def test_whatif_profit_take_holds_to_end_when_never_triggered():
    assert whatif_profit_take([10.0, 20.0, 15.0], 25.0) == 15.0


def test_whatif_bracket_takes_profit_first():
    assert whatif_bracket([10.0, 50.0, 30.0, -27.0], take=40.0, stop=-20.0) == 50.0


def test_whatif_bracket_stops_out_first():
    assert whatif_bracket([10.0, -25.0, 30.0], take=40.0, stop=-20.0) == -25.0


def test_whatif_bracket_holds_when_neither_bound_hit():
    assert whatif_bracket([10.0, 20.0, 15.0], take=40.0, stop=-20.0) == 15.0
