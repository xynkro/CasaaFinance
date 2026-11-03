"""The put list per book: what a book's cash can actually secure, how a line is
priced and ranked, the scan pass that finds them, and how they reach the DM and app.
All tickers and amounts are made up."""
from __future__ import annotations

import csv
import json
import logging
import shutil
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scripts import daily_ideas_dm as dm_script
from scripts import daily_options_scan as dos
from src import daily_ideas as di
from src import put_lines as pl

TODAY = "2026-11-03"
FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "daily_ideas"


def _line(ticker="AAA", strike=10.0, expiry="2026-12-18", bid=0.40, ask=0.44, under=11.5, delta=-0.25, **kw):
    dte = (date.fromisoformat(expiry) - date.fromisoformat(TODAY)).days
    return pl.PutLine(ticker=ticker, strike=strike, expiry=expiry, dte=dte, delta=delta, bid=bid, ask=ask,
                      premium=(bid + ask) / 2, underlying=under, scanned_at="2026-11-02T233000", **kw)


def _row(ticker="AAA", when="2026-11-02T233000", strike=10, expiry="20261218", strategy="CSP", **kw):
    return {"date": when, "ticker": ticker, "strategy": strategy, "strike": strike, "expiry": expiry,
            "delta": -0.25, "bid": 0.40, "ask": 0.44, "premium": 0.42, "underlying_last": 11.5,
            "notes": "", "signals_json": "", **kw}


# ── pricing a line ──────────────────────────────────────────────────────────

def test_a_sell_is_priced_up_from_the_bid_not_at_the_mid():
    ln = _line(bid=0.40, ask=0.48)
    assert ln.fill == pytest.approx(0.42)
    assert ln.credit == pytest.approx(42)
    assert ln.collateral == 1000
    assert ln.breakeven == pytest.approx(9.58)


def test_cushion_is_to_the_breakeven_and_yield_uses_the_fill():
    ln = _line(strike=10, bid=0.40, ask=0.40, under=12.5)
    assert ln.cushion == pytest.approx(1 - 9.6 / 12.5)
    assert ln.ann_yield == pytest.approx(0.40 / 10 * 365 / 45)


def test_no_quote_falls_back_to_the_last_trade():
    ln = _line(bid=0, ask=0)
    ln.premium = 0.33
    assert not ln.quoted
    assert ln.fill == 0.33


def test_spread_limit_allows_one_tick_on_a_cheap_option():
    assert pl.spread_ok(0.40, 0.48)            # 18% of the mid
    assert not pl.spread_ok(0.40, 2.05)        # the kind of quote the old list ranked on its mid
    assert pl.spread_ok(0.15, 0.25)            # 50% of the mid, but only $0.10


# ── reading the scan ────────────────────────────────────────────────────────

def test_parse_keeps_each_tickers_newest_scan_only():
    rows = [_row(when="2026-10-31T233000", strike=9), _row(when="2026-11-02T233000", strike=10),
            _row("BBB", when="2026-10-31T233000")]
    got = {(ln.ticker, ln.strike) for ln in pl.parse_scan_rows(rows, TODAY)}
    assert got == {("AAA", 10), ("BBB", 10)}


def test_parse_keeps_rows_of_one_run_seconds_apart():
    rows = [_row(when="2026-11-02T233000", strike=10), _row(when="2026-11-02T233500", strike=9)]
    assert {ln.strike for ln in pl.parse_scan_rows(rows, TODAY)} == {9, 10}


def test_parse_drops_old_scans_other_strategies_and_close_expiries():
    rows = [_row(when="2026-10-20T233000"), _row("BBB", strategy="CC"), _row("CCC", expiry="20261106")]
    assert pl.parse_scan_rows(rows, TODAY) == []


def test_parse_reads_earnings_per_share_kind_and_flow():
    rows = [_row(signals_json=json.dumps({"rsi": 0.1, "eps": -1.5, "is_etf": 0.0}),
                 notes="⚠ SELL_CAUTION | 🟧 ADVERSE FLOW: LONG_PUT x2d | size S:1x"),
            _row("ETF1", signals_json=json.dumps({"is_etf": 1.0})), _row("OLD", signals_json="not json")]
    by = {ln.ticker: ln for ln in pl.parse_scan_rows(rows, TODAY)}
    assert by["AAA"].loses_money and by["AAA"].kind == "stock"
    assert by["AAA"].flow == "🟧 ADVERSE FLOW: LONG_PUT x2d"
    assert by["ETF1"].kind == "ETF"
    assert by["OLD"].kind == "" and by["OLD"].eps is None


