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
                     accounts=[di.Account("sarah", "SGD", nlv=67_000, cash=1_400)], sgd_per_usd=1.28,
                     kinds={}, earnings={}, blocked=[], exits=[ex], holdings={("sarah", "VVV"): (10, 350)})
    assert dm.exits == []
    assert "🔴 WSR profit-takes: 12/40 lagged SPY" in dm.text
    assert "levels only: VVV $420 (Sarah)" in dm.text
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
    a = di.Account("sarah", "SGD", nlv=67_000, cash=1_400)
    from datetime import datetime
    dm = di.build_dm(now_et=datetime(2026, 4, 3, 9, 47), today=days[-1], records={"wsr": rec},
                     wsr=[idea], uoa=[], gov=None, momentum=[], bars=bars, accounts=[a],
                     sgd_per_usd=1.28, kinds={"EEE": "ETF"}, earnings={}, blocked=[])
    assert dm.sized == []
    assert "🔴 WSR dip-buys: 74/183 beat SPY" in dm.text
    assert "levels only: EEE $70 (below)" in dm.text


# ── budget ──────────────────────────────────────────────────────────────────

def test_budget_splits_now_vs_after_deposit_vs_over():
    a = di.Account("sarah", "SGD", nlv=67_000, cash=1_369, deposit=3_000, deposit_ccy="SGD")
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
    assert out.startswith("📈 <b>Ideas · Mon 2 Nov · 09:47 ET</b>")
    assert "<b>1 · AAA · stock · BUY</b> — trigger hit today" in out
    assert "EEE · ETF · BUY" in out
    assert "GGG · option · BUY CALL" in out
    assert "Caspar none (one contract is" in out           # too dear for the small book
    assert "⚠ earnings Fri 6 Nov" in out
    assert "MMM 12.5% above $80" in out                     # waiting, not sized
    assert "QQC (stop hit today" in out                     # live re-check dropped it
    assert "2 trims of underwater holdings (rule)" in out   # never-sell-a-loser
    assert "paper leg off" in out                           # momentum watch-only
    for gone in ("KIL", "OLD", "UUU", "TTT", "SPY · option"):
        assert gone not in out
    assert "Nov budget (cash + deposit):" in out


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
    assert "<b>S1 · WWW · Caspar · SELL</b> — WSR says sell now" in out
    assert "Sell 5 of his 20 sh at market" in out
    assert "<b>S2 · VVV · Sarah · SELL</b> — 1.0% below the trim level" in out
    assert "Sell 3 of her 10 sh with a limit at $420" in out
    assert "Waiting to trim: PPP 16.7% below $120" in out
    assert "S1 frees ≈" in out and "S2 frees ≈" in out


def test_fixture_dm_is_valid_telegram_html(fixture_dm):
    out = fixture_dm.strip()
    assert len(out) <= di.TELEGRAM_LIMIT
    assert out.count("<b>") == out.count("</b>")
    assert out.count("<i>") == out.count("</i>")
    assert "<" not in out.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
