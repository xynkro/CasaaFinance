"""Hold list — names Caspar keeps regardless of the engine.

2026-10-09: "if its already loser dont realize those losses by selling just
leave it." The engine had queued OPEN TRIM daily since 2026-09-21. These tests
pin that a held (account, ticker) is exempt from sell-side recs in BOTH shapes
that carry them — the brain's dicts (push_decisions) and trigger_alerts'
Decision dataclasses — while buys on the same name, and sells on other
accounts, pass through untouched.
"""
from dataclasses import dataclass

import pytest

from src.hold_list import (HOLD_LIST_TAB, HOLD_SELL_STRATEGIES, drop_held_sell_recs,
                           hold_key, is_held, is_sell_rec, read_hold_list)
from src.schema import HoldListRow


# ── schema / tab wiring ──────────────────────────────────────────────────────

def test_tab_name_agrees_with_schema():
    assert HoldListRow.TAB_NAME == HOLD_LIST_TAB == "hold_list"


def test_row_normalises_account_and_ticker():
    r = HoldListRow(date="2026-10-09", account=" Caspar ", ticker=" open ", note="hold")
    assert r.to_row(audit=False) == ["2026-10-09", "caspar", "OPEN", "hold"]


# ── key + predicates ─────────────────────────────────────────────────────────

def test_hold_key_is_case_and_whitespace_insensitive():
    assert hold_key(" CASPAR ", " open ") == ("caspar", "OPEN")


def test_sell_recs_are_trim_and_cc_only():
    assert HOLD_SELL_STRATEGIES == {"TRIM", "CC"}
    assert is_sell_rec("trim") and is_sell_rec("CC")
    for s in ("BUY_DIP", "CSP", "PMCC", "LONG_CALL", "", None):
        assert not is_sell_rec(s)


def test_is_held_matches_exact_account():
    holds = {("caspar", "OPEN")}
    assert is_held("caspar", "open", holds)
    assert not is_held("sarah", "OPEN", holds)


def test_wildcard_account_holds_for_everyone():
    holds = {("*", "SLV")}
    assert is_held("caspar", "SLV", holds) and is_held("sarah", "slv", holds)


def test_empty_list_or_blank_ticker_is_never_held():
    assert not is_held("caspar", "OPEN", set())
    assert not is_held("caspar", "", {("caspar", "")})


# ── read_hold_list (fail OPEN) ───────────────────────────────────────────────

class _WS:
    def __init__(self, vals): self._v = vals
    def get_all_values(self): return self._v


class _SS:
    def __init__(self, vals=None, raise_=False): self._v, self._r = vals, raise_
    def worksheet(self, name):
        if self._r: raise KeyError(name)
        return _WS(self._v)


def test_read_parses_rows_and_normalises():
    ss = _SS([["date", "account", "ticker", "note"],
              ["2026-10-09", "Caspar", "open", "hold"],
              ["2026-10-09", "caspar", "BBAI", ""],
              ["2026-10-09", "*", "slv", "both"],
              ["2026-10-09", "caspar", "", "blank ticker ignored"]])
    assert read_hold_list(ss) == {("caspar", "OPEN"), ("caspar", "BBAI"), ("*", "SLV")}


def test_missing_tab_fails_open():
    assert read_hold_list(_SS(raise_=True)) == set()


def test_empty_tab_and_missing_columns_fail_open():
    assert read_hold_list(_SS([])) == set()
    assert read_hold_list(_SS([["date", "symbol"], ["x", "OPEN"]])) == set()


# ── drop_held_sell_recs — both production shapes ─────────────────────────────

def _brain(account, ticker, strategy):
    return {"account": account, "ticker": ticker, "strategy": strategy, "conv": 5}


def test_regression_open_trim_dropped_gdx_buy_kept():
    """The exact 2026-10-09 queue: OPEN TRIM (held) must go, GDX BUY_DIP stays,
    and Sarah's TRIMs are untouched because they're not on her list."""
    holds = {("caspar", "OPEN"), ("caspar", "BBAI"), ("caspar", "RCAT"), ("caspar", "SLV")}
    items = [_brain("caspar", "OPEN", "TRIM"), _brain("caspar", "GDX", "BUY_DIP"),
             _brain("sarah", "BYND", "TRIM"), _brain("sarah", "SBET", "TRIM")]
    kept, dropped = drop_held_sell_recs(
        items, holds, account=lambda d: d["account"], ticker=lambda d: d["ticker"],
        strategy=lambda d: d["strategy"])
    assert [d["ticker"] for d in dropped] == ["OPEN"]
    assert [d["ticker"] for d in kept] == ["GDX", "BYND", "SBET"]


def test_buying_more_of_a_held_name_is_not_blocked():
    holds = {("caspar", "OPEN")}
    kept, dropped = drop_held_sell_recs(
        [_brain("caspar", "OPEN", "BUY_DIP"), _brain("caspar", "OPEN", "CSP")], holds,
        account=lambda d: d["account"], ticker=lambda d: d["ticker"], strategy=lambda d: d["strategy"])
    assert dropped == [] and len(kept) == 2


def test_cc_on_a_held_name_is_a_sell_rec_and_dropped():
    holds = {("caspar", "SLV")}
    kept, dropped = drop_held_sell_recs(
        [_brain("caspar", "SLV", "CC")], holds,
        account=lambda d: d["account"], ticker=lambda d: d["ticker"], strategy=lambda d: d["strategy"])
    assert len(dropped) == 1 and kept == []


@dataclass
class _Decision:
    account: str
    ticker: str
    strategy: str


def test_works_on_trigger_alerts_decision_shape():
    holds = {("caspar", "OPEN")}
    items = [_Decision("caspar", "OPEN", "TRIM"), _Decision("caspar", "XLP", "BUY_DIP")]
    kept, dropped = drop_held_sell_recs(
        items, holds, account=lambda d: d.account, ticker=lambda d: d.ticker,
        strategy=lambda d: d.strategy)
    assert [d.ticker for d in dropped] == ["OPEN"] and [d.ticker for d in kept] == ["XLP"]


def test_empty_hold_list_is_a_no_op():
    items = [_brain("caspar", "OPEN", "TRIM")]
    kept, dropped = drop_held_sell_recs(
        items, set(), account=lambda d: d["account"], ticker=lambda d: d["ticker"],
        strategy=lambda d: d["strategy"])
    assert kept == items and dropped == []