# ── bringing a line up to date ──────────────────────────────────────────────

def test_a_big_move_since_the_quote_drops_the_line():
    assert "moved −6%" in pl.check_line(_line(under=11.5), 10.8, [], "", "", TODAY).replace("-", "−")


def test_a_small_move_updates_the_stock_price():
    ln = _line(under=11.5)
    assert pl.check_line(ln, 11.3, ["2027-02-01"], "", "", TODAY) is None
    assert ln.underlying == 11.3 and ln.moved == pytest.approx(11.3 / 11.5 - 1)


def test_no_cushion_left_drops_the_line():
    assert pl.check_line(_line(strike=10, under=10.3), 10.1, [], "", "", TODAY) == "no cushion left"


def test_a_wide_spread_drops_the_line_but_no_quote_does_not():
    assert pl.check_line(_line(bid=0.40, ask=2.05), None, [], "", "", TODAY) == "spread too wide"
    assert pl.check_line(_line(bid=0, ask=0), None, ["2027-02-01"], "", "", TODAY) is None


def test_earnings_before_expiry_drops_the_line():
    assert "earnings 2026-12-10" in pl.check_line(_line(), None, ["2026-12-10"], "", "", TODAY)


def test_earnings_after_expiry_is_clear():
    ln = _line()
    assert pl.check_line(ln, None, ["2027-02-01"], "2026-10-28", "", TODAY) is None
    assert ln.earnings == "clear" and ln.last_report == "2026-10-28"


def test_a_recent_report_means_the_next_cant_land_before_expiry():
    ln = _line()
    pl.check_line(ln, None, [], "2026-10-28", "", TODAY)
    assert ln.earnings == "clear"


def test_no_dates_at_all_is_unknown_never_clear():
    ln = _line()
    pl.check_line(ln, None, [], "", "", TODAY)
    assert ln.earnings == "unknown"


def test_an_old_report_with_nothing_ahead_is_unknown():
    ln = _line()
    pl.check_line(ln, None, [], "2026-08-01", "", TODAY)
    assert ln.earnings == "unknown"


def test_an_etf_has_no_earnings():
    ln = _line()
    assert pl.check_line(ln, None, [], "", "ETF", TODAY) is None
    assert ln.earnings == "none"


# ── ranking ─────────────────────────────────────────────────────────────────

def _checked(**kw):
    ln = _line(**kw)
    ln.earnings = "clear"
    return ln


def test_rank_order():
    no_quote = _checked(ticker="NOQ", bid=0, ask=0)
    unknown = _checked(ticker="UNK", under=13.0)
    unknown.earnings = "unknown"
    flow = _checked(ticker="FLO", under=13.0, flow="🟧 ADVERSE FLOW: LONG_PUT x1d")
    loser = _checked(ticker="LOS", under=13.0, eps=-1.0)
    thin = _checked(ticker="THI", under=10.6)                  # under the 9% cushion
    rich = _checked(ticker="RIC", under=13.0, bid=0.60, ask=0.64)
    plain = _checked(ticker="PLA", under=13.0)
    ordered = sorted([no_quote, unknown, flow, loser, thin, rich, plain], key=pl.rank)
    assert [ln.ticker for ln in ordered] == ["RIC", "PLA", "THI", "LOS", "FLO", "UNK", "NOQ"]


# ── per book ────────────────────────────────────────────────────────────────

def test_a_line_fits_on_its_full_strike_not_on_the_account_value():
    bp = pl.for_book([_checked(strike=16, under=18)], cash_usd=1070, deposit_usd=0, nlv_usd=50_000,
                     weights={}, cap=0.30)
    assert bp.fits == [] and bp.cheapest.strike == 16


def test_fits_rung_and_cheapest():
    lines = [_checked(ticker="SMA", strike=9, under=10.5), _checked(ticker="MID", strike=15, under=17),
             _checked(ticker="BIG", strike=50, under=55)]
    bp = pl.for_book(lines, cash_usd=1000, deposit_usd=2000, nlv_usd=50_000, weights={}, cap=0.30)
    assert [ln.ticker for ln in bp.fits] == ["SMA"]
    assert [ln.ticker for ln in bp.rung] == ["MID"]
    assert bp.cheapest is None      # something fits, so nothing needs saying


