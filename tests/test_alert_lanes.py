"""Unit tests for the three held-book alert lanes added after the
June 5-9 2026 zero-page incident (held put credit spreads rode an SPX
selloff with no Telegram): spread-defense, held-name news, and
market-pressure. Sheet reads are mocked by feeding the pure plan_*
functions plain dicts shaped like the tab rows."""
from datetime import datetime, timedelta, timezone

from src.schema import us_market_date

from scripts.trigger_alerts import (
    DEFENSE_CALL_APPROACH_MULT,
    DEFENSE_PUT_APPROACH_MULT,
    HELD_NEWS_FRESH_MIN,
    HELD_NEWS_PING_CAP,
    HELD_NEWS_SENT_THRESHOLD,
    HOT_NEWS_FRESH_MIN,
    PRESSURE_ALERT_PCT,
    PRESSURE_WARN_PCT,
    PRESSURE_WORST_N,
    defense_level,
    headline_hash,
    held_news_fresh_cutoff,
    plan_defense_pings,
    plan_held_news_pings,
    plan_market_pressure,
    pressure_severity,
    spread_label,
)

SGT = timezone(timedelta(hours=8))
DAY = "2026-06-10"


def _leg(ticker="NVDA", right="P", strike="190.00", expiry="20260620",
         qty="-1", dte="10", account="caspar", underlying_last="200.00"):
    """A row shaped like the `options` tab (everything is a string,
    exactly as get_all_values returns it)."""
    return {
        "date": "2026-06-10T091500", "account": account, "ticker": ticker,
        "right": right, "strike": strike, "expiry": expiry, "qty": qty,
        "dte": dte, "underlying_last": underlying_last,
    }


# ════════════════════════════════════════════════════════════════════
# Lane 1 — spread defense: level math
# ════════════════════════════════════════════════════════════════════

def test_defense_level_short_put():
    # strike 190 → approach band tops out at 190*1.03 = 195.70
    assert defense_level("P", 190.0, 196.00) == ""
    assert defense_level("P", 190.0, 195.70) == "approach"   # boundary inclusive
    assert defense_level("P", 190.0, 191.00) == "approach"
    assert defense_level("P", 190.0, 190.00) == "breach"     # at the strike
    assert defense_level("P", 190.0, 185.20) == "breach"


def test_defense_level_short_call():
    # strike 360 → approach band starts at 360*0.97 = 349.20
    assert defense_level("C", 360.0, 348.00) == ""
    assert defense_level("C", 360.0, 349.20) == "approach"   # boundary inclusive
    assert defense_level("C", 360.0, 355.00) == "approach"
    assert defense_level("C", 360.0, 360.00) == "breach"
    assert defense_level("C", 360.0, 365.00) == "breach"


def test_defense_level_garbage_inputs():
    assert defense_level("", 190.0, 185.0) == ""
    assert defense_level("X", 190.0, 185.0) == ""
    assert defense_level("P", 0.0, 185.0) == ""
    assert defense_level("P", 190.0, 0.0) == ""


def test_defense_approach_mults_match_spec():
    assert DEFENSE_PUT_APPROACH_MULT == 1.03
    assert DEFENSE_CALL_APPROACH_MULT == 0.97


# ════════════════════════════════════════════════════════════════════
# Lane 1 — spread defense: grouping + plan/dedup
# ════════════════════════════════════════════════════════════════════

def test_spread_label_groups_put_credit_spread():
    short = _leg(strike="190.00", qty="-1")
    long_ = _leg(strike="180.00", qty="1")
    assert spread_label(short, [short, long_]) == "PCS 180/190"


def test_spread_label_groups_call_credit_spread():
    short = _leg(ticker="AVGO", right="C", strike="350.00", qty="-2")
    long_ = _leg(ticker="AVGO", right="C", strike="360.00", qty="2")
    assert spread_label(short, [short, long_]) == "CCS 350/360"


def test_spread_label_naked_short_legs():
    short_put = _leg(qty="-1")
    assert spread_label(short_put, [short_put]) == "CSP"
    short_call = _leg(right="C", qty="-1")
    assert spread_label(short_call, [short_call]) == "CC"


