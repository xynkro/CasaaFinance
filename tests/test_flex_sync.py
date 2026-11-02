"""Tests for the Flex → PortfolioGrab JSON bridge (headless position sync)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ibkr_flex_sync import (
    _flex_option_row,
    _flex_stock_row,
    build_flex_grab,
)


def _stk(symbol="SCHD", qty=105, mark=32.39, cost=32.69, value=3401.0, upl=0.0):
    return {"account": "U6773281", "asset": "STK", "symbol": symbol, "qty": qty,
            "mark": mark, "value": value, "cost_price": cost, "cost_money": cost * qty,
            "upl": upl, "put_call": "", "strike": "", "expiry": "",
            "multiplier": "", "underlying": ""}


def _opt(qty=-3, pc="P", strike="190", mark=1.77, cost=2.99, upl=0.0):
    return {"account": "U6773281", "asset": "OPT", "symbol": "NVDA 260702P190",
            "qty": qty, "mark": mark, "value": mark * qty * 100,
            "cost_price": cost, "cost_money": cost * qty * 100, "upl": upl,
            "put_call": pc, "strike": strike, "expiry": "2026-07-02",
            "multiplier": "100", "underlying": "NVDA"}


class TestRowMapping:
    def test_stock_row_shape_and_upl_compute(self):
        r = _flex_stock_row(_stk(), nlv=10110.0)
        assert r["sec_type"] == "STK" and r["symbol"] == "SCHD"
        # fifo upl absent (0) → computed from mark vs cost
        assert r["upl"] == round((32.39 - 32.69) * 105, 2)
        assert r["weight_pct"] == round(3401.0 / 10110.0 * 100, 2)

    def test_option_cost_scales_to_per_contract(self):
        """Flex costBasisPrice is per share; grab schema carries per contract."""
        r = _flex_option_row(_opt())
        assert r["avg_cost"] == round(2.99 * 100, 2)
        assert r["side"] == "short_put"
        assert r["right"] == "P" and r["strike"] == 190.0
        assert r["expiry"] == "20260702"          # dashes stripped
        # upl computed per contract: (mark - cost) * qty * 100
        assert r["upl"] == round((1.77 - 2.99) * -3 * 100, 2)

    def test_long_call_side(self):
        r = _flex_option_row(_opt(qty=2, pc="C"))
        assert r["side"] == "long_call"


class TestBuildFlexGrab:
    def test_sarah_carried_forward_never_clobbered(self):
        prev = {"accounts": {"sarah": {"account_id": "U16000287",
                                       "positions": [{"symbol": "AAPL"}],
                                       "summary": {"net_liquidation_sgd": 60152.0},
                                       "options": [], "trades": []},
                             "caspar": {"summary": {"buying_power": 1905.71,
                                                    "excess_liquidity": 1908.09}}}}
        grab = build_flex_grab({"account": "U6773281", "nlv": 10110.0, "cash": 69.0, "currency": "USD"},
                               [_stk(), _opt()], prev)
        assert grab["accounts"]["sarah"]["positions"] == [{"symbol": "AAPL"}]
        assert grab["writer"] == "ibkr_flex_sync.py"
        c = grab["accounts"]["caspar"]
        assert c["summary"]["net_liquidation"] == 10110.0
        # margin fields Flex lacks are carried from the previous grab, not 0
        assert c["summary"]["buying_power"] == 1905.71
        assert len(c["positions"]) == 1 and len(c["options"]) == 1

    def test_no_prior_grab_yields_empty_sarah(self):
        grab = build_flex_grab({"account": "U6773281", "nlv": 100.0, "currency": "USD"}, [], {})
        assert grab["accounts"]["sarah"]["positions"] == []
        assert grab["accounts"]["caspar"]["summary"]["buying_power"] == 0.0


class TestCasparSummaryIsInUsd:
    """His base is SGD; the Sheet's columns and everything reading them mean USD."""

    @staticmethod
    def _row(symbol, currency, value, upl, fx=None):
        return {"account": "U6773281", "asset": "STK", "symbol": symbol, "qty": 10.0, "mark": value / 10,
                "value": value, "cost_price": 1.0, "cost_money": 10.0, "upl": upl,
                "currency": currency, "fx_to_base": fx}

    def test_sgd_base_converts_totals_and_weights_with_the_statements_own_rate(self):
        rows = [self._row("AAA", "USD", 1000.0, 100.0, fx=1.25), self._row("C6L", "SGD", 500.0, 50.0, fx=1.0)]
        grab = build_flex_grab({"account": "U6773281", "nlv": 2500.0, "cash": 125.0, "stock": 1750.0,
                                "currency": "SGD"}, rows, {})
        c = grab["accounts"]["caspar"]
        s = c["summary"]
        assert (c["base_currency"], c["summary_currency"]) == ("SGD", "USD")
        assert (s["net_liquidation"], s["total_cash"], s["total_market_value"]) == (2000.0, 100.0, 1400.0)
        assert s["unrealized_pnl"] == 140.0                     # 100 USD + 50 SGD
        weights = {r["symbol"]: r["weight_pct"] for r in c["positions"]}
        assert weights == {"AAA": 50.0, "C6L": 20.0}            # 1000/2000, then 400/2000
        assert {r["symbol"]: r["mkt_val"] for r in c["positions"]} == {"AAA": 1000.0, "C6L": 500.0}

    def test_a_report_that_names_no_currency_is_treated_as_his_sgd_base(self):
        rows = [self._row("AAA", "", 1000.0, 0.0), self._row("C6L", "", 500.0, 0.0)]
        grab = build_flex_grab({"account": "U6773281", "nlv": 2500.0, "cash": 125.0}, rows, {},
                               fetch_rate=lambda: 1.25)
        c = grab["accounts"]["caspar"]
        assert c["summary"]["net_liquidation"] == 2000.0
        assert {r["symbol"]: r["weight_pct"] for r in c["positions"]} == {"AAA": 50.0, "C6L": 20.0}

    def test_no_rate_means_no_snapshot_rather_than_a_guess(self):
        import pytest
        with pytest.raises(RuntimeError, match="no USD/SGD rate"):
            build_flex_grab({"account": "U6773281", "nlv": 2500.0, "currency": "SGD"}, [], {},
                            fetch_rate=lambda: None)
        with pytest.raises(RuntimeError, match="unsupported base currency"):
            build_flex_grab({"account": "U6773281", "nlv": 2500.0, "currency": "EUR"}, [], {})