def test_nothing_fits_names_the_smallest_line():
    lines = [_checked(ticker="MID", strike=15, under=17), _checked(ticker="BIG", strike=50, under=55)]
    bp = pl.for_book(lines, cash_usd=60, deposit_usd=400, nlv_usd=9_000, weights={}, cap=0.30)
    assert bp.fits == [] and bp.rung == []
    assert bp.cheapest.ticker == "MID"


def test_one_line_per_ticker_best_first_and_capped():
    lines = [_checked(ticker="AAA", strike=9, under=10.5), _checked(ticker="AAA", strike=8, under=10.5)]
    lines += [_checked(ticker=t, strike=8, under=10) for t in ("BBB", "CCC", "DDD", "EEE")]
    bp = pl.for_book(lines, cash_usd=5000, deposit_usd=0, nlv_usd=50_000, weights={}, cap=0.30)
    assert len(bp.fits) == pl.MAX_PER_BOOK
    assert len({ln.ticker for ln in bp.fits}) == pl.MAX_PER_BOOK


def test_assignment_cant_take_a_name_past_the_cap():
    bp = pl.for_book([_checked(strike=20, under=23)], cash_usd=5000, deposit_usd=0, nlv_usd=10_000,
                     weights={"AAA": 0.15}, cap=0.30)
    assert bp.fits == []            # 15% held + 20% if assigned
    bp = pl.for_book([_checked(strike=20, under=23)], cash_usd=5000, deposit_usd=0, nlv_usd=10_000,
                     weights={"AAA": 0.05}, cap=0.30)
    assert len(bp.fits) == 1


# ── graded record ───────────────────────────────────────────────────────────

def _outcome(ticker="AAA", strike=10, expiry=20261218, scan="2026-05-01", ev="2026-06-01", pnl=2.0,
             outcome="WIN", price=11, strategy="CSP", model="premium_v2"):
    return {"ticker": ticker, "strike": strike, "expiry": expiry, "scan_date": scan, "eval_date": ev,
            "outcome_pnl_pct": pnl, "strategy_outcome": outcome, "price_at_scan": price,
            "strategy": strategy, "pnl_model": model}


def test_a_contract_scanned_for_days_counts_once():
    rows = [_outcome(scan=f"2026-05-0{i}") for i in range(1, 6)]
    assert len(pl.graded_contracts(rows)) == 1


def test_a_contract_keeps_first_scan_price_and_final_result():
    rows = [_outcome(ev="2026-05-20", pnl=1.0, price=11), _outcome(scan="2026-05-09", ev="2026-06-01", pnl=-7.0,
                                                                   outcome="LOSS", price=30)]
    g = pl.graded_contracts(rows)[0]
    assert g["price"] == 11 and g["pnl"] == -7.0 and not g["won"]


def test_other_strategies_and_old_models_are_left_out():
    rows = [_outcome(strategy="CC"), _outcome(model="stock_proxy_v1"), _outcome(pnl="")]
    assert pl.graded_contracts(rows) == []


def test_record_text_uses_the_cheap_stock_band_only_when_every_line_is_in_it():
    graded = pl.graded_contracts([_outcome("AAA", pnl=3.0, price=11),
                                  _outcome("BBB", pnl=-8.0, outcome="LOSS", price=100)])
    cheap = pl.record_text(graded, [_line(under=11)])
    assert "stocks under $25: 1," in cheap and "100% kept" in cheap
    mixed = pl.record_text(graded, [_line(under=11), _line(under=30)])
    assert "put lines: 2," in mixed and "50% lost over 5%" in mixed and "worst −8%" in mixed


# ── the scan pass ───────────────────────────────────────────────────────────

def test_caps_are_each_books_cash_with_and_without_the_deposit():
    states = {"a": {"cash": 60.0, "deposit": 390.0}, "b": {"cash": 1000.0, "deposit": 2300.0}}
    assert dos.cash_fit_caps(states) == [4.5, 10.0, 33.0]


def test_a_book_with_no_real_cash_adds_no_cap():
    assert dos.cash_fit_caps({"a": {"cash": 60.0, "deposit": 0.0}}) == []