def test_spread_label_ignores_other_expiry_or_ticker():
    short = _leg(strike="190.00", qty="-1", expiry="20260620")
    other_exp = _leg(strike="180.00", qty="1", expiry="20260720")
    other_tk = _leg(ticker="INTC", strike="180.00", qty="1")
    assert spread_label(short, [short, other_exp, other_tk]) == "CSP"


def test_plan_defense_approach_fires_once_per_day():
    legs = [_leg(strike="190.00", qty="-1"), _leg(strike="180.00", qty="1")]
    plans = plan_defense_pings(legs, {"NVDA": 195.0}, set(), DAY, DAY)
    assert len(plans) == 1
    p = plans[0]
    assert p["level"] == "approach"
    assert p["label"] == "PCS 180/190"
    assert p["dte"] == 10
    assert p["key"] == f"defense:NVDA|P190|20260620|approach|{DAY}"
    # Same run state recorded → next run is silent.
    assert plan_defense_pings(legs, {"NVDA": 195.0}, {p["key"]}, DAY, DAY) == []


def test_plan_defense_breach_subsumes_approach():
    legs = [_leg(strike="190.00", qty="-1")]
    plans = plan_defense_pings(legs, {"NVDA": 188.0}, set(), DAY, DAY)
    assert len(plans) == 1
    p = plans[0]
    assert p["level"] == "breach"
    # Gap straight through the strike pages ONCE: the breach marks the
    # approach key too so a later bounce into the band can't page.
    assert f"defense:NVDA|P190|20260620|approach|{DAY}" in p["keys_to_mark"]
    assert f"defense:NVDA|P190|20260620|breach|{DAY}" in p["keys_to_mark"]


def test_plan_defense_escalates_approach_to_breach():
    legs = [_leg(strike="190.00", qty="-1")]
    approach_key = f"defense:NVDA|P190|20260620|approach|{DAY}"
    plans = plan_defense_pings(legs, {"NVDA": 189.5}, {approach_key}, DAY, DAY)
    assert [p["level"] for p in plans] == ["breach"]


def test_plan_defense_rearms_on_later_day():
    legs = [_leg(strike="190.00", qty="-1")]
    prior = {f"defense:NVDA|P190|20260620|breach|{DAY}",
             f"defense:NVDA|P190|20260620|approach|{DAY}"}
    assert plan_defense_pings(legs, {"NVDA": 188.0}, prior, DAY, DAY) == []
    plans = plan_defense_pings(legs, {"NVDA": 188.0}, prior, "2026-06-11", "2026-06-11")
    assert len(plans) == 1   # new day → new key → re-armed


def test_plan_defense_ignores_long_and_safe_legs():
    legs = [
        _leg(strike="180.00", qty="1"),                  # long leg — never paged
        _leg(ticker="IONQ", strike="40.00", qty="-1"),   # short, but safe
    ]
    assert plan_defense_pings(legs, {"NVDA": 150.0, "IONQ": 60.0}, set(), DAY, DAY) == []


def test_plan_defense_falls_back_to_grab_underlying():
    # Ticker missing from live_prices → use the options-tab underlying_last.
    legs = [_leg(strike="190.00", qty="-1", underlying_last="189.00")]
    plans = plan_defense_pings(legs, {}, set(), DAY, DAY)
    assert len(plans) == 1
    assert plans[0]["underlying"] == 189.0
    assert plans[0]["level"] == "breach"


def test_plan_defense_short_call_mirror():
    legs = [_leg(ticker="AVGO", right="C", strike="350.00", qty="-1"),
            _leg(ticker="AVGO", right="C", strike="360.00", qty="1")]
    plans = plan_defense_pings(legs, {"AVGO": 341.0}, set(), DAY, DAY)
    assert len(plans) == 1
    assert plans[0]["level"] == "approach"   # 341 >= 350*0.97 = 339.5
    assert plans[0]["label"] == "CCS 350/360"
    plans = plan_defense_pings(legs, {"AVGO": 351.0}, set(), DAY, DAY)
    assert plans[0]["level"] == "breach"


