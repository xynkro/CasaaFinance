"""Daily ideas DM — the rules Caspar agreed on 2026-10-31.

Grading (fill at trigger, hold 20 sessions, vs SPY, week-clustered t), the
three tiers, whole-unit sizing with the one-unit exception, cash + deposit
budget, the live re-check, the never-sell-a-loser filter, and an end-to-end
dryrun against the synthetic fixture in fixtures/daily_ideas/.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from src import daily_ideas as di
import scripts.daily_ideas_dm as dm_script

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "daily_ideas"


def _days(n: int, start: date = date(2026, 3, 2)) -> list[str]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _bars(days, closes, lows=None, opens=None):
    lows = lows or closes
    opens = opens or closes
    return di.Bars(list(days), list(opens), [max(o, c) for o, c in zip(opens, closes)],
                   list(lows), list(closes))


# ── sizing ──────────────────────────────────────────────────────────────────

def test_size_rounds_down_to_whole_units():
    assert di.size_units(1050, 239.36) == (4, False)


def test_one_unit_allowed_up_to_one_and_a_half_times_the_size():
    assert di.size_units(176, 239.36) == (1, True)      # 1.36× → allowed (mock: ZZN)


def test_no_size_beyond_one_and_a_half_times():
    assert di.size_units(176, 765) == (0, False)        # GGL contract for the small book


def test_concentration_cap_blocks_a_name_already_near_30pct():
    a = di.Account("sarah", "USD", nlv=10_000, cash=0, weights={"SPY": 0.29})
    idea = di.Idea("wsr", "SPY", "BUY", unit_cost=150.0)
    di.size_idea(idea, "yellow", [a], 1.28)
    assert idea.sizes["sarah"][0] == 0
    assert "already" in idea.sizes["sarah"][2]


# ── grading + tiers ─────────────────────────────────────────────────────────

def test_buy_dip_fills_at_trigger_and_is_graded_vs_spy():
    days = _days(40)
    spy = _bars(days, [100.0] * 40)
    # Idea on day 0 with trigger 95; day 3 dips to 94 → fill at min(95, open 96)=95.
    closes = [100, 99, 98, 96] + [110.0] * 36
    lows = [100, 99, 98, 94] + [109.0] * 36
    b = _bars(days, closes, lows=lows, opens=[100, 99, 98, 96] + [110.0] * 36)
    rec = di.grade("wsr", [di.PastIdea("wsr", "X", days[0], 95.0)], {"SPY": spy, "X": b}, "2026-12-31")
    assert rec.n == 1 and rec.beat == 1
    assert rec.mean_alpha == pytest.approx(110 / 95 - 1 - 2 * di.COST_PER_SIDE)


def test_dividends_count_in_the_graded_return():
    # Flat price, but a dividend (adj close steps down before the ex-date) —
    # total return must be positive, not zero.
    days = _days(30)
    spy = _bars(days, [100.0] * 30)
    b = _bars(days, [50.0] * 30)
    b.adj = [49.0] * 10 + [50.0] * 20
    rec = di.grade("wsr", [di.PastIdea("wsr", "III", days[0], None)], {"SPY": spy, "III": b}, "2026-12-31")
    assert rec.n == 1
    assert rec.mean_alpha == pytest.approx(50 / 49 - 1 - 2 * di.COST_PER_SIDE)


def test_a_buy_that_only_matches_spy_loses_its_costs():
    days = _days(30)
    flat = _bars(days, [100.0] * 30)
    rec = di.grade("uoa", [di.PastIdea("uoa", "X", days[0], None)], {"SPY": flat, "X": flat}, "2026-12-31")
    assert rec.n == 1 and rec.beat == 0
    assert rec.mean_alpha == pytest.approx(-2 * di.COST_PER_SIDE)
    assert "0/1 beat SPY after costs" in di.record_line(di.assign_tier(rec))


def test_a_trim_pays_its_cost_once():
    days = _days(30)
    flat = _bars(days, [100.0] * 30)
    idea = di.PastIdea("wsr_trim", "X", days[0], None, side="sell")
    rec = di.grade("wsr_trim", [idea], {"SPY": flat, "X": flat}, "2026-12-31")
    assert rec.n == 1 and rec.beat == 0
    assert rec.mean_alpha == pytest.approx(-di.COST_PER_SIDE)


def test_unfilled_dip_is_not_counted_as_a_trade():
    days = _days(40)
    spy = _bars(days, [100.0] * 40)
    b = _bars(days, [100.0] * 40)
    rec = di.grade("wsr", [di.PastIdea("wsr", "X", days[0], 90.0)], {"SPY": spy, "X": b}, "2026-12-31")
    assert rec.n == 0 and rec.unfilled == 1


def test_todays_partial_bar_never_completes_a_hold():
    days = _days(22)
    spy = _bars(days, [100.0] * 22)
    b = _bars(days, [100.0] * 22)
    rec = di.grade("uoa", [di.PastIdea("uoa", "X", days[0], None)], {"SPY": spy, "X": b}, days[-1])
    assert rec.n == 0 and rec.open == 1


def _rec(t, n=40, clusters=10, share=0.1):
    return di.Record("wsr", n=n, beat=n // 2, t=t, clusters=clusters, top_cluster_share=share)


def test_tiers():
    assert di.assign_tier(_rec(2.5)).tier == "green"
    assert di.assign_tier(_rec(-2.1)).tier == "red"
    assert di.assign_tier(_rec(-1.5)).tier == "yellow"
    assert di.assign_tier(_rec(-1.5)).near_cut


def test_one_basket_cannot_earn_green():
    # gov_lo on real data: 86 of 105 ideas from one May week.
    assert di.assign_tier(_rec(9.4, n=105, clusters=9, share=0.82)).tier == "yellow"


def test_too_few_graded_stays_on_probation():
    r = di.assign_tier(_rec(5.0, n=6, clusters=3))
    assert r.tier == "yellow" and r.note


# ── candidates ──────────────────────────────────────────────────────────────

def _row(**kw):
    base = {"date": "2026-10-28T013300", "account": "sarah", "ticker": "ZZN", "strategy": "BUY_DIP",
            "entry": "240", "target": "275", "status": "watching", "source": "wsr_lite",
            "thesis_1liner": "ZZN $253 — watching"}
    base.update(kw)
    return base


def test_live_dips_merge_books_and_prefer_full_wsr_reason():
    rows = [_row(date="2026-10-26T232050", source="wsr_full",
                 thesis_1liner="ZZN BUY_DIP $240 — post-ER add."),
            _row(),
            _row(account="caspar", date="2026-10-28T013300")]
    [idea] = di.live_wsr_dips(rows, "2026-11-02")
    assert idea.accounts == ("caspar", "sarah")
    assert idea.why == "post-ER add."
    assert idea.trigger == 240


def test_killed_and_stale_dips_are_gone():
    rows = [_row(ticker="KIL", date="2026-10-26T232050"),
            _row(ticker="KIL", status="killed"),
            _row(ticker="OLD", date="2026-10-12T232050")]
    assert di.live_wsr_dips(rows, "2026-11-02") == []


def test_trims_of_losers_and_held_names_are_blocked():
    rows = [_row(ticker="NNN", strategy="TRIM", status="pending"),
            _row(ticker="OOO", strategy="TRIM", account="caspar", status="pending"),
            _row(ticker="VVV", strategy="TRIM")]
    upl = {("sarah", "NNN"): -200.0, ("sarah", "VVV"): 500.0, ("caspar", "OOO"): 10.0}
    holds = {("caspar", "OOO")}
    assert di.blocked_sells(rows, "2026-11-02", upl, holds) == [("caspar", "OOO"), ("sarah", "NNN")]


# ── take-profit exits ───────────────────────────────────────────────────────

def test_trim_fills_when_the_high_reaches_the_level_and_is_graded_from_the_sellers_side():
    days = _days(40)
    spy = _bars(days, [100.0] * 40)
    # Trim at 105 written day 0; day 2's high reaches 106 → fill at max(105, open 104)=105.
    # The stock then slides to 95 while SPY is flat: selling was right.
    closes = [100, 102, 104] + [95.0] * 37
    b = di.Bars(days, [100, 102, 104] + [95.0] * 37, [100, 102, 106] + [95.0] * 37,
                [100, 102, 104] + [95.0] * 37, closes)
    idea = di.PastIdea("wsr_trim", "X", days[0], 105.0, side="sell")
    rec = di.grade("wsr_trim", [idea], {"SPY": spy, "X": b}, "2026-12-31")
    assert rec.n == 1 and rec.beat == 1
    assert rec.mean_alpha == pytest.approx(-(95 / 105 - 1) - di.COST_PER_SIDE)
    assert "1/1 lagged SPY after the trim and costs · trimming +" in di.record_line(di.assign_tier(rec))


def _pos(date, ticker, upl, qty=10, cost=100):
    return {"date": f"{date}T071300", "ticker": ticker, "qty": qty, "avg_cost": cost, "upl": upl}


def test_trim_history_grades_only_winners_and_one_idea_per_restated_stream():
    rows = [_row(ticker="DDD", strategy="TRIM", status="pending", entry=str(e), date=f"{d}T013300")
            for d, e in (("2026-10-20", 600), ("2026-10-21", 590), ("2026-10-22", 610))]
    rows += [_row(ticker="NNN", strategy="TRIM", status="pending", entry="65", date="2026-10-21T013300"),
             _row(ticker="ZZZ", strategy="TRIM", status="pending", entry="9", date="2026-10-21T013300")]
    positions = {"sarah": [_pos("2026-10-19", "DDD", 2400), _pos("2026-10-19", "NNN", -475)]}
    hist = di.wsr_trim_history(rows, positions)
    # DDD's daily "sell at market" re-statements are one idea; the NNN loser
    # and the never-held ZZZ are not graded.
    assert [(i.ticker, i.date, i.trigger, i.side) for i in hist] == [("DDD", "2026-10-20", 600.0, "sell")]


def test_live_trims_partition_with_blocked_sells():
    rows = [_row(ticker="VVV", strategy="TRIM", entry="420", qty="2", date="2026-10-26T232050",
                 source="wsr_full", thesis_1liner="VVV TRIM 2sh @ $420 — RSI overbought; realize the gain."),
            _row(ticker="VVV", strategy="TRIM", entry="420", qty="2",
                 thesis_1liner="VVV $401 — trigger fading 4.5% away."),
            _row(ticker="NNN", strategy="TRIM", status="pending", entry="62"),
            _row(ticker="OOO", strategy="TRIM", account="caspar", status="pending", entry="5"),
            _row(ticker="DDD", strategy="TRIM", status="pending", entry="560", qty="2",
                 thesis_1liner="DDD $560 — promoted: sell 2sh at market pre-ER.")]
    upl = {("sarah", "VVV"): 500.0, ("sarah", "NNN"): -400.0, ("caspar", "OOO"): 10.0,
           ("sarah", "DDD"): 2400.0}
    holds = {("caspar", "OOO")}
    exits = {e.ticker: e for e in di.live_wsr_trims(rows, "2026-11-02", upl, holds)}
    assert set(exits) == {"VVV", "DDD"}
    assert exits["VVV"].why == "RSI overbought; realize the gain." and not exits["VVV"].market
    assert exits["DDD"].market and exits["DDD"].qty == 2
    blocked = di.blocked_sells(rows, "2026-11-02", upl, holds)
    assert not {tk for _, tk in blocked} & set(exits)


def test_check_exit_caps_at_shares_held_and_never_sells_below_cost():
    days = _days(25)
    ex = di.Exit("sarah", "VVV", trigger=420.0, market=False, qty=5)
    assert di.check_exit(ex, _bars(days, [416.0] * 25), days[-1], held=3, avg_cost=350) is None
    assert ex.units == 3 and ex.status == "1.0% below the trim level"
    assert ex.proceeds == pytest.approx(3 * 420)          # priced at the limit
    under = di.Exit("sarah", "VVV", trigger=420.0, market=True, qty=2)
    assert di.check_exit(under, _bars(days, [340.0] * 25), days[-1], held=3, avg_cost=350) \
        == "now below cost (rule)"
    gone = di.Exit("sarah", "VVV", trigger=420.0, market=True, qty=2)
    assert di.check_exit(gone, _bars(days, [416.0] * 25), days[-1], held=0, avg_cost=350) == "no longer held"


def test_red_trim_record_shows_levels_only():
    from datetime import datetime
    days = _days(25)
    bars = {"SPY": _bars(days, [100.0] * 25), "VVV": _bars(days, [421.0] * 25)}
    rec = di.Record("wsr_trim", n=40, beat=12, mean_alpha=-0.02, t=-2.4, clusters=15, tier="red")
    ex = di.Exit("sarah", "VVV", trigger=420.0, market=False, qty=2)
    dm = di.build_dm(now_et=datetime(2026, 4, 3, 9, 47), today=days[-1], records={"wsr_trim": rec},
                     wsr=[], uoa=[], gov=None, momentum=[], bars=bars,
                     accounts=[di.Account("sarah", "SGD", nlv=50_000, cash=1_500)], sgd_per_usd=1.28,
                     kinds={}, earnings={}, blocked=[], exits=[ex], holdings={("sarah", "VVV"): (10, 350)})
    assert dm.exits == []
    assert "🔴 WSR profit-takes: 12/40 lagged SPY" in dm.text
    assert "levels only: VVV $420" in dm.text
    assert "<b>👤 Sarah</b> — No action" in dm.text
    assert "S1" not in dm.text


def test_uoa_skips_index_etfs_and_picks_the_heaviest_contract():
    rows = [
        {"date": "2026-10-29", "ticker": "SPY", "side": "CALL", "strike": "770", "expiry": "2026-11-20",
         "dte": "22", "notional": "9e6", "aggressor": "BUY_INITIATED", "bias": "BULLISH", "quality": "90"},
        {"date": "2026-10-29", "ticker": "GGL", "side": "CALL", "strike": "285", "expiry": "2026-11-20",
         "dte": "22", "notional": "4.5e6", "aggressor": "BUY_INITIATED", "bias": "BULLISH", "quality": "89",
         "bid": "8.05", "ask": "8.15"},
        {"date": "2026-10-29", "ticker": "GGL", "side": "CALL", "strike": "300", "expiry": "2026-11-20",
         "dte": "22", "notional": "3.6e6", "aggressor": "BUY_INITIATED", "bias": "BULLISH", "quality": "87"},
    ]
    [idea] = di.uoa_candidates(rows, "2026-10-30")
    assert idea.ticker == "GGL" and idea.strike == 285 and idea.limit == 8.15
    assert "yesterday" in idea.why and "$285–300" in idea.why


# ── live re-check ───────────────────────────────────────────────────────────

def test_a_source_stop_broken_today_drops_the_idea():
    days = _days(25)
    closes = [100.0] * 24 + [90.0]
    idea = di.Idea("momentum", "QQC", "BUY", trigger=95, stop=95.0)
    reason = di.check_live(idea, _bars(days, closes), days[-1])
    assert reason and reason.startswith("stop hit today")


def test_trigger_hit_today_status_and_stop_from_20_day_low():
    days = _days(25)
    closes = [104.0] * 24 + [100.4]
    lows = [103.0] * 10 + [96.0] + [103.0] * 13 + [99.5]
    idea = di.Idea("wsr", "A", "BUY", trigger=100)
    assert di.check_live(idea, _bars(days, closes, lows=lows), days[-1]) is None
    assert idea.status == "trigger hit today"
    assert idea.stop == 96.0
    assert idea.unit_cost == 100


def test_dip_on_a_fresh_20_day_low_keeps_a_stop_below_entry():
    days = _days(25)
    closes = [104.0] * 24 + [99.8]
    lows = [103.0] * 24 + [99.5]          # today IS the 20-day low
    idea = di.Idea("wsr", "A", "BUY", trigger=100)
    assert di.check_live(idea, _bars(days, closes, lows=lows), days[-1]) is None
    # Today's low is the 20-day low; the range leg gives the stop real room.
    assert idea.stop < 99.5 < idea.unit_cost
    assert idea.stop_basis.startswith("1.5 days")


def test_broken_trigger_anchor_is_dropped():
    days = _days(25)
    idea = di.Idea("wsr", "PPN", "BUY", trigger=93)
    reason = di.check_live(idea, _bars(days, [50.7] * 25), days[-1])
    assert reason and "nowhere near" in reason


def test_limit_below_the_20_day_low_gets_a_stop_under_its_entry():
    # SPY on 30 Oct: buy level $740, 20-day low $750 — the stop must not sit
    # above the entry, or the fill itself would break it.
    days = _days(25)
    closes = [760.0] * 24 + [755.7]
    lows = [752.0] * 24 + [750.4]
    idea = di.Idea("wsr", "SPY", "BUY", trigger=740)
    assert di.check_live(idea, _bars(days, closes, lows=lows), days[-1]) is None
    assert idea.stop < 740
    assert idea.stop_basis.startswith("1.5 days")


def test_red_source_ideas_show_levels_on_one_line_and_get_no_size():
    days = _days(25)
    bars = {"SPY": _bars(days, [100.0] * 25), "QQQ": _bars(days, [100.0] * 25),
            "EEE": _bars(days, [70.0] * 24 + [69.4], lows=[68.6] * 25)}
    idea = di.Idea("wsr", "EEE", "BUY", trigger=70.0, target=76.0)
    rec = di.Record("wsr", n=183, beat=74, mean_alpha=-0.011, t=-2.1, clusters=23, tier="red")
    a = di.Account("sarah", "SGD", nlv=50_000, cash=1_500)
    from datetime import datetime
    dm = di.build_dm(now_et=datetime(2026, 4, 3, 9, 47), today=days[-1], records={"wsr": rec},
                     wsr=[idea], uoa=[], gov=None, momentum=[], bars=bars, accounts=[a],
                     sgd_per_usd=1.28, kinds={"EEE": "ETF"}, earnings={}, blocked=[])
    assert dm.sized == []
    assert "🔴 WSR dip-buys: 74/183 beat SPY" in dm.text
    assert "WSR dip-buys levels, no size: EEE $70 (below)" in dm.text


# ── budget ──────────────────────────────────────────────────────────────────

def test_budget_splits_now_vs_after_deposit_vs_over():
    a = di.Account("sarah", "SGD", nlv=50_000, cash=1_500, deposit=3_000, deposit_ccy="SGD")
    ideas = []
    for cost in (957.0, 765.0, 1041.0, 900.0):
        i = di.Idea("wsr", "X", "BUY", unit_cost=cost)
        i.sizes["sarah"] = (1, False, "")
        ideas.append(i)
    bud = di.allocate(list(enumerate(ideas, 1)), a, 1.28)
    assert bud.now == [1] and bud.later == [2, 3] and bud.over == [4]


def test_landed_deposit_is_not_counted_twice():
    assert di.deposit_landed([80.0, 85.0, 470.0], 390.0)
    assert not di.deposit_landed([80.0, 85.0, 90.0], 390.0)


def test_earnings_note():
    soon = di.Earnings(upcoming=["2026-11-06"], checked=True)
    assert "inside the 20-day hold" in di.earnings_note("A", {"A": soon}, "2026-11-02")
    done = di.Earnings(reported="2026-10-29", checked=True)
    assert "reported 29 Oct — earnings are behind it" == di.earnings_note("A", {"A": done}, "2026-10-30")
    assert di.earnings_note("A", {}, "2026-10-30") == ""


def _notes(sheet, yahoo, today):
    e = {"A": di.reconcile_earnings(sheet, yahoo, today)}
    return di.earnings_note("A", e, today), di.exit_earnings_note("A", e, today)


def test_sheet_date_soon_after_a_confirmed_report_is_stale():
    yahoo = [("2027-01-26", False), ("2026-10-27", True), ("2026-07-28", True)]
    e = di.reconcile_earnings(["2026-11-03"], yahoo, "2026-11-01")
    assert e.upcoming == ["2027-01-26"] and e.reported == "2026-10-27" and e.checked
    assert _notes(["2026-11-03"], yahoo, "2026-11-01") == ("", "")
    assert _notes(["2026-11-03"], yahoo, "2026-10-29")[0] == "reported 27 Oct — earnings are behind it"


def test_when_the_sources_disagree_the_earlier_date_shows():
    yahoo = [("2026-11-04", False), ("2026-08-05", True)]
    assert _notes(["2026-11-09"], yahoo, "2026-11-01") == (
        "⚠ earnings Wed 4 Nov, inside the 20-day hold", "⚠ earnings Wed 4 Nov")
    assert _notes(["2026-11-02"], yahoo, "2026-11-01")[1] == "⚠ earnings Mon 2 Nov"    # Sheet earlier


def test_sources_agreeing_give_one_date():
    yahoo = [("2026-11-03", False), ("2026-08-04", True)]
    assert di.reconcile_earnings(["2026-11-03"], yahoo, "2026-11-01").upcoming == ["2026-11-03"]


def test_a_passed_sheet_date_is_not_a_report_without_yahoo_results():
    yahoo = [("2026-11-04", False), ("2026-08-04", True)]
    note, _ = _notes(["2026-10-30"], yahoo, "2026-11-01")
    assert note == "⚠ earnings Wed 4 Nov, inside the 20-day hold"
    # Yahoo lists the date but no results yet: no claim either way.
    assert _notes(["2026-10-30"], [("2026-10-30", False), ("2026-08-04", True)], "2026-11-01") == ("", "")


def test_today_depends_on_whether_results_are_out():
    assert _notes(["2026-11-02"], [("2026-11-02", True)], "2026-11-02") == (
        "reported today — earnings are behind it", "")
    assert _notes(["2026-11-02"], [("2026-11-02", False)], "2026-11-02")[1] == "⚠ earnings Mon 2 Nov"


def test_late_filers_keep_a_close_next_date():
    yahoo = [("2026-05-06", False), ("2026-03-31", True)]    # 36 days apart really happens
    assert di.reconcile_earnings([], yahoo, "2026-04-01").upcoming == ["2026-05-06"]
    assert di.reconcile_earnings(["2026-05-06"], [("2026-03-31", True)], "2026-04-01").upcoming == ["2026-05-06"]


def test_no_yahoo_rows_keeps_the_sheet_and_says_so():
    assert _notes(["2026-11-03"], None, "2026-11-01") == (
        "⚠ earnings Tue 3 Nov, inside the 20-day hold (date not cross-checked)",
        "⚠ earnings Tue 3 Nov (date not cross-checked)")
    assert _notes(["2026-10-30"], [], "2026-11-01")[0] == (
        "reported 30 Oct — earnings are behind it (date not cross-checked)")
    assert _notes([], None, "2026-11-01") == ("", "")


# ── end-to-end dryrun against the synthetic fixture ─────────────────────────

@pytest.fixture
def fixture_dm(capsys, monkeypatch):
    monkeypatch.delenv("GROWTH_LEG_ENABLED", raising=False)
    assert dm_script.main(["--fixture", str(FIXTURE)]) == 0
    return capsys.readouterr().out


def test_fixture_dryrun_shapes_the_dm(fixture_dm):
    out = fixture_dm
    assert out.startswith("📈 <b>Ideas · Mon 2 Nov · 09:47 ET · 22:47 SGT</b>")
    assert "<b>1 · AAA · stock · BUY</b> — trigger hit today" in out
    assert "EEE · ETF · BUY" in out
    assert "GGG · option · BUY CALL" in out
    assert "GGG: buy call, no size (one contract is" in out  # too dear for the small book
    assert "⚠ earnings Fri 6 Nov" in out
    assert "MMM 12.5% above $80" in out                     # waiting, not sized
    assert "QQC (stop hit today" in out                     # live re-check dropped it
    assert "of underwater holdings skipped (rule)" in out   # never-sell-a-loser
    assert "paper leg off" in out                           # momentum watch-only
    for gone in ("KIL", "OLD", "UUU", "TTT", "SPY · option"):
        assert gone not in out
    assert "Nov budget:" in out


def test_ci_dry_run_never_prints_the_dm(capsys, monkeypatch):
    dm = di.DM("SECRET CASH", [], [], [], [])
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    dm_script.print_dry(dm, is_fixture=False)
    assert "SECRET CASH" not in capsys.readouterr().out
    dm_script.print_dry(dm, is_fixture=True)      # synthetic data only
    assert "SECRET CASH" in capsys.readouterr().out
    monkeypatch.delenv("GITHUB_ACTIONS")
    dm_script.print_dry(dm, is_fixture=False)     # on the Mac
    assert "SECRET CASH" in capsys.readouterr().out


def test_fixture_dryrun_cross_checks_earnings_dates(fixture_dm):
    out = fixture_dm
    assert "⚠ earnings Fri 6 Nov, inside the 20-day hold\n" in out    # both sources agree
    assert "⚠ earnings Thu 5 Nov\n" in out                            # WWW: Yahoo earlier than the Sheet
    assert "Wed 4 Nov" not in out                                      # VVV: stale Sheet date
    assert "Thu 12 Nov" not in out
    assert "⚠ earnings Tue 10 Nov, inside the 20-day hold (date not cross-checked)" in out    # GGG


def test_fixture_dryrun_take_profits(fixture_dm):
    out = fixture_dm
    assert "<b>Take profits</b>" in out
    assert "WSR profit-takes:" in out and "lagged SPY after the trim" in out
    assert "<b>S1 · WWW · SELL</b> — WSR says sell now" in out
    assert "Sell 5 of his 20 sh at market" in out
    assert "<b>S2 · VVV · SELL</b> — 1.0% below the trim level" in out
    assert "Sell 3 of her 10 sh with a limit at $420" in out
    assert "Waiting to trim: PPP 16.7% below $120" in out
    assert "S1 frees ≈" in out and "S2 frees ≈" in out


def test_fixture_dm_is_valid_telegram_html(fixture_dm):
    out = fixture_dm.strip()
    assert len(out) <= di.TELEGRAM_LIMIT
    assert out.count("<b>") == out.count("</b>")
    assert out.count("<i>") == out.count("</i>")
    assert "<" not in out.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")


# ── the PWA's copy of the DM (cards → the daily_ideas tab) ──────────────────

@pytest.fixture
def fixture_built(monkeypatch):
    """The DM object (not just its text) from an offline run of the fixture."""
    monkeypatch.delenv("GROWTH_LEG_ENABLED", raising=False)
    got = {}
    real = di.build_dm

    def spy(**kw):
        got["dm"] = real(**kw)
        return got["dm"]

    monkeypatch.setattr(di, "build_dm", spy)
    assert dm_script.main(["--fixture", str(FIXTURE)]) == 0
    return got["dm"]


def _plain_lines(dm):
    return di._plain(dm.text).splitlines()


def test_plain_drops_tags_before_unescaping():
    assert di._plain("<b>Stop: close &lt; $95.90</b> &amp; <i>x</i>") == "Stop: close < $95.90 & x"
    assert di._plain("a &lt;b&gt; c") == "a <b> c"       # a '<' that was text is not a tag


def test_cards_have_one_meta_row_and_match_the_dm_counts(fixture_built):
    dm = fixture_built
    cards = dm.cards
    assert all(list(c) == list(di.CARD_COLUMNS) for c in cards)
    assert all(isinstance(v, str) for c in cards for v in c.values())
    by = lambda s: [c for c in cards if c["section"] == s]
    assert len(by("meta")) == 1 and cards[0]["section"] == "meta"
    assert [c["account"] for c in by("book")] == ["Caspar", "Sarah"]
    assert len({c["ticker"] for c in by("idea")}) == len(dm.sized) == 4
    assert {c["account"] for c in by("idea")} == {"Caspar", "Sarah"}
    assert len(by("exit")) == len(dm.exits) == 2
    assert len([c for c in by("watch") if not c["account"]]) == len(dm.watch)
    assert {c["date"] for c in cards} == {"2026-11-02"}
    assert {c["sent_at"] for c in cards} == {"2026-11-02T09:47"}
    assert {c["num"] for c in by("idea")} == {"1", "2", "3", "4"}
    assert [c["num"] for c in by("exit")] == ["S1", "S2"]
    assert {c["ticker"] for c in by("idea")} == {i.ticker for i in dm.sized}


def test_card_strings_carry_no_telegram_markup(fixture_built):
    for c in fixture_built.cards:
        for k, v in c.items():
            for bad in ("<b>", "</b>", "<i>", "</i>", "&lt;", "&gt;", "&amp;"):
                assert bad not in v, (c["section"], c["num"], k, v)


def test_underwater_and_hold_list_names_never_become_cards(fixture_built):
    # UUU is underwater and TTT is on the hold list: their WSR trims are blocked.
    exits = [c for c in fixture_built.cards if c["section"] == "exit"]
    assert {c["ticker"] for c in exits} == {"WWW", "VVV"}
    for c in fixture_built.cards:
        assert "UUU" not in "|".join(c.values()) and "TTT" not in "|".join(c.values())


def test_idea_cards_repeat_the_dm_lines_exactly(fixture_built):
    dm = fixture_built
    lines = _plain_lines(dm)
    ideas = {(c["ticker"], c["account"]): c for c in dm.cards if c["section"] == "idea"}

    aaa = ideas[("AAA", "Caspar")]                        # a stock, first under Caspar
    assert f"{aaa['num']} · AAA · {aaa['kind']} · {aaa['action']} — {aaa['status']}" in lines
    entry, sep, target = aaa["plan"].partition(" · Target")
    assert sep and entry == "Entry ≤ $100 (now $100.40)" and entry in lines
    assert f"{aaa['stop']} · Target{target}" in lines
    assert aaa["stop"] == "Stop: close < $95.90 (20-day low, −4.1%)"
    assert aaa["size"].startswith("Size: 2 sh ≈ $200 · ") and aaa["size"] in lines
    hers = ideas[("AAA", "Sarah")]
    assert hers["size"].startswith("Size: 7 sh ≈ $700 · ") and hers["size"] in lines
    assert hers["why"] == aaa["why"] and hers["record"] == aaa["record"]   # the app's copy stays full
    assert f"Why and record: as #{aaa['num']} under Caspar." in lines      # the DM's points back
    assert aaa["why"] == "Why (WSR): post-earnings add on a pullback to support." and aaa["why"] in lines
    assert aaa["notes"] == "⚠ earnings Fri 6 Nov, inside the 20-day hold" and aaa["notes"] in lines
    assert aaa["record"].startswith("🟡 WSR dip-buys: 9/14 beat SPY after costs") and aaa["record"] in lines
    assert (aaa["source"], aaa["tier"], aaa["kind"], aaa["action"]) == ("wsr", "yellow", "stock", "BUY")

    ggg = ideas[("GGG", "Sarah")]                         # an option, too dear for Caspar's book
    assert ("GGG", "Caspar") not in ideas
    assert (ggg["kind"], ggg["action"], ggg["source"]) == ("option", "BUY CALL", "uoa")
    assert ggg["plan"] == "Buy 1× 20 Nov $150C ≤ $3.10 (mid $3.00)" and ggg["plan"] in lines
    assert "max loss $310 per contract" in ggg["stop"] and "breakeven $153.10" in ggg["stop"]
    assert ggg["stop"] in lines
    assert ggg["why"].startswith("Why: ") and ggg["why"] in lines      # not "Why (WSR)"
    assert ggg["size"] in lines


def test_exit_cards_name_the_book_and_repeat_the_dm_lines(fixture_built):
    dm = fixture_built
    lines = _plain_lines(dm)
    s1, s2 = [c for c in dm.cards if c["section"] == "exit"]
    assert f"{s1['num']} · {s1['ticker']} · {s1['action']} — {s1['status']}" in lines
    assert (s1["account"], s1["status"]) == ("Caspar", "WSR says sell now")
    assert s1["plan"].startswith("Sell 5 of his 20 sh at market") and s1["plan"] in lines
    assert s1["size"].startswith("Locks ≈ +$60") and s1["size"] in lines
    assert s1["why"] in lines and s1["notes"] == "⚠ earnings Thu 5 Nov"
    assert s1["record"] in lines and s1["record"].startswith("🟡 WSR profit-takes:")
    assert (s2["account"], s2["plan"].startswith("Sell 3 of her 10 sh with a limit at $420")) == ("Sarah", True)


def test_meta_and_watch_cards_repeat_the_dm(fixture_built):
    dm = fixture_built
    lines = _plain_lines(dm)
    meta = dm.cards[0]
    assert meta["tape"] == lines[1] == "SPY 638.39 −1.2% · QQQ 670.49 −0.6% · broad sell-off"
    assert meta["lead"] in lines and meta["lead"].startswith("All at probation size")
    assert meta["phase"] == "open" and meta["recheck"] == ""
    assert all(x in lines for x in meta["levels"].split(" | "))
    assert meta["dropped"] == "QQC (stop hit today, −8%)" and f"Dropped: {meta['dropped']}" in lines
    books = {c["account"]: c for c in dm.cards if c["section"] == "book"}
    assert all(b["budget"] in lines for b in books.values() if b["budget"])
    assert sum("underwater" in b["dropped"] for b in books.values()) >= 1   # blocked trims name their book
    assert any("PPP 16.7% below $120" in b["waiting"] for b in books.values())
    assert "• Waiting to trim: PPP 16.7% below $120" in lines
    watch = [c["plan"] for c in dm.cards if c["section"] == "watch" and not c["account"]]
    assert all(f"• {w}" in lines for w in watch)
    assert watch[0].startswith("ZZZ: momentum leader")
    mine = [c["plan"] for c in dm.cards if c["section"] == "watch" and c["account"]]
    assert all(f"• {w}" in lines for w in mine)


def test_meta_row_is_written_even_when_nothing_is_sized():
    from datetime import datetime
    dm = di.build_dm(now_et=datetime(2026, 11, 2, 9, 47), today="2026-11-02", records={}, wsr=[],
                     uoa=[], gov=None, momentum=[], bars={}, accounts=[], sgd_per_usd=1.28,
                     kinds={}, earnings={}, blocked=[])
    assert [c["section"] for c in dm.cards] == ["meta"]
    meta = dm.cards[0]
    assert (meta["date"], meta["sent_at"], meta["lead"], meta["budget"]) == ("2026-11-02", "2026-11-02T09:47", "", "")


def test_dry_run_stdout_is_the_dm_and_nothing_else(capsys, monkeypatch):
    monkeypatch.delenv("GROWTH_LEG_ENABLED", raising=False)
    assert dm_script.main(["--fixture", str(FIXTURE)]) == 0
    out = capsys.readouterr().out
    assert out.strip().startswith("📈 <b>Ideas") and "cards" not in out
    assert out.strip().endswith("QQC (stop hit today, −8%)")


class _FakeSheets:
    """Stands in for src.sheets: records what the card write does."""
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def _hit(self, name, *a, **kw):
        self.calls.append((name, a, kw))
        if self.fail_on == name:
            raise RuntimeError("sheet boom")

    def authenticate(self): self._hit("authenticate"); return "client"
    def ensure_headers(self, *a, **kw): self._hit("ensure_headers", *a, **kw)
    def append_rows(self, *a, **kw): self._hit("append_rows", *a, **kw); return 1
    def replace_today_rows(self, *a, **kw): self._hit("replace_today_rows", *a, **kw); return len(a[2])


def test_write_cards_replaces_todays_rows_with_the_header_width(monkeypatch):
    from src import sheets
    fake = _FakeSheets()
    for n in ("ensure_headers", "replace_today_rows"):
        monkeypatch.setattr(sheets, n, getattr(fake, n))
    cards = [di._card(date="2026-11-02", section="meta", tape="t"),
             di._card(date="2026-11-02", section="idea", num=1, ticker="AAA")]
    assert dm_script.write_cards("client", cards, "2026-11-02") == 0
    assert [c[0] for c in fake.calls] == ["ensure_headers", "replace_today_rows"]
    _, (client, tab, headers), _ = fake.calls[0]
    assert (tab, headers) == (dm_script.CARD_TAB, dm_script.CARD_HEADERS) == ("daily_ideas", list(di.CARD_COLUMNS))
    _, (client, tab, rows), kw = fake.calls[1]
    assert tab == "daily_ideas" and kw == {"today_prefix": "2026-11-02"}
    assert all(len(r) == len(dm_script.CARD_HEADERS) for r in rows) and rows[1][3] == "1"


def test_a_failed_card_write_returns_1_and_never_raises(monkeypatch):
    from src import sheets
    fake = _FakeSheets(fail_on="replace_today_rows")
    for n in ("ensure_headers", "replace_today_rows"):
        monkeypatch.setattr(sheets, n, getattr(fake, n))
    assert dm_script.write_cards("client", [di._card(date="2026-11-02", section="meta")], "2026-11-02") == 1


def test_live_send_logs_the_ledger_before_the_cards_and_a_card_failure_costs_neither(monkeypatch):
    """The DM goes out once and the ideas_log ledger is written even if the cards fail."""
    from src import sheets, sync, telegram
    fake = _FakeSheets(fail_on="replace_today_rows")
    monkeypatch.delenv("GROWTH_LEG_ENABLED", raising=False)
    monkeypatch.setattr(sync, "load_env", lambda: None)       # never read a real .env in a test

    def no_network(*a, **kw):
        raise AssertionError("this test must never open a network connection")

    import socket
    monkeypatch.setattr(socket.socket, "connect", no_network)  # belt and braces: Telegram/Sheets are stubbed
    sent = []
    monkeypatch.setattr(telegram, "ping_daily_ideas", lambda text: sent.append(text))
    for n in ("authenticate", "ensure_headers", "append_rows", "replace_today_rows"):
        monkeypatch.setattr(sheets, n, getattr(fake, n))
    bars = dm_script.bars_from_csv(FIXTURE / "prices.csv")
    monkeypatch.setattr(dm_script, "load_tabs_sheet", lambda: dm_script.load_tabs_dir(FIXTURE))
    monkeypatch.setattr(dm_script, "fetch_bars", lambda tickers, start: bars)
    monkeypatch.setattr(dm_script, "fetch_fx", lambda: 1.28)
    monkeypatch.setattr(dm_script, "fetch_kinds", lambda tickers: {})
    monkeypatch.setattr(dm_script, "fetch_earnings", lambda tickers: {})
    monkeypatch.setattr(dm_script, "fetch_option", lambda *a: None)
    assert dm_script.main(["--force", "--phase", "open"]) == 1   # the card write failed
    names = [c[0] for c in fake.calls]
    assert len(sent) == 1                                  # sent once, never re-sent
    assert names.index("append_rows") < names.index("replace_today_rows")   # ledger first
    assert fake.calls[names.index("append_rows")][1][1] == dm_script.LOG_TAB


def test_red_trim_levels_reach_the_pwa_as_an_exit_note():
    """A losing trim record sends levels only. The app must show what the DM shows."""
    from datetime import datetime
    days = _days(25)
    bars = {"SPY": _bars(days, [100.0] * 25), "VVV": _bars(days, [421.0] * 25)}
    rec = di.Record("wsr_trim", n=40, beat=12, mean_alpha=-0.02, t=-2.4, clusters=15, tier="red")
    ex = di.Exit("sarah", "VVV", trigger=420.0, market=False, qty=2)
    dm = di.build_dm(now_et=datetime(2026, 4, 3, 9, 47), today=days[-1], records={"wsr_trim": rec},
                     wsr=[], uoa=[], gov=None, momentum=[], bars=bars,
                     accounts=[di.Account("sarah", "SGD", nlv=50_000, cash=1_500)], sgd_per_usd=1.28,
                     kinds={}, earnings={}, blocked=[], exits=[ex], holdings={("sarah", "VVV"): (10, 350)})
    assert not [c for c in dm.cards if c["section"] == "exit"]
    notes = [c for c in dm.cards if c["section"] == "exit_note"]
    assert [(n["plan"], n["account"]) for n in notes] == [("levels only: VVV $420", "Sarah")]
    assert notes[0]["record"] in dm.text and notes[0]["record"].startswith("🔴 WSR profit-takes")


# ── the pre-open plan, the direction block, and the books ───────────────────

def test_premarket_bar_moves_the_price_but_never_the_record():
    days = _days(30)
    spy = _bars(days, [100.0] * 30)
    tk = _bars(days, [50.0] * 30)
    today = (date.fromisoformat(days[-1]) + timedelta(days=1)).isoformat()
    bars = di.with_premarket({"SPY": spy, "TTT": tk}, {"SPY": (101, 102, 100.5, 101.5)}, today)
    assert bars["SPY"].dates[-1] == today and bars["SPY"].c[-1] == 101.5
    assert bars["TTT"].dates[-1] == days[-1]               # no quote: keeps its last close
    last, chg, _ = di.move_stats(bars["SPY"], today)
    assert (last, round(chg, 3)) == (101.5, 0.015)
    ideas = [di.PastIdea("uoa", "SPY", days[2], None)]
    before = di.grade("uoa", ideas, {"SPY": spy}, today)
    after = di.grade("uoa", ideas, bars, today)
    assert (before.n, before.mean_alpha) == (after.n, after.mean_alpha)


def test_premarket_does_not_add_a_second_bar_once_today_exists():
    days = _days(5)
    b = _bars(days, [10.0] * 5)
    assert di.with_premarket({"X": b}, {"X": (1, 1, 1, 1)}, days[-1])["X"] is b


def test_session_labels_say_which_day_the_number_is_from():
    days = _days(5, start=date(2026, 10, 26))              # Mon 26 to Fri 30 Oct
    b = _bars(days, [100, 100, 100, 100, 98.0])
    assert di.session_word(b, "2026-11-02") == "Fri"       # before any trade on Monday
    assert di.session_change(b, "2026-11-02") == ("Fri", pytest.approx(-0.02))
    assert di.session_word(b, days[-1]) == "today"


def test_a_bounce_under_a_broken_stop_does_not_read_as_a_fresh_hit():
    days = _days(5, start=date(2026, 10, 26))
    b = _bars(days, [100.0] * 5)
    assert di.stop_note(b, "2026-11-02", -0.11) == "stop hit Fri, −11%"
    assert di.stop_note(b, days[-1], 0.01) == "still below its stop, +1% today"


def test_stale_book_needs_cash_and_share_counts_both_frozen():
    frozen = frozenset({("AAA", 10.0)})
    same = [(f"2026-0{m}-01", frozen) for m in (6, 7, 8)]
    cash = [("2026-06-01", 500.0), ("2026-07-01", 500.0), ("2026-08-01", 500.0)]
    assert di.stale_since(cash, same, "2026-08-20") == "2026-06-01"
    moving = cash[:-1] + [("2026-08-01", 500.2)]
    assert di.stale_since(moving, same, "2026-08-05") == ""   # cash moved days ago
    assert di.stale_since(moving, same, "2026-08-20") == "2026-08-01"
    assert di.stale_since(cash, same, "2026-06-05") == ""     # not long enough yet
    assert di.stale_since([], [], "2026-08-20") == ""


def test_brief_record_scores_only_real_calls_on_trading_days():
    days = _days(4, start=date(2026, 10, 26))              # Mon..Thu
    spy = _bars(days, [100, 101, 100, 102])                # up, down, up
    rows = [{"date": f"{days[1]}T100000", "sentiment": "bullish"},  # right
            {"date": f"{days[2]}T100000", "sentiment": "bullish"},  # wrong
            {"date": f"{days[3]}T100000", "sentiment": "neutral"},  # not a call
            {"date": "2026-10-25T100000", "sentiment": "bearish"},  # a Sunday
            {"date": "2026-10-31T100000", "sentiment": "bearish"}]  # today's: not scored yet
    assert di.direction_record(rows, spy, "2026-10-31") == (1, 2)


def test_direction_lines_show_the_read_and_say_when_it_is_old():
    rows = [{"date": "2026-11-02T100410", "sentiment": "Bearish", "verdict": "Defensive   stance."}]
    assert di.direction_lines(rows, None, "2026-11-02") == ["Morning brief: bearish. Defensive stance."]
    assert di.direction_lines(rows, None, "2026-11-06") == ["No fresh brief: the last is from 2 Nov."]
    assert di.direction_lines([], None, "2026-11-02") == []


def test_level_lines_use_completed_closes_and_drop_old_dealer_levels():
    days = _days(210)
    today = (date.fromisoformat(days[-1]) + timedelta(days=1)).isoformat()
    bars = {"SPY": _bars(days + [today], [100.0] * 210 + [999.0])}
    gex = [{"symbol": "SPY", "date": days[-1], "put_wall": "95", "call_wall": "105", "regime": "NEGATIVE_TREND"}]
    macro = [{"date": f"{days[-1]}T090000", "vix": "19.44", "us_10y": "4.929"}]
    lines = di.level_lines(bars, gex, macro, today)
    assert lines[0].startswith("SPY: 50d $100 · 200d $100 · dealer walls $95 / $105")
    assert lines[1] == "VIX 19.4 · 10Y 4.93% · dealers short gamma, so moves can run further"
    far = (date.fromisoformat(today) + timedelta(days=9)).isoformat()
    assert "dealer walls" not in di.level_lines(bars, gex, [], far)[0]


def test_book_earnings_lists_only_this_books_near_reports():
    e = {"AAA": di.Earnings(upcoming=["2026-11-02"], checked=True),
         "BBB": di.Earnings(upcoming=["2026-11-05"], checked=True),
         "CCC": di.Earnings(upcoming=["2026-12-20"], checked=True),
         "DDD": di.Earnings(upcoming=["2026-11-03"], checked=False)}
    h = {("sarah", "BBB"): (5, 1), ("sarah", "AAA"): (5, 1), ("sarah", "CCC"): (5, 1),
         ("caspar", "DDD"): (5, 1), ("sarah", "DDD"): (0, 0)}
    assert di.book_earnings("sarah", h, e, "2026-11-02") == ["AAA today", "BBB Thu 5 Nov"]
    assert di.book_earnings("caspar", h, e, "2026-11-02") == ["DDD Tue 3 Nov (date not cross-checked)"]


def test_plan_changes_names_new_gone_and_crossed_levels():
    prior = [{"section": "exit", "account": "Sarah", "ticker": "AAA", "action": "SELL", "status": "1.0% below the trim level"},
             {"section": "exit", "account": "Sarah", "ticker": "BBB", "action": "SELL", "status": "WSR says sell now"},
             {"section": "idea", "account": "Caspar", "ticker": "SAME", "action": "BUY", "status": "below trigger"},
             {"section": "watch", "account": "", "ticker": "", "action": "", "status": ""}]
    now = [{"section": "exit", "account": "Sarah", "ticker": "AAA", "action": "SELL", "status": "at the trim level"},
           {"section": "idea", "account": "Caspar", "ticker": "SAME", "action": "BUY", "status": "trigger hit today"},
           {"section": "idea", "account": "Sarah", "ticker": "NEW", "action": "BUY", "status": "below trigger"}]
    assert di.plan_changes(prior, now) == ["Sarah AAA SELL reached its level", "new: Sarah NEW BUY", "gone: Sarah BBB SELL"]
    assert di.plan_changes(now, now) == []


def _preopen_run(monkeypatch, tabs_extra=None, now="2026-11-02T08:45:00", argv=(), traded_today=False):
    """A live send against the fixture with every outside call stubbed."""
    from src import sheets, sync, telegram
    from datetime import datetime as real_dt
    fake = _FakeSheets()
    monkeypatch.delenv("GROWTH_LEG_ENABLED", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr(sync, "load_env", lambda: None)
    sent = []
    monkeypatch.setattr(telegram, "ping_daily_ideas", lambda text: sent.append(text))
    for n in ("authenticate", "ensure_headers", "append_rows", "replace_today_rows"):
        monkeypatch.setattr(sheets, n, getattr(fake, n))
    bars = dm_script.bars_from_csv(FIXTURE / "prices.csv")
    tabs = dm_script.load_tabs_dir(FIXTURE)
    tabs.update(tabs_extra or {})
    monkeypatch.setattr(dm_script, "load_tabs_sheet", lambda: tabs)
    # The fixture's prices run through 2 Nov; a pre-open run hasn't seen that bar yet.
    cut = {t: di.Bars(b.dates[:-1], b.o[:-1], b.h[:-1], b.l[:-1], b.c[:-1], b.adj[:-1]) for t, b in bars.items()}
    monkeypatch.setattr(dm_script, "fetch_bars", lambda tickers, start: dict(bars if traded_today else cut))
    monkeypatch.setattr(dm_script, "fetch_fx", lambda: 1.28)
    monkeypatch.setattr(dm_script, "fetch_kinds", lambda tickers: {})
    monkeypatch.setattr(dm_script, "fetch_earnings", lambda tickers: {})
    monkeypatch.setattr(dm_script, "fetch_option", lambda *a: None)
    monkeypatch.setattr(dm_script, "fetch_premarket", lambda tickers, today: {"SPY": (640.0, 641.0, 639.0, 640.5)})

    class Clock(real_dt):
        @classmethod
        def now(cls, tz=None):
            return real_dt.fromisoformat(now).replace(tzinfo=tz)

    monkeypatch.setattr(dm_script, "datetime", Clock)
    return dm_script.main(list(argv)), sent, fake


def test_preopen_send_writes_the_app_but_not_the_graded_ledger(monkeypatch):
    rc, sent, fake = _preopen_run(monkeypatch)
    assert rc == 0 and len(sent) == 1
    assert sent[0].startswith("🌅 <b>Pre-open plan · Mon 2 Nov · 08:45 ET · 21:45 SGT</b>")
    assert "pre-market, vs" in sent[0] and "Re-check 09:47 ET · 22:47 SGT on live prices." in sent[0]
    names = [c[0] for c in fake.calls]
    assert "append_rows" not in names and "replace_today_rows" in names
    rows = fake.calls[names.index("replace_today_rows")][1][2]
    phase = dm_script.CARD_HEADERS.index("phase")
    assert {r[phase] for r in rows} == {"preopen"}


def test_preopen_goes_once_and_never_on_a_holiday(monkeypatch):
    already = [{"date": "2026-11-02", "section": "meta", "phase": "preopen", "sent_at": "2026-11-02T08:45"}]
    rc, sent, _ = _preopen_run(monkeypatch, {"daily_ideas": already})
    assert rc == 0 and sent == []
    rc, sent, _ = _preopen_run(monkeypatch)
    assert len(sent) == 1
    monkeypatch.setattr(dm_script, "fetch_premarket", lambda tickers, today: {})
    # (re-stub after _preopen_run so the holiday has no SPY quote)
    from src import telegram
    held = []
    monkeypatch.setattr(telegram, "ping_daily_ideas", lambda text: held.append(text))
    assert dm_script.main([]) == 0 and held == []


def test_recheck_with_nothing_changed_is_one_short_message(monkeypatch):
    rc, sent, fake = _preopen_run(monkeypatch)
    names = [c[0] for c in fake.calls]
    rows = fake.calls[names.index("replace_today_rows")][1][2]
    plan = [dict(zip(dm_script.CARD_HEADERS, r)) for r in rows]
    # The same inputs at 09:47: the fixture's own 2 Nov bars now apply, so compare via the pure function.
    assert di.plan_changes(plan, plan) == []
    dm = di.build_dm(now_et=_et("2026-11-02T09:47:00"), today="2026-11-02", records={}, wsr=[], uoa=[], gov=None,
                     momentum=[], bars={}, accounts=[], sgd_per_usd=1.28, kinds={}, earnings={}, blocked=[],
                     prior_cards=[{"section": "meta", "phase": "preopen", "sent_at": "2026-11-02T08:45"}])
    assert dm.text.startswith("✅ <b>Re-check · Mon 2 Nov · 09:47 ET · 22:47 SGT</b>")
    assert dm.text.endswith("Plan unchanged since the 08:45 ET plan.") and dm.changes == []
    assert dm.cards[0]["phase"] == "open"    # the app still gets the fresh rows


def test_recheck_says_what_changed_then_gives_the_whole_list():
    prior = [{"section": "meta", "phase": "preopen", "sent_at": "2026-11-02T08:45"},
             {"section": "exit", "account": "Sarah", "ticker": "OLD", "action": "SELL", "status": "WSR says sell now"}]
    dm = di.build_dm(now_et=_et("2026-11-02T09:47:00"), today="2026-11-02", records={}, wsr=[], uoa=[], gov=None,
                     momentum=[], bars={}, accounts=[], sgd_per_usd=1.28, kinds={}, earnings={}, blocked=[],
                     prior_cards=prior)
    assert dm.changes == ["gone: Sarah OLD SELL"]
    assert "<b>Changed since the 08:45 ET plan:</b> gone: Sarah OLD SELL" in dm.text.splitlines()[1]
    assert dm.text.startswith("📈 <b>Ideas")


def test_stale_book_warns_in_the_dm_and_on_the_book_card():
    from datetime import datetime
    a = di.Account("sarah", "SGD", nlv=50_000, cash=1_500, stale_since="2026-06-04")
    dm = di.build_dm(now_et=datetime(2026, 11, 2, 8, 45), today="2026-11-02", records={}, wsr=[], uoa=[], gov=None,
                     momentum=[], bars={}, accounts=[a], sgd_per_usd=1.28, kinds={}, earnings={}, blocked=[],
                     phase="preopen")
    want = "⚠ Cash and share counts unchanged since 4 Jun: check against IBKR before acting."
    assert want in dm.text
    assert [c["warning"] for c in dm.cards if c["section"] == "book"] == [want]


def test_a_run_after_the_window_warns_once_if_nothing_went_out(monkeypatch):
    rc, sent, fake = _preopen_run(monkeypatch, now="2026-11-02T15:00:00", traded_today=True)
    assert rc == 0 and len(sent) == 1 and sent[0].startswith("⚠️ <b>No ideas list today.</b>")
    assert "15:00 ET · 04:00 SGT" in sent[0]
    names = [c[0] for c in fake.calls]
    assert "append_rows" in names               # so the next late run stays quiet
    logged = [{"date": "2026-11-02", "source": "missed"}]
    rc, sent, _ = _preopen_run(monkeypatch, {"ideas_log": logged}, now="2026-11-02T15:30:00", traded_today=True)
    assert rc == 0 and sent == []


def test_a_run_outside_the_windows_stays_quiet(monkeypatch):
    for clock in ("2026-11-02T07:00:00", "2026-11-02T09:35:00", "2026-11-01T10:00:00"):
        rc, sent, _ = _preopen_run(monkeypatch, now=clock)
        assert rc == 0 and sent == []


def _et(stamp: str):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo("America/New_York"))