def test_expiries_try_monthlies_first_and_skip_the_exit_window():
    got = dos.cash_fit_expiries(("2026-11-13", "2026-11-20", "2026-12-04", "2026-12-11", "2026-12-18"),
                                today=date(2026, 11, 3))
    assert got == ["2026-12-18", "2026-12-11", "2026-12-04"]


def _chain(rows):
    return pd.DataFrame([{"contractSymbol": sym, "strike": k, "bid": b, "ask": a, "lastPrice": last,
                          "openInterest": oi} for sym, k, b, a, last, oi in rows])


def _sym(k, root="AAA"):
    return f"{root}261218P{int(k * 1000):08d}"


PRICE, DTE = 11.5, 45


def test_pick_stays_under_the_cash_limit():
    chain = _chain([(_sym(11), 11, 0.70, 0.74, 0, 500), (_sym(10), 10, 0.30, 0.34, 0, 500)])
    r = dos.pick_cash_fit_put(chain, "AAA", "2026-12-18", PRICE, DTE, cap=10.5)
    assert float(r["strike"]) == 10


def test_pick_returns_none_when_no_strike_fits():
    chain = _chain([(_sym(11), 11, 0.70, 0.74, 0, 500)])
    assert dos.pick_cash_fit_put(chain, "AAA", "2026-12-18", PRICE, DTE, cap=9) is None


def test_pick_skips_adjusted_contracts():
    chain = _chain([(_sym(10, root="AAA1"), 10, 0.30, 0.34, 0, 500)])
    assert dos.pick_cash_fit_put(chain, "AAA", "2026-12-18", PRICE, DTE, cap=10.5) is None


def test_pick_skips_an_ask_with_no_bid_but_keeps_an_off_hours_last_trade():
    chain = _chain([(_sym(10), 10, 0, 0.90, 0, 500)])
    assert dos.pick_cash_fit_put(chain, "AAA", "2026-12-18", PRICE, DTE, cap=10.5) is None
    chain = _chain([(_sym(10), 10, 0, 0, 0.32, 500)])
    assert float(dos.pick_cash_fit_put(chain, "AAA", "2026-12-18", PRICE, DTE, cap=10.5)["strike"]) == 10


def test_pick_skips_thin_open_interest():
    chain = _chain([(_sym(10), 10, 0.30, 0.34, 0, 3)])
    assert dos.pick_cash_fit_put(chain, "AAA", "2026-12-18", PRICE, DTE, cap=10.5) is None


def test_cash_account_size_caps_at_its_cash():
    states = {"s": {"nlv": 50_000.0, "is_margin": False, "profile": "balanced", "excess_liq": None, "cash": 1070.0}}
    c = {"strategy": "CSP", "strike": 16.0, "underlying_last": 18.0, "premium": 0.4}
    assert "S:0x" in dos._sizing_note(c, states, {"vix": 15.0, "spx_above_200sma": True})
    states["s"]["cash"] = 3300.0
    assert "S:0x" not in dos._sizing_note(c, states, {"vix": 15.0, "spx_above_200sma": True})


def test_scan_logs_never_show_a_cash_limit(caplog, monkeypatch):
    calls = []
    monkeypatch.setattr(dos, "_yahoo_screen", lambda *a: calls.append(a) or [{"symbol": "AAA"}])
    monkeypatch.setattr(dos, "scan_cash_fit", lambda *a: [])
    logger = logging.getLogger("test_put_lines")
    with caplog.at_level(logging.DEBUG, logger=logger.name):
        dos.run_cash_fit(logger, {"s": {"cash": 1234.0, "deposit": 2000.0}}, set(), {})
    assert len(calls) == 2              # one list per cash level
    assert not any(x in caplog.text for x in ("1234", "12.34", "32.34", "17.6", "46.2"))


def test_discovery_falls_back_when_the_screener_fails(monkeypatch):
    def boom(*a):
        raise RuntimeError("down")
    monkeypatch.setattr(dos, "_yahoo_screen", boom)
    assert dos.discover_universe(logging.getLogger("t"), top_n=3) == dos.FALLBACK_HIGH_IV_UNIVERSE[:3]


# ── into the DM and the app ─────────────────────────────────────────────────

ET = ZoneInfo("America/New_York")