def test_plan_defense_skips_expired_legs():
    # The IBKR grab can carry already-expired legs for days (settlement
    # lag) — found live in the 2026-06-10 book (OPEN 4.5P exp 20260529).
    dead = _leg(ticker="OPEN", strike="4.50", qty="-1",
                expiry="20260529", dte="0")
    assert plan_defense_pings([dead], {"OPEN": 4.34}, set(), DAY, DAY) == []
    # But a leg expiring TODAY (0 DTE) is exactly when paging matters,
    # and "yesterday" SGT can still be live US-time — both stay eligible.
    for exp in ("20260610", "20260609"):
        live = _leg(strike="190.00", qty="-1", expiry=exp, dte="0")
        plans = plan_defense_pings([live], {"NVDA": 188.0}, set(), DAY, DAY)
        assert len(plans) == 1, exp


def test_plan_defense_dedups_same_strike_across_accounts():
    # Spec keys dedup on (ticker, strike, expiry, level) — both accounts
    # holding the same short strike page once, not twice.
    legs = [_leg(qty="-1", account="caspar"), _leg(qty="-1", account="sarah")]
    plans = plan_defense_pings(legs, {"NVDA": 189.0}, set(), DAY, DAY)
    assert len(plans) == 1


# ════════════════════════════════════════════════════════════════════
# Lane 2 — held-name news: freshness window + dedup keying
# ════════════════════════════════════════════════════════════════════

def _news(ticker="NVDA", headline="NVDA guidance cut", score="-0.5",
          dt="2026-06-10T120000", label="negative"):
    """A row shaped like the news_sentiment tab (all strings)."""
    return {
        "id": "123", "datetime": dt, "ticker": ticker, "headline": headline,
        "summary": "", "source": "Reuters", "url": "https://x",
        "sentiment_score": score, "sentiment_label": label,
        "category": "company", "updated_at": dt,
    }


def test_held_news_window_is_cadence_aware():
    # 2.5h floor — must survive GH cron gaps; never narrower than the
    # macro hot-news window.
    assert HELD_NEWS_FRESH_MIN == 150
    assert HELD_NEWS_FRESH_MIN >= HOT_NEWS_FRESH_MIN


def test_held_news_fresh_cutoff_format():
    now = datetime(2026, 6, 10, 12, 0, 0, tzinfo=SGT)
    cutoff = held_news_fresh_cutoff(now)
    assert cutoff == "2026-06-10T093000"   # 12:00 - 150min = 09:30 SGT


def test_held_news_freshness_window():
    cutoff = "2026-06-10T093000"
    fresh = _news(dt="2026-06-10T093000")   # exactly at cutoff = fresh
    stale = _news(dt="2026-06-10T092959", headline="older story")
    plans = plan_held_news_pings([fresh, stale], {"NVDA"}, set(), cutoff)
    assert [p["headline"] for p in plans] == ["NVDA guidance cut"]


def test_held_news_sentiment_threshold():
    cutoff = "2026-06-10T000000"
    rows = [
        _news(headline="big negative", score="-0.3"),    # |s| == 0.3 → page
        _news(headline="big positive", score="0.31"),
        _news(headline="meh", score="0.29"),             # below → no page
        _news(headline="neutral", score="0"),
    ]
    got = {p["headline"] for p in plan_held_news_pings(rows, {"NVDA"}, set(), cutoff)}
    assert got == {"big negative", "big positive"}
    assert HELD_NEWS_SENT_THRESHOLD == 0.3


def test_held_news_only_held_tickers():
    cutoff = "2026-06-10T000000"
    rows = [_news(ticker="NVDA"), _news(ticker="TSLA", headline="TSLA recall")]
    plans = plan_held_news_pings(rows, {"NVDA", "INTC"}, set(), cutoff)
    assert [p["ticker"] for p in plans] == ["NVDA"]


def test_held_news_dedup_by_headline_hash():
    cutoff = "2026-06-10T000000"
    n = _news()
    key = f"heldnews:{headline_hash(n['headline'])}"
    # Already in the ledger → suppressed.
    assert plan_held_news_pings([n], {"NVDA"}, {key}, cutoff) == []
    # Same story under a second held ticker / different Finnhub id →
    # one page within the run, not two.
    twin = _news(ticker="INTC")
    plans = plan_held_news_pings([n, twin], {"NVDA", "INTC"}, set(), cutoff)
    assert len(plans) == 1


def test_headline_hash_normalises_case_and_whitespace():
    assert headline_hash("NVDA  Guidance Cut ") == headline_hash("nvda guidance cut")
    assert headline_hash("a") != headline_hash("b")
    assert len(headline_hash("anything")) == 16


