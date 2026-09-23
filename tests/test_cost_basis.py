"""Cost-basis integrity — the `upl == mkt_val` bug.

Between 2026-06-05 and 2026-06-13 every `avg_cost` in positions_caspar went
to 0. The local TWS grab (`ibkr-grab`, which read ib_insync `averageCost`)
died around 2026-06-10 and the Flex path took over; Flex's `costBasisPrice`
came through empty, so `_flex_stock_row` wrote avg_cost 0. yahoo_grab then
read its OWN previous row back each run, so the zero propagated forward for
three months. With avg_cost 0 the P&L line reduces to

    upl = (price - 0) * qty == mkt_val

i.e. every holding reported as pure profit. Caspar's book showed +$8,473
unrealised against a true figure near -$500. Sarah's account was never
affected (she is carried forward from the last good grab, not from Flex).

These tests pin the two halves of the fix: recover a real cost basis where
one exists, and refuse to invent one where it does not.
"""
import pytest

from src.yahoo_grab import avg_cost_index, resolve_cost_and_upl
from scripts.ibkr_flex_sync import flex_cost_price


# ── avg_cost_index ───────────────────────────────────────────────────────────

def test_index_takes_last_non_zero_per_ticker():
    rows = [
        {"date": "2026-06-01", "ticker": "SCHD", "avg_cost": "28.00"},
        {"date": "2026-06-10", "ticker": "SCHD", "avg_cost": "29.5703"},
        {"date": "2026-09-23", "ticker": "SCHD", "avg_cost": "0"},
    ]
    assert avg_cost_index(rows)["SCHD"] == pytest.approx(29.5703)


def test_index_is_date_ordered_not_row_ordered():
    """Rows arrive unsorted after a dedup rewrite; the newest date must win."""
    rows = [
        {"date": "2026-06-10", "ticker": "TLT", "avg_cost": "86.0812"},
        {"date": "2026-05-01", "ticker": "TLT", "avg_cost": "12.00"},
    ]
    assert avg_cost_index(rows)["TLT"] == pytest.approx(86.0812)


def test_index_skips_zero_blank_and_garbage():
    rows = [
        {"date": "2026-06-10", "ticker": "IEF", "avg_cost": "95.3936"},
        {"date": "2026-09-20", "ticker": "IEF", "avg_cost": ""},
        {"date": "2026-09-21", "ticker": "IEF", "avg_cost": "0"},
        {"date": "2026-09-22", "ticker": "IEF", "avg_cost": "n/a"},
        {"date": "2026-09-23", "ticker": "IEF", "avg_cost": "-3"},
    ]
    assert avg_cost_index(rows)["IEF"] == pytest.approx(95.3936)


def test_index_omits_ticker_that_never_had_a_cost():
    rows = [{"date": "2026-09-23", "ticker": "FPS", "avg_cost": "0"}]
    assert "FPS" not in avg_cost_index(rows)


# ── resolve_cost_and_upl ─────────────────────────────────────────────────────

def test_uses_the_rows_own_cost_when_present():
    cost, upl = resolve_cost_and_upl("29.5703", 105.0, 33.74, "SCHD", {})
    assert cost == pytest.approx(29.5703)
    assert upl == pytest.approx((33.74 - 29.5703) * 105.0)


def test_falls_back_to_the_index_when_the_row_is_zero():
    cost, upl = resolve_cost_and_upl("0", 105.0, 33.74, "SCHD", {"SCHD": 29.5703})
    assert cost == pytest.approx(29.5703)
    assert upl == pytest.approx(437.82, abs=0.01)


def test_unknown_cost_yields_no_number_at_all():
    """The whole point: silence, not a confident wrong number."""
    assert resolve_cost_and_upl("0", 15.0, 38.52, "FPS", {}) == (None, None)


def test_regression_zero_cost_never_reports_market_value_as_profit():
    """The exact production shape: C6L, 100 @ 6.57, avg_cost wiped to 0.

    The bug returned upl == 657.00 (the entire position as gain). With a
    recoverable history it must return the real +19.27; with no history it
    must return nothing.
    """
    _, upl_recovered = resolve_cost_and_upl("0", 100.0, 6.57, "C6L", {"C6L": 6.3773})
    assert upl_recovered == pytest.approx(19.27, abs=0.01)
    assert upl_recovered != pytest.approx(657.00)

    _, upl_unknown = resolve_cost_and_upl("0", 100.0, 6.57, "C6L", {})
    assert upl_unknown is None


def test_short_position_cost_basis_still_works():
    cost, upl = resolve_cost_and_upl("5.00", -100.0, 4.00, "XYZ", {})
    assert upl == pytest.approx(100.0)   # short, price fell → gain


# ── Flex cost price ──────────────────────────────────────────────────────────

def test_flex_prefers_cost_basis_price():
    assert flex_cost_price({"cost_price": 29.57, "cost_money": 9999.0,
                            "qty": 105.0}) == pytest.approx(29.57)


def test_flex_derives_price_from_cost_money_when_price_missing():
    """The actual Flex failure: costBasisPrice empty, costBasisMoney present."""
    assert flex_cost_price({"cost_price": 0.0, "cost_money": 3105.0,
                            "qty": 105.0}) == pytest.approx(29.5714, abs=1e-4)


def test_flex_handles_short_quantities():
    assert flex_cost_price({"cost_price": 0.0, "cost_money": -500.0,
                            "qty": -100.0}) == pytest.approx(5.0)


def test_flex_returns_zero_rather_than_dividing_by_zero():
    assert flex_cost_price({"cost_price": 0.0, "cost_money": 100.0, "qty": 0.0}) == 0.0
    assert flex_cost_price({"cost_price": 0.0, "cost_money": 0.0, "qty": 10.0}) == 0.0


def test_flex_option_cost_money_is_divided_by_the_multiplier():
    """costBasisMoney already contains the multiplier.

    A 100-lot short put opened for $5.00/share carries costBasisMoney 500 on
    qty 1, multiplier 100. Dividing by qty alone returns 500 — per CONTRACT —
    and _flex_option_row then multiplies by 100 again, booking a $50,000 cost
    basis on a $500 position.
    """
    row = {"cost_price": 0.0, "cost_money": -500.0, "qty": -1.0}
    assert flex_cost_price(row, 100) == pytest.approx(5.0)
    assert flex_cost_price(row, 100) != pytest.approx(500.0)


def test_flex_multiplier_defaults_to_one_for_stocks():
    row = {"cost_price": 0.0, "cost_money": 3105.0, "qty": 105.0}
    assert flex_cost_price(row) == flex_cost_price(row, 1)


def test_flex_zero_multiplier_does_not_divide_by_zero():
    assert flex_cost_price({"cost_price": 0.0, "cost_money": 100.0, "qty": 10.0}, 0) == 0.0