def _dm(puts, phase="preopen", prior=None, cash=1000.0):
    acct = di.Account("sarah", "USD", nlv=50_000, cash=cash, deposit=2000, deposit_ccy="USD")
    return di.build_dm(now_et=datetime(2026, 11, 3, 8, 45, tzinfo=ET), today=TODAY, records={}, wsr=[], uoa=[],
                       gov=None, momentum=[], bars={}, accounts=[acct], sgd_per_usd=1.28, kinds={}, earnings={},
                       blocked=[], phase=phase, prior_cards=prior, puts={"sarah": puts},
                       put_records={"sarah": "Graded put lines: 9."})


def test_dm_shows_the_order_the_cost_and_the_risk():
    ln = _checked(strike=9, under=10.5, bid=0.40, ask=0.44)
    dm = _dm(pl.BookPuts(fits=[ln]))
    text = dm.puts_text
    assert text.startswith("🪙 <b>Puts this cash covers · Tue 3 Nov · 08:45 ET")
    assert "Quotes Mon 2 Nov 10:30 ET · 23:30 SGT" in text
    assert "<b>👤 Sarah</b> — $1k cash" in text
    assert "<b>P1 · AAA</b> · Sell 1× 18 Dec $9 put, limit ≥ $0.41 (bid 0.40 · ask 0.44)" in text
    assert "Collect ≈ $41 · puts up $900 (1.8% of the book) · breakeven $8.59, 18% under $10.50" in text
    assert "about 25% odds of assignment · earnings clear" in text
    assert "buy back at 50% of the credit" in text
    assert "Graded put lines: 9." in text
    assert "1 put" in dm.text and "AAA" not in dm.text      # the plan only counts them


def test_puts_warn_when_the_books_cash_is_stale():
    acct = di.Account("sarah", "USD", nlv=50_000, cash=1000, stale_since="2026-06-04")
    dm = di.build_dm(now_et=datetime(2026, 11, 3, 8, 45, tzinfo=ET), today=TODAY, records={}, wsr=[], uoa=[],
                     gov=None, momentum=[], bars={}, accounts=[acct], sgd_per_usd=1.28, kinds={}, earnings={},
                     blocked=[], phase="preopen", puts={"sarah": pl.BookPuts(fits=[_checked(strike=9, under=10.5)])})
    assert "⚠ Cash unchanged since 4 Jun: check it against IBKR first." in dm.puts_text


def test_dm_flags_what_should_give_pause():
    ln = _checked(strike=9, under=10.5, eps=-1.5, flow="🟧 ADVERSE FLOW: LONG_PUT x2d")
    ln.earnings = "unknown"
    text = _dm(pl.BookPuts(fits=[ln])).puts_text
    assert "⚠ No earnings date found" in text
    assert "🟧 Heavy put buying on AAA for 2 days" in text
    assert "⚠ Losing money (EPS −1.50): if assigned, it stays in the book" in text


def test_dm_says_when_quotes_are_only_the_last_close():
    ln = _checked(strike=9, under=10.5)
    ln.scanned_at = "2026-11-03T130000"       # 00:00 ET, market shut
    assert "Last close's quotes" in _dm(pl.BookPuts(fits=[ln])).puts_text


def test_dm_says_how_much_nothing_needs():
    ln = _checked(ticker="BIG", strike=50, under=55)
    text = _dm(pl.BookPuts(cheapest=ln), cash=60).puts_text
    assert "None fit this cash. Smallest on the list: BIG $50 needs $5,000." in text
    assert "<b>P1" not in text


def test_dm_names_the_lines_the_deposit_would_cover():
    ln = _checked(ticker="MID", strike=15, under=17)
    text = _dm(pl.BookPuts(rung=[ln], cheapest=ln)).puts_text
    assert "With the $2k deposit: MID $15." in text


def test_no_scan_means_no_put_block():
    acct = di.Account("sarah", "USD", nlv=50_000, cash=1000)
    dm = di.build_dm(now_et=datetime(2026, 11, 3, 8, 45, tzinfo=ET), today=TODAY, records={}, wsr=[], uoa=[],
                     gov=None, momentum=[], bars={}, accounts=[acct], sgd_per_usd=1.28, kinds={}, earnings={},
                     blocked=[], phase="preopen")
    assert "Puts" not in dm.text and dm.puts_text == ""