def test_held_news_cap_keeps_strongest():
    cutoff = "2026-06-10T000000"
    rows = [
        _news(headline=f"story {i}", score=str(s))
        for i, s in enumerate([-0.9, 0.4, -0.6, 0.8, -0.35])
    ]
    plans = plan_held_news_pings(rows, {"NVDA"}, set(), cutoff)
    assert len(plans) == HELD_NEWS_PING_CAP == 3
    assert [abs(p["score"]) for p in plans] == [0.9, 0.8, 0.6]


# ════════════════════════════════════════════════════════════════════
# Lane 3 — market pressure: thresholds + per-day/severity dedup
# ════════════════════════════════════════════════════════════════════

def test_pressure_severity_thresholds():
    assert pressure_severity(-1.0, -1.0) == ""
    assert pressure_severity(-1.25, 0.0) == "WARN"      # boundary inclusive
    assert pressure_severity(0.0, -1.3) == "WARN"       # either index trips
    assert pressure_severity(-2.0, -0.5) == "ALERT"     # boundary inclusive
    assert pressure_severity(-1.6, -2.1) == "ALERT"     # worst reading wins
    assert pressure_severity(None, -2.5) == "ALERT"     # one index missing
    assert pressure_severity(None, None) == ""
    assert PRESSURE_WARN_PCT == -1.25 and PRESSURE_ALERT_PCT == -2.0


def test_pressure_plan_warn_and_heatmap():
    changes = {"SPY": -1.6, "QQQ": -1.0, "AMD": -9.4, "MU": -8.7,
               "INTC": -8.2, "NVDA": -3.1, "IONQ": -2.0, "AVGO": -1.0,
               "TSLA": -99.0}   # not held → excluded from heatmap
    held = {"AMD", "MU", "INTC", "NVDA", "IONQ", "AVGO"}
    plan = plan_market_pressure(changes, held, set(), DAY)
    assert plan is not None
    assert plan["severity"] == "WARN"
    assert plan["key"] == f"pressure:{DAY}|WARN"
    assert plan["keys_to_mark"] == [plan["key"]]   # WARN does not mark ALERT
    # Worst-5 held, most negative first, capped at PRESSURE_WORST_N.
    assert len(plan["worst"]) == PRESSURE_WORST_N == 5
    assert [t for t, _ in plan["worst"]] == ["AMD", "MU", "INTC", "NVDA", "IONQ"]


def test_pressure_plan_alert_marks_warn_too():
    changes = {"SPY": -1.6, "QQQ": -2.1}
    plan = plan_market_pressure(changes, set(), set(), DAY)
    assert plan["severity"] == "ALERT"
    assert set(plan["keys_to_mark"]) == {
        f"pressure:{DAY}|ALERT", f"pressure:{DAY}|WARN"}


def test_pressure_one_page_per_severity_per_day():
    changes = {"SPY": -1.6, "QQQ": -1.0}
    fired = {f"pressure:{DAY}|WARN"}
    assert plan_market_pressure(changes, set(), fired, DAY) is None
    # Escalation to ALERT still pages (different key)...
    changes = {"SPY": -2.4, "QQQ": -1.0}
    plan = plan_market_pressure(changes, set(), fired, DAY)
    assert plan and plan["severity"] == "ALERT"
    # ...and a new day re-arms WARN.
    changes = {"SPY": -1.6, "QQQ": -1.0}
    assert plan_market_pressure(changes, set(), fired, "2026-06-11") is not None


def test_pressure_no_page_after_alert_eases_to_warn_band():
    # ALERT marked both keys; tape easing to -1.5% must not downgrade-page.
    fired = {f"pressure:{DAY}|ALERT", f"pressure:{DAY}|WARN"}
    assert plan_market_pressure({"SPY": -1.5, "QQQ": -1.0}, set(), fired, DAY) is None


def test_pressure_silent_when_indices_missing():
    assert plan_market_pressure({}, {"NVDA"}, set(), DAY) is None