def test_app_cards_carry_the_dms_strings():
    ln = _checked(strike=9, under=10.5)
    dm = _dm(pl.BookPuts(fits=[ln]))
    card = next(c for c in dm.cards if c["section"] == "put")
    assert card["account"] == "Sarah" and card["num"] == "P1" and card["ticker"] == "AAA"
    assert card["plan"] in dm.puts_text and card["stop"] in dm.puts_text and card["size"] in dm.puts_text
    assert card["record"] == "Graded put lines: 9."
    assert any(c["section"] == "put_note" and c["plan"] == di.PUT_MANAGE for c in dm.cards)


def _put_row(ticker, strike, bid, ask, under):
    return {"date": "2026-10-30T233000", "ticker": ticker, "strategy": "CSP", "right": "P", "strike": strike,
            "expiry": "20261218", "delta": -0.25, "premium": round((bid + ask) / 2, 2), "bid": bid, "ask": ask,
            "underlying_last": under, "notes": "cash-fit",
            "signals_json": json.dumps({"cash_fit": 1.0, "is_etf": 0.0, "eps": 0.5})}


def _write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


@pytest.fixture
def puts_fixture(tmp_path):
    """The DM's synthetic fixture, plus a scan and a graded record."""
    d = tmp_path / "f"
    shutil.copytree(FIXTURE, d)
    _write_csv(d / "scan_results.csv", [
        _put_row("PUA", 10, 0.40, 0.44, 11.5),      # covered by the bigger book's cash
        _put_row("PUB", 9, 0.30, 0.34, 10.2),       # no live quote at the re-check: dropped
        _put_row("PUC", 25, 0.70, 0.74, 28.0),      # covered once the deposit lands
        _put_row("PUD", 60, 1.40, 1.50, 66.0),      # over both books' money
    ])
    _write_csv(d / "signal_outcomes.csv", [
        _outcome("PUA", pnl=3.0, price=11), _outcome("PUC", strike=20, pnl=-6.0, outcome="LOSS", price=22)])
    meta = json.loads((d / "meta.json").read_text())
    meta["options"].update({"PUA|2026-12-18|10": {"bid": 0.42, "ask": 0.46},
                            "PUC|2026-12-18|25": {"bid": 0.72, "ask": 0.78}})
    meta["yahoo_earnings"].update({"PUA": [["2027-01-27", False], ["2026-10-28", True]],
                                   "PUC": [["2027-02-02", False], ["2026-10-22", True]]})
    (d / "meta.json").write_text(json.dumps(meta))
    return d


def test_fixture_run_lists_puts_per_book(capsys, monkeypatch, puts_fixture):
    monkeypatch.delenv("GROWTH_LEG_ENABLED", raising=False)
    assert dm_script.main(["--fixture", str(puts_fixture)]) == 0
    out = capsys.readouterr().out
    plan, puts = out.split("🪙")
    caspar, sarah = puts.split("<b>👤 Sarah</b>")
    assert "None fit this cash. Smallest on the list: PUA $10 needs $1,000." in caspar
    assert "<b>P1 · PUA</b> · Sell 1× 18 Dec $10 put, limit ≥ $0.43 (bid 0.42 · ask 0.46)" in sarah
    assert "Live quotes" in puts
    assert "With the S$2.5k deposit: PUC $25." in sarah
    assert "PUB" not in out                 # no live quote at the re-check
    assert "Graded puts on stocks under $25: 2," in sarah
    assert "trimmed" not in out




def test_recheck_says_when_a_put_comes_or_goes():
    old = _checked(ticker="OLD", strike=9, under=10.5)
    prior = _dm(pl.BookPuts(fits=[old])).cards
    new = _checked(ticker="NEW", strike=9, under=10.5)
    new.live = True
    dm = _dm(pl.BookPuts(fits=[new]), phase="open", prior=prior)
    assert "new: Sarah NEW SELL $9 PUT" in dm.text and "gone: Sarah OLD SELL $9 PUT" in dm.text
    assert "Live quotes" in dm.puts_text


def test_recheck_stays_quiet_when_the_puts_hold():
    ln = _checked(strike=9, under=10.5)
    prior = _dm(pl.BookPuts(fits=[ln])).cards
    assert _dm(pl.BookPuts(fits=[ln]), phase="open", prior=prior).puts_text == ""