# ════════════════════════════════════════════════════════════════════
# Lane 3 regression — 2026-06-11 incident: SGT-midnight key roll.
#
# The US cash session runs 21:30-04:00 SGT, crossing SGT midnight.
# Keying the pressure dedup to the SGT date re-armed WARN at 00:00 SGT
# mid-session: WARN paged 23:36 SGT Jun 10 (QQQ -1.2786), re-paged
# ~00:10 SGT Jun 11 on the date roll (same selloff), and the deepening
# tape at 01:51-03:32 SGT then logged "pressure=none" — its WARN was
# silently deduped against the midnight re-page. Fix: key on the
# US-Eastern trading date (us_market_date), constant across a session.
# ════════════════════════════════════════════════════════════════════

def test_us_market_date_constant_across_sgt_midnight():
    # Every cycle of the 2026-06-10 US session maps to ONE session day,
    # even though the SGT calendar date flips at 00:00 SGT mid-session.
    incident_cycles_sgt = [
        datetime(2026, 6, 10, 23, 36, tzinfo=SGT),   # WARN paged here
        datetime(2026, 6, 11, 0, 10, tzinfo=SGT),    # old key re-armed here
        datetime(2026, 6, 11, 0, 40, tzinfo=SGT),    # GH cycle, suppressed
        datetime(2026, 6, 11, 3, 21, tzinfo=SGT),    # logged pressure=none
        datetime(2026, 6, 11, 3, 32, tzinfo=SGT),    # logged pressure=none
        datetime(2026, 6, 11, 3, 45, tzinfo=SGT),    # ALERT fired
    ]
    assert {us_market_date(t) for t in incident_cycles_sgt} == {"2026-06-10"}
    # The next US session (21:30 SGT Jun 11 = 09:30 ET Jun 11) is a new day.
    assert us_market_date(datetime(2026, 6, 11, 21, 30, tzinfo=SGT)) == "2026-06-11"


def test_pressure_2026_06_11_incident_regression():
    """Replay the incident cycles with the exact logged SPY/QQQ values,
    marking keys after each page exactly as main()'s send path does."""
    held: set[str] = set()
    fired: set[str] = set()

    def cycle(sgt_dt, spy, qqq):
        plan = plan_market_pressure(
            {"SPY": spy, "QQQ": qqq}, held, fired, us_market_date(sgt_dt))
        if plan:
            fired.update(plan["keys_to_mark"])
        return plan

    # 23:36 SGT Jun 10 — first WARN of the session pages (ledger values).
    plan = cycle(datetime(2026, 6, 10, 23, 36, tzinfo=SGT), -0.9199, -1.2786)
    assert plan and plan["severity"] == "WARN"
    assert plan["key"] == "pressure:2026-06-10|WARN"

    # 00:40 SGT Jun 11 — SGT date rolled, session didn't. Under the old
    # SGT-day keying this cycle re-paged WARN (fresh "2026-06-11" key)
    # and silently consumed the rest of the session's WARN budget.
    assert cycle(datetime(2026, 6, 11, 0, 40, tzinfo=SGT), -0.9226, -1.3012) is None

    # 01:51 / 03:21 / 03:32 SGT — WARN band, already paged this session.
    assert cycle(datetime(2026, 6, 11, 1, 51, tzinfo=SGT), -1.1166, -1.5569) is None
    assert cycle(datetime(2026, 6, 11, 3, 21, tzinfo=SGT), -1.3378, -1.6558) is None
    assert cycle(datetime(2026, 6, 11, 3, 32, tzinfo=SGT), -1.3432, -1.8762) is None

    # 03:45 SGT — escalation to ALERT pages on the SAME session day.
    plan = cycle(datetime(2026, 6, 11, 3, 45, tzinfo=SGT), -1.5386, -2.0951)
    assert plan and plan["severity"] == "ALERT"
    assert plan["key"] == "pressure:2026-06-10|ALERT"
    assert set(plan["keys_to_mark"]) == {
        "pressure:2026-06-10|ALERT", "pressure:2026-06-10|WARN"}

    # Next US session (Jun 11 ET) re-arms WARN at the same tape.
    plan = cycle(datetime(2026, 6, 11, 21, 40, tzinfo=SGT), -1.0, -1.4)
    assert plan and plan["key"] == "pressure:2026-06-11|WARN"


# ════════════════════════════════════════════════════════════════════
# Lane 1 regression — same SGT-midnight key roll, now on defense.
#
# The defense lane keyed its event_key with the SGT calendar date, so
# a leg paged at 23:5x SGT for an in-band underlying would re-page
# minutes later at 00:1x SGT on the date roll — same US session, same
# unchanged position. Identical flaw to the pressure lane (fixed in
# commit 0124992 for ET=2026-06-10 incident); this lane is fixed the
# same way: the dedup `day` is the US-EASTERN trading date
# (us_market_date), constant across one cash session.
# ════════════════════════════════════════════════════════════════════

def test_plan_defense_no_re_arm_across_sgt_midnight_same_us_session():
    """A 23:5x SGT page must not re-page at 00:1x SGT same US session.
    A new US session (next ET day) re-arms."""
    legs = [_leg(strike="190.00", qty="-1")]  # NVDA P190, expiry 20260620
    prior: set[str] = set()

    def cycle(sgt_dt, px):
        day = us_market_date(sgt_dt)
        # SGT-today on these cycles flips at 00:00 SGT — keep it real so
        # the expiry_floor guard is exercised on its actual reference,
        # not on the dedup day.
        sgt_today = sgt_dt.strftime("%Y-%m-%d")
        plans = plan_defense_pings(legs, {"NVDA": px}, prior, day, sgt_today)
        for p in plans:
            prior.update(p["keys_to_mark"])
        return plans

    # 23:50 SGT Jun 10 — NVDA at 195 (just inside the approach band:
    # 190 * 1.03 = 195.70). First page of the session fires approach.
    plans = cycle(datetime(2026, 6, 10, 23, 50, tzinfo=SGT), 195.0)
    assert len(plans) == 1
    assert plans[0]["level"] == "approach"
    assert plans[0]["key"] == "defense:NVDA|P190|20260620|approach|2026-06-10"

    # 00:10 SGT Jun 11 — SGT date rolled, US session didn't. Under the
    # old SGT-day keying this would have re-paged the SAME approach for
    # the SAME unchanged tape. With the fix, dedup key stays on the
    # US-session day 2026-06-10 and the page is suppressed.
    assert cycle(datetime(2026, 6, 11, 0, 10, tzinfo=SGT), 195.0) == []

    # 01:55 / 03:32 SGT — still in approach band, still same session.
    assert cycle(datetime(2026, 6, 11, 1, 55, tzinfo=SGT), 194.5) == []
    assert cycle(datetime(2026, 6, 11, 3, 32, tzinfo=SGT), 193.0) == []

    # 03:45 SGT — gap through the strike escalates approach to breach
    # on the SAME US-session day (key still 2026-06-10).
    plans = cycle(datetime(2026, 6, 11, 3, 45, tzinfo=SGT), 188.0)
    assert len(plans) == 1
    assert plans[0]["level"] == "breach"
    assert plans[0]["key"] == "defense:NVDA|P190|20260620|breach|2026-06-10"

    # Next US session (Jun 11 ET = 21:30 SGT Jun 11 onward) re-arms.
    # NVDA still at 188 — re-page fires under the NEW session-day key.
    plans = cycle(datetime(2026, 6, 11, 21, 40, tzinfo=SGT), 188.0)
    assert len(plans) == 1
    assert plans[0]["level"] == "breach"
    assert plans[0]["key"] == "defense:NVDA|P190|20260620|breach|2026-06-11"


def test_plan_defense_dedup_day_decoupled_from_expiry_guard():
    """`sgt_today` controls the stale-leg expiry guard, `day` controls
    the dedup key — they're decoupled so a leg expiring "yesterday SGT"
    can stay alive in the still-running US session."""
    # NVDA P190 expiring 20260610 — that's "today" SGT (still live US-time).
    live = _leg(strike="190.00", qty="-1", expiry="20260610", dte="0")
    # 00:30 SGT Jun 11: SGT date is 2026-06-11, US-session day is still
    # 2026-06-10. Expiry guard floor = sgt_today - 1 day = 2026-06-10 →
    # leg expiring 20260610 is NOT < 20260610 → stays eligible.
    plans = plan_defense_pings(
        [live], {"NVDA": 188.0}, set(),
        day="2026-06-10", sgt_today="2026-06-11")
    assert len(plans) == 1
    assert plans[0]["level"] == "breach"
    # And the dedup key uses the US-session day, not the SGT date.
    assert plans[0]["key"].endswith("|2026-06-10")
