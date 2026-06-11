"""
trigger_alerts.py — every-N-min poll that fires Telegram pushes when a
WATCHING decision transitions into ACT_NOW, plus three held-book lanes
(spread-defense / held-name news / market pressure).

Mirrors the client-side `evaluateTrigger()` in `pwa/src/data.ts` so a
user who only opens the app once a day still gets paged at the moment
the brain's level + all its gates clear simultaneously.

Inputs (all read from Sheets):
  - decision_queue   → all WATCHING rows
  - live_prices      → ticker → current price + day change % (5-min cron)
  - exposure_posture → for "exposure:NEW_ENTRY_ALLOWED" gate
  - tv_signals       → for "tv_daily:BUY", "tv_weekly:BUY" gates
  - options          → HELD option legs (spread-defense lane)
  - news_sentiment   → held-name news lane (4×/day Finnhub cache; this
                       script makes NO Finnhub calls of its own)

Output:
  - trigger_alerts sheet (per-decision state ledger)
  - macro_alerts_state sheet (per-event dedup ledger, shared by macro +
    defense + held-news + pressure lanes)
  - Telegram push when state transitions DORMANT/CLOSE/READY → ACT_NOW
    (same row staying ACT_NOW across runs is suppressed)
  - Telegram defense page when an underlying approaches/breaches a held
    SHORT strike; held-name strong-sentiment news; SPY/QQQ pressure page

Schedule: every 10 min during US market hours. PRIMARY: local launchd
agent scripts/com.caspar.trigger-alerts.plist → intraday_loop_local.sh
(runs tv_price_refresh THEN this script, so prices are fresh at eval
time). BACKUP: .github/workflows/trigger-alerts.yml — GH cron is
best-effort (4 runs delivered across the whole 2026-06-09 session); the
dedup ledgers make the double-delivery harmless.

Manual run:
  python scripts/trigger_alerts.py        # write + send
  python scripts/trigger_alerts.py --dry  # print, no sheet write, no telegram
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.logging_util import setup_logging  # noqa: E402

from src.sync import load_env       # noqa: E402
from src import sheets as sh        # noqa: E402
from src import schema as S         # noqa: E402
from src import telegram as tg      # noqa: E402
from src.macro_blackouts import MacroFeed  # noqa: E402
from src import macro_playbook as mp  # noqa: E402

# Match the PWA evaluator semantics — these strategies BUY when price
# falls TO the entry level. SELL/TRIM strategies wait for price to RISE
# to entry. Anything else is non-directional and gets skipped.
BUY_STRATEGIES = {"BUY_DIP", "CSP", "PMCC"}
SELL_STRATEGIES = {"TRIM", "CC"}

# Same threshold the PWA uses for the "close" state.
CLOSE_THRESHOLD_PCT = 0.03

# Public PWA URL for Telegram push. Override via env if rebuilt elsewhere.
PWA_URL = "https://xynkro.github.io/CasaaFinance/"

# ────────────────────────────────────────────────────────────────────
# Alert-lane tuning — module-level so tests can import them.
# ────────────────────────────────────────────────────────────────────
# Macro hot-news lane caps (hoisted from main() so the held-news lane
# below can size itself relative to them):
#   - HOT_NEWS_PING_CAP  : max macro-news pings per cron run
#   - HOT_NEWS_FRESH_MIN : recency window — only ping news younger than
#     this. The Finnhub cache holds 24h of news but alerting on hour-old
#     headlines is just spam. 60min keeps pings actionable.
HOT_NEWS_PING_CAP = 3
HOT_NEWS_FRESH_MIN = 60

# Spread-defense lane (incident fix, June 5-9 2026: held put credit
# spreads sailed through an SPX selloff with ZERO pages because the
# decision-lane evaluator only covers BUY/SELL strategies and skips
# spreads as non-directional). For every SHORT leg in the options book:
#   put  : underlying <= strike × 1.03 → "approach", <= strike → "breach"
#   call : underlying >= strike × 0.97 → "approach", >= strike → "breach"
# Each level pages once per (ticker, strike, expiry) per SGT day — the
# dedup key embeds the day, so a strike that recovers and re-breaches on
# a later day re-arms naturally.
DEFENSE_PUT_APPROACH_MULT = 1.03
DEFENSE_CALL_APPROACH_MULT = 0.97

# Held-name news lane: page on strong-sentiment fresh news for HELD
# tickers, read from the news_sentiment tab (written 4×/day by
# finnhub_news_insider.py — this lane adds ZERO new Finnhub calls).
#   - threshold: |sentiment_score| >= 0.3 (heuristic scale is -1..+1)
#   - freshness: cadence-aware. The evaluating cron is best-effort (GH
#     delivered 4 runs across the whole 2026-06-09 session — gaps well
#     over 2h), so a 60-min window like HOT_NEWS_FRESH_MIN would
#     silently drop anything that landed inside a cron gap. 2.5h is
#     wide enough to survive those gaps while staying actionable; the
#     headline-hash dedup means the wider window can't double-page.
HELD_NEWS_SENT_THRESHOLD = 0.3
HELD_NEWS_FRESH_MIN = max(HOT_NEWS_FRESH_MIN, 150)
HELD_NEWS_PING_CAP = 3  # same flood-protection precedent as HOT_NEWS_PING_CAP

# Market-pressure lane ("time to get out"): SPY/QQQ day-change
# thresholds in percent. One page per severity per US-session day
# (US-Eastern date — NOT the SGT date: the US session crosses SGT
# midnight, and SGT-date keying re-armed WARN at 00:00 SGT mid-session
# in the 2026-06-11 incident); an ALERT also marks WARN as fired so a
# tape easing back into the WARN band doesn't downgrade-page afterwards
# (WARN→ALERT escalation still pages).
PRESSURE_WARN_PCT = -1.25
PRESSURE_ALERT_PCT = -2.0
PRESSURE_WORST_N = 5  # worst held names shown in the mini-heatmap


def _f(v, default: float = 0.0) -> float:
    """Sheet-cell float parse — '' / None / garbage → default."""
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


@dataclass
class Decision:
    """Subset of decision_queue row needed for trigger eval."""
    date: str
    account: str
    ticker: str
    strategy: str
    strike: str
    status: str
    entry: float
    accumulation_plan: str
    gates: str   # JSON-encoded array (Phase 6) — empty for legacy rows


@dataclass
class TriggerEval:
    state: str          # dormant | close | ready | act_now
    direction: str      # buy | trim
    pct_to_trigger: float
    blocking_gates: list[str]


def decision_key(d: Decision) -> str:
    """Mirror of pwa/src/lib/decisionActions.ts keyForDecision()."""
    date = (d.date or "")[:10]
    account = (d.account or "").lower()
    ticker = (d.ticker or "").upper()
    strategy = (d.strategy or "").upper()
    try:
        strike_num = float(d.strike or 0)
        strike_str = f"{strike_num:.2f}" if strike_num else "0.00"
    except (TypeError, ValueError):
        strike_str = "0.00"
    return f"{date}|{account}|{ticker}|{strategy}|{strike_str}"


def parse_gates(gates_str: str) -> list[str]:
    """Parse the JSON-encoded gates array; empty list on missing/invalid."""
    if not gates_str:
        return []
    try:
        parsed = json.loads(gates_str)
        if isinstance(parsed, list):
            return [str(g) for g in parsed if g]
    except (json.JSONDecodeError, ValueError):
        pass
    return []


def evaluate_gate(
    gate: str,
    exposure_rec: str,
    tv_daily_rec: str,
    tv_weekly_rec: str,
) -> str:
    """Return non-empty block reason, or empty string when gate passes."""
    if ":" in gate:
        gtype, required = gate.split(":", 1)
    else:
        gtype, required = gate, ""
    gtype = gtype.strip().lower()
    required = required.strip().upper()

    if gtype == "exposure":
        rec = (exposure_rec or "").upper()
        if not rec:
            return f"exposure unknown, need {required}"
        return "" if rec == required else f"exposure {rec}, need {required}"
    if gtype == "tv_daily":
        rec = (tv_daily_rec or "").upper()
        if not rec:
            return f"TV daily unknown, need {required}"
        ok = (
            ("BUY" in rec) if required == "BUY"
            else ("SELL" in rec) if required == "SELL"
            else (rec == required)
        )
        return "" if ok else f"TV daily={rec}, need {required}"
    if gtype == "tv_weekly":
        rec = (tv_weekly_rec or "").upper()
        if not rec:
            return f"TV weekly unknown, need {required}"
        ok = (
            ("BUY" in rec) if required == "BUY"
            else ("SELL" in rec) if required == "SELL"
            else (rec == required)
        )
        return "" if ok else f"TV weekly={rec}, need {required}"
    if gtype == "earnings_clear":
        return ""  # informational marker — brain already filtered
    return f"manual gate: {gate}"


def evaluate_trigger(
    d: Decision,
    current_price: float | None,
    exposure_rec: str,
    tv_daily_rec: str,
    tv_weekly_rec: str,
) -> TriggerEval | None:
    """Mirror of pwa/src/data.ts evaluateTrigger().

    Returns None when the decision is unevaluable. Callers should use
    `evaluate_trigger_with_reason()` instead if they need to know WHY
    something was skipped (for logging).
    """
    res = evaluate_trigger_with_reason(d, current_price, exposure_rec, tv_daily_rec, tv_weekly_rec)
    return res[0]


def evaluate_trigger_with_reason(
    d: Decision,
    current_price: float | None,
    exposure_rec: str,
    tv_daily_rec: str,
    tv_weekly_rec: str,
) -> tuple[TriggerEval | None, str]:
    """Return (eval | None, skip_reason). Skip reason is empty when
    the decision is evaluable. Used by the cron's per-row logging so
    silent drops are now visible.
    """
    if (d.status or "").lower() != "watching":
        return None, f"status={d.status or '?'} (not watching)"
    entry = float(d.entry or 0)
    if not entry:
        return None, "no entry price set"
    if not current_price:
        return None, "no live price available"

    strat = (d.strategy or "").upper()
    is_buy = strat in BUY_STRATEGIES
    is_sell = strat in SELL_STRATEGIES
    if not is_buy and not is_sell:
        return None, f"non-directional strategy '{strat or '(empty)'}'"

    pct = (current_price - entry) / entry if is_buy else (entry - current_price) / entry

    # Gates: prefer structured `gates` field, fall back to plan parsing.
    gates: list[str] = []
    structured = parse_gates(d.gates)
    if structured:
        for g in structured:
            block = evaluate_gate(g, exposure_rec, tv_daily_rec, tv_weekly_rec)
            if block:
                gates.append(block)
    else:
        # Legacy fallback (mirror of PWA evaluator).
        plan_lower = (d.accumulation_plan or "").lower()
        if any(tok in plan_lower for tok in [
            "new_entry_allowed", "cash_priority blocks", "ceiling ≥", "exposure_ceiling",
        ]):
            rec = (exposure_rec or "").upper()
            if rec and rec != "NEW_ENTRY_ALLOWED":
                gates.append(f"exposure {rec}, need NEW_ENTRY_ALLOWED")
        if any(tok in plan_lower for tok in [
            "tv daily=buy", "tv daily flips", "tv daily=str",
        ]):
            rec = (tv_daily_rec or "").upper()
            if rec and "BUY" not in rec:
                gates.append(f"TV daily={rec}, need BUY")

    if pct <= 0:
        state = "act_now" if not gates else "ready"
    elif pct <= CLOSE_THRESHOLD_PCT:
        state = "close"
    else:
        state = "dormant"

    return (
        TriggerEval(
            state=state,
            direction="buy" if is_buy else "trim",
            pct_to_trigger=pct,
            blocking_gates=gates,
        ),
        "",
    )


def load_decisions(client, logger: logging.Logger) -> list[Decision]:
    """Load latest watching decision rows from decision_queue sheet."""
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.DecisionRow.TAB_NAME)
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []
    hdr = rows[0]

    def col(name: str) -> int:
        try:
            return hdr.index(name)
        except ValueError:
            return -1

    c_date     = col("date")
    c_account  = col("account")
    c_ticker   = col("ticker")
    c_status   = col("status")
    c_entry    = col("entry")
    c_strategy = col("strategy")
    c_strike   = col("strike")
    c_plan     = col("accumulation_plan")
    c_gates    = col("gates")

    out: list[Decision] = []
    # Latest day only — match the PWA's `latestGroup()` semantics.
    if c_date < 0:
        return []
    latest_date = ""
    for r in rows[1:]:
        if not r or len(r) <= c_date:
            continue
        d = r[c_date][:10]
        if d > latest_date:
            latest_date = d
    if not latest_date:
        return []

    for r in rows[1:]:
        if not r or len(r) <= max(c_date, c_status, c_entry):
            continue
        if r[c_date][:10] != latest_date:
            continue
        if (r[c_status] or "").lower() != "watching":
            continue
        try:
            entry = float(r[c_entry] or 0)
        except (TypeError, ValueError):
            entry = 0.0
        out.append(Decision(
            date=r[c_date] if c_date >= 0 else "",
            account=r[c_account] if c_account >= 0 and len(r) > c_account else "",
            ticker=r[c_ticker] if c_ticker >= 0 and len(r) > c_ticker else "",
            strategy=r[c_strategy] if c_strategy >= 0 and len(r) > c_strategy else "",
            strike=r[c_strike] if c_strike >= 0 and len(r) > c_strike else "",
            status="watching",
            entry=entry,
            accumulation_plan=r[c_plan] if c_plan >= 0 and len(r) > c_plan else "",
            gates=r[c_gates] if c_gates >= 0 and len(r) > c_gates else "",
        ))
    logger.info(f"Loaded {len(out)} watching decisions for {latest_date}")
    return out


def load_portfolio_tickers(client) -> set[str]:
    """Return uppercase ticker set held across both accounts (latest grab).

    Used by the macro-news mirror logic — when a hot headline mentions any
    of these tickers, the ping is also routed to Multi Day Swing so the
    user sees portfolio-relevant news alongside their decisions topic.
    """
    out: set[str] = set()
    ss = sh._open_sheet(client)
    for tab in ("positions_caspar", "positions_sarah"):
        try:
            ws = ss.worksheet(tab)
        except Exception:
            continue
        rows = ws.get_all_values()
        if len(rows) < 2:
            continue
        hdr = rows[0]
        try:
            c_d = hdr.index("date")
            c_t = hdr.index("ticker")
        except ValueError:
            continue
        # Latest date — same convention as the PWA's `latestGroup()`.
        latest = max((r[c_d] for r in rows[1:] if len(r) > c_d and r[c_d]), default="")
        if not latest:
            continue
        for r in rows[1:]:
            if len(r) > max(c_d, c_t) and r[c_d] == latest and r[c_t]:
                out.add(r[c_t].strip().upper())
    return out


def load_live_quotes(client) -> tuple[dict[str, float], dict[str, float]]:
    """(ticker→last, ticker→day change %) from live_prices.

    One read feeds both the decision lane (last) and the defense /
    market-pressure lanes (last + change_pct). SPY/QQQ are in the feed
    as of commit 991f6c7.
    """
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.LivePriceRow.TAB_NAME)
    except Exception:
        return {}, {}
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {}, {}
    hdr = rows[0]
    try:
        c_t = hdr.index("ticker")
        c_l = hdr.index("last")
    except ValueError:
        return {}, {}
    c_c = hdr.index("change_pct") if "change_pct" in hdr else -1
    prices: dict[str, float] = {}
    changes: dict[str, float] = {}
    for r in rows[1:]:
        if len(r) <= max(c_t, c_l):
            continue
        t = r[c_t].upper()
        try:
            prices[t] = float(r[c_l] or 0)
        except (TypeError, ValueError):
            continue
        if c_c >= 0 and len(r) > c_c and str(r[c_c]).strip() != "":
            try:
                changes[t] = float(r[c_c])
            except (TypeError, ValueError):
                pass
    return prices, changes


# ════════════════════════════════════════════════════════════════════
# Spread-defense lane (incident fix) — short-strike proximity on HELD
# option legs. The decision lane above only covers BUY/SELL strategies;
# held spreads had INFINITE alert latency by design until this.
# ════════════════════════════════════════════════════════════════════

def defense_level(right: str, strike: float, underlying: float) -> str:
    """Return 'breach' | 'approach' | '' for a SHORT option leg.

    Puts : underlying <= strike                              → breach
           underlying <= strike × DEFENSE_PUT_APPROACH_MULT  → approach
    Calls: underlying >= strike                              → breach
           underlying >= strike × DEFENSE_CALL_APPROACH_MULT → approach
    """
    if strike <= 0 or underlying <= 0:
        return ""
    r = (right or "").strip().upper()[:1]
    if r == "P":
        if underlying <= strike:
            return "breach"
        if underlying <= strike * DEFENSE_PUT_APPROACH_MULT:
            return "approach"
    elif r == "C":
        if underlying >= strike:
            return "breach"
        if underlying >= strike * DEFENSE_CALL_APPROACH_MULT:
            return "approach"
    return ""


def spread_label(short_leg: dict, all_legs: list[dict]) -> str:
    """Human label for the structure a short leg belongs to.

    Pairs the short leg with a LONG leg of the same account + ticker +
    right + expiry → 'PCS 180/190' / 'CCS 350/360' (strikes low/high).
    Unpaired short put → 'CSP'; unpaired short call → 'CC'. The defense
    logic only needs the short leg — the label is message context.
    """
    r = (short_leg.get("right") or "").strip().upper()[:1]
    me = (
        short_leg.get("account") or "",
        (short_leg.get("ticker") or "").strip().upper(),
        r,
        str(short_leg.get("expiry") or ""),
    )
    longs = [
        l for l in all_legs
        if _f(l.get("qty")) > 0
        and (
            l.get("account") or "",
            (l.get("ticker") or "").strip().upper(),
            (l.get("right") or "").strip().upper()[:1],
            str(l.get("expiry") or ""),
        ) == me
    ]
    if longs:
        kind = "PCS" if r == "P" else "CCS"
        lo, hi = sorted([_f(short_leg.get("strike")), _f(longs[0].get("strike"))])
        return f"{kind} {lo:g}/{hi:g}"
    return "CSP" if r == "P" else "CC"


def plan_defense_pings(
    legs: list[dict],
    live_prices: dict[str, float],
    prior_keys: set[str],
    day: str,
) -> list[dict]:
    """Plan defense pings for SHORT legs at/inside the approach band.
    Pure — testable without Sheets.

    Dedup: event_key = "defense:<TICKER>|<R><strike>|<expiry>|<level>|<day>"
    in the macro_alerts_state ledger — keyed (ticker, strike, expiry,
    level) with the SGT day appended, so each level pages ONCE per
    position per day and a recover-then-re-breach on a later day
    re-arms. A 'breach' plan also marks the 'approach' key so a gap
    straight through the strike pages once (the breach), not twice.
    """
    # Expired-leg guard: the IBKR grab can carry already-expired legs for
    # a few days (assignment/settlement lag) — paging defense on those is
    # noise. SGT runs ~half a day ahead of the US session, so only skip
    # when the expiry is MORE than 1 day before the SGT date (a leg
    # expiring "yesterday" SGT can still be live US-time).
    try:
        expiry_floor = (date.fromisoformat(day) - timedelta(days=1)).strftime("%Y%m%d")
    except ValueError:
        expiry_floor = ""

    plans: list[dict] = []
    seen: set[str] = set()
    for leg in legs:
        if _f(leg.get("qty")) >= 0:
            continue  # defense logic only needs SHORT legs
        ticker = (leg.get("ticker") or "").strip().upper()
        right = (leg.get("right") or "").strip().upper()[:1]
        strike = _f(leg.get("strike"))
        expiry = str(leg.get("expiry") or "")
        if expiry_floor and len(expiry) == 8 and expiry < expiry_floor:
            continue  # already expired — stale grab row, not a live risk
        # live_prices is the 5-min feed; fall back to the grab-time
        # underlying_last only when the feed misses the ticker.
        underlying = live_prices.get(ticker) or _f(leg.get("underlying_last"))
        level = defense_level(right, strike, underlying)
        if not level:
            continue

        def _key(lv: str) -> str:
            return f"defense:{ticker}|{right}{strike:g}|{expiry}|{lv}|{day}"

        key = _key(level)
        if key in prior_keys or key in seen:
            continue
        seen.add(key)
        keys_to_mark = [key]
        if level == "breach":
            keys_to_mark.append(_key("approach"))  # breach subsumes approach
        plans.append({
            "key": key,
            "keys_to_mark": keys_to_mark,
            "ticker": ticker,
            "right": right,
            "strike": strike,
            "expiry": expiry,
            "dte": int(_f(leg.get("dte"))),
            "underlying": underlying,
            "level": level,
            "label": spread_label(leg, legs),
            "account": (leg.get("account") or "").lower(),
        })
    return plans


def load_open_option_legs(client, logger: logging.Logger) -> list[dict]:
    """Latest-grab rows from the `options` tab as header-keyed dicts
    (one per leg: ticker/right/strike/expiry/qty/... per S.OptionRow).

    The tab is append-per-grab with audit timestamps in `date`
    ('YYYY-MM-DDTHHMMSS'), so "open positions" = rows whose date equals
    the max date value — same exact-timestamp convention as
    telegram_portfolio_responder.py.
    """
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.OptionRow.TAB_NAME)
    except Exception:
        return []
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []
    hdr = rows[0]
    try:
        c_date = hdr.index("date")
    except ValueError:
        return []
    latest = max((r[c_date] for r in rows[1:] if r and len(r) > c_date), default="")
    if not latest:
        return []
    out: list[dict] = []
    for r in rows[1:]:
        if not r or len(r) <= c_date or r[c_date] != latest:
            continue
        out.append({hdr[i]: (r[i] if i < len(r) else "") for i in range(len(hdr))})
    logger.info(f"Loaded {len(out)} open option legs (grab {latest})")
    return out


# ════════════════════════════════════════════════════════════════════
# Held-name news lane — strong-sentiment fresh news on HELD tickers.
# Reads the news_sentiment tab only (no new Finnhub quota); before this
# lane, held-name news reached no push channel (its only consumer was
# the PWA mirror).
# ════════════════════════════════════════════════════════════════════

def headline_hash(headline: str) -> str:
    """Stable 16-hex dedup hash of a headline. Case/whitespace
    normalised so the same story re-pulled under another Finnhub id
    (or listed under a second held ticker) doesn't re-page."""
    norm = " ".join((headline or "").lower().split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def held_news_fresh_cutoff(now_sgt: datetime | None = None) -> str:
    """SGT-iso lower bound ('YYYY-MM-DDTHHMMSS') for fresh held-name
    news. Lexicographic-comparable with news_sentiment.datetime, which
    finnhub_news_insider writes SGT-anchored."""
    now = now_sgt or datetime.now(timezone(timedelta(hours=8)))
    return (now - timedelta(minutes=HELD_NEWS_FRESH_MIN)).strftime("%Y-%m-%dT%H%M%S")


def plan_held_news_pings(
    news_rows: list[dict],
    held_tickers: set[str],
    prior_keys: set[str],
    fresh_cutoff: str,
) -> list[dict]:
    """Plan held-name news pings. Pure — testable without Sheets.

    Page when a HELD ticker has news newer than `fresh_cutoff` with
    |sentiment_score| >= HELD_NEWS_SENT_THRESHOLD. Dedup key =
    "heldnews:<headline hash>" in the macro_alerts_state ledger. Capped
    at HELD_NEWS_PING_CAP per run, strongest sentiment first.
    """
    candidates: list[dict] = []
    seen: set[str] = set()
    for n in news_rows:
        ticker = (n.get("ticker") or "").strip().upper()
        if ticker not in held_tickers:
            continue
        if (n.get("datetime") or "") < fresh_cutoff:
            continue
        score = _f(n.get("sentiment_score"))
        if abs(score) < HELD_NEWS_SENT_THRESHOLD:
            continue
        key = f"heldnews:{headline_hash(n.get('headline') or '')}"
        if key in prior_keys or key in seen:
            continue
        seen.add(key)
        candidates.append({
            "key": key,
            "ticker": ticker,
            "headline": n.get("headline") or "",
            "score": score,
            "label": n.get("sentiment_label") or "",
            "source": n.get("source") or "",
            "url": n.get("url") or "",
            "datetime": n.get("datetime") or "",
        })
    candidates.sort(key=lambda c: abs(c["score"]), reverse=True)
    return candidates[:HELD_NEWS_PING_CAP]


def load_news_sentiment_rows(client) -> list[dict]:
    """All news_sentiment rows as header-keyed dicts. Freshness /
    threshold filtering happens in plan_held_news_pings (one read,
    pure logic downstream)."""
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.NewsSentimentRow.TAB_NAME)
    except Exception:
        return []
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []
    hdr = rows[0]
    return [
        {hdr[i]: (r[i] if i < len(r) else "") for i in range(len(hdr))}
        for r in rows[1:] if r
    ]


# ════════════════════════════════════════════════════════════════════
# Market-pressure lane — SPY/QQQ tape check ("time to get out").
# ════════════════════════════════════════════════════════════════════

def pressure_severity(spy_chg: float | None, qqq_chg: float | None) -> str:
    """'ALERT' | 'WARN' | '' from SPY/QQQ day-change %. EITHER index
    crossing a threshold trips that severity; the worse reading wins."""
    vals = [v for v in (spy_chg, qqq_chg) if v is not None]
    if not vals:
        return ""
    worst = min(vals)
    if worst <= PRESSURE_ALERT_PCT:
        return "ALERT"
    if worst <= PRESSURE_WARN_PCT:
        return "WARN"
    return ""


def plan_market_pressure(
    live_changes: dict[str, float],
    held_tickers: set[str],
    prior_keys: set[str],
    day: str,
) -> dict | None:
    """Plan the market-pressure page, or None. Pure — testable.

    Dedup: event_key = "pressure:<day>|<severity>" — one page per
    severity per `day`. Callers must pass the US-EASTERN trading date
    (S.us_market_date()), not the SGT date: the US cash session runs
    21:30-04:00 SGT, so an SGT-date key rolls over mid-session at
    00:00 SGT — that re-armed WARN minutes after midnight in the
    2026-06-11 incident and then swallowed the deepening tape's WARN
    for the rest of the session. An ALERT also marks the WARN key so
    the tape easing back into the WARN band later doesn't
    downgrade-page; WARN→ALERT escalation still pages (different key).
    Includes the worst-PRESSURE_WORST_N held names by day change as a
    mini-heatmap.
    """
    spy = live_changes.get("SPY")
    qqq = live_changes.get("QQQ")
    sev = pressure_severity(spy, qqq)
    if not sev:
        return None
    key = f"pressure:{day}|{sev}"
    if key in prior_keys:
        return None
    keys_to_mark = [key]
    if sev == "ALERT":
        keys_to_mark.append(f"pressure:{day}|WARN")
    worst = sorted(
        ((t, live_changes[t]) for t in held_tickers if t in live_changes),
        key=lambda x: x[1],
    )[:PRESSURE_WORST_N]
    return {
        "key": key,
        "keys_to_mark": keys_to_mark,
        "severity": sev,
        "spy": spy,
        "qqq": qqq,
        "worst": worst,
    }


def load_exposure_rec(client) -> str:
    """Latest exposure_posture.recommendation, or empty string."""
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.ExposurePostureRow.TAB_NAME)
    except Exception:
        return ""
    rows = ws.get_all_values()
    if len(rows) < 2:
        return ""
    hdr = rows[0]
    try:
        c_d = hdr.index("date")
        c_r = hdr.index("recommendation")
    except ValueError:
        return ""
    latest = ""
    rec = ""
    for r in rows[1:]:
        if len(r) <= max(c_d, c_r):
            continue
        if r[c_d] > latest:
            latest = r[c_d]
            rec = r[c_r]
    return rec


def load_macro_prints(client) -> list[dict]:
    """Today's US macro releases that have PRINTED — actual + forecast both
    present. Feeds the macro-surprise playbook (interpret_surprise filters down
    to the events it has a take on)."""
    try:
        ss = sh._open_sheet(client)
        rows = ss.worksheet(S.EconomicEventRow.TAB_NAME).get_all_values()
    except Exception:
        return []
    if len(rows) < 2:
        return []
    ci = {h: i for i, h in enumerate(rows[0])}
    need = ("date", "event", "actual", "forecast")
    if not all(k in ci for k in need):
        return []
    today = date.today().isoformat()
    out: list[dict] = []
    for r in rows[1:]:
        def g(k):
            return r[ci[k]] if k in ci and len(r) > ci[k] else ""
        if g("date")[:10] != today:
            continue
        if (g("country") or "").upper() != "US":
            continue
        if not str(g("actual")).strip() or not str(g("forecast")).strip():
            continue
        out.append({
            "date": g("date"), "event": g("event"), "actual": g("actual"),
            "forecast": g("forecast"), "previous": g("previous"),
            "unit": g("unit"), "impact": g("impact"),
        })
    return out


def _regime_context(client) -> str:
    """The FREE 'so what for my book RIGHT NOW' — no AI, no tokens. Joins the
    headline to live state we already compute: exposure posture (can I add risk)
    + the SPY GEX gate (is premium-selling safe today). This is context, not
    interpretation — which is exactly why it doesn't read as canned filler."""
    bits: list[str] = []
    try:
        rec = load_exposure_rec(client)
        if rec and rec != "NEW_ENTRY_ALLOWED":
            bits.append(f"exposure {rec}")
    except Exception:
        pass
    try:
        ss = sh._open_sheet(client)
        rows = ss.worksheet(S.GexRegimeRow.TAB_NAME).get_all_values()
        if len(rows) > 1:
            ci = {h: i for i, h in enumerate(rows[0])}
            spy = [r for r in rows[1:]
                   if len(r) > ci.get("symbol", 99) and r[ci["symbol"]].upper() == "SPY"]
            if spy and "premium_gate" in ci:
                gate = spy[-1][ci["premium_gate"]]
                regime = spy[-1][ci["regime"]] if "regime" in ci else ""
                if gate and gate != "NORMAL":
                    bits.append(f"GEX {regime or gate}")
    except Exception:
        pass
    return " · ".join(bits)


def load_tv_recs(client) -> tuple[dict[str, str], dict[str, str]]:
    """(daily_rec_by_ticker, weekly_rec_by_ticker) — latest per (ticker, interval)."""
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.TvSignalRow.TAB_NAME)
    except Exception:
        return {}, {}
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {}, {}
    hdr = rows[0]
    try:
        c_date     = hdr.index("date")
        c_ticker   = hdr.index("ticker")
        c_interval = hdr.index("interval")
        c_rec      = hdr.index("recommendation")
    except ValueError:
        return {}, {}
    # Keep latest row per (ticker, interval).
    latest: dict[tuple[str, str], tuple[str, str]] = {}  # (t,i) -> (date, rec)
    for r in rows[1:]:
        if len(r) <= max(c_date, c_ticker, c_interval, c_rec):
            continue
        key = (r[c_ticker].upper(), r[c_interval])
        if key not in latest or r[c_date] > latest[key][0]:
            latest[key] = (r[c_date], r[c_rec])
    daily: dict[str, str] = {}
    weekly: dict[str, str] = {}
    for (t, interval), (_d, rec) in latest.items():
        if interval == "1d":
            daily[t] = rec
        elif interval == "1W":
            weekly[t] = rec
    return daily, weekly


def load_alert_state(client) -> dict[str, dict]:
    """Existing trigger_alerts rows keyed by decision_key."""
    sh.ensure_headers(client, S.TriggerAlertRow.TAB_NAME, S.TriggerAlertRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.TriggerAlertRow.TAB_NAME)
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {}
    hdr = rows[0]
    out: dict[str, dict] = {}
    for r in rows[1:]:
        if not r:
            continue
        rec = {hdr[i]: (r[i] if i < len(r) else "") for i in range(len(hdr))}
        key = rec.get("decision_key", "")
        if key:
            out[key] = rec
    return out


def load_macro_alert_state(client) -> dict[str, dict]:
    """Existing macro_alerts_state rows keyed by event_key.

    Empty dict when sheet is missing — the next write will auto-create
    via ensure_headers.
    """
    sh.ensure_headers(client, S.MacroAlertStateRow.TAB_NAME, S.MacroAlertStateRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.MacroAlertStateRow.TAB_NAME)
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {}
    hdr = rows[0]
    out: dict[str, dict] = {}
    for r in rows[1:]:
        if not r:
            continue
        rec = {hdr[i]: (r[i] if i < len(r) else "") for i in range(len(hdr))}
        key = rec.get("event_key", "")
        if key:
            out[key] = rec
    return out


def upsert_macro_alert_state(
    client,
    new_rows: list[S.MacroAlertStateRow],
    logger: logging.Logger,
) -> int:
    """UPSERT keyed by event_key. Drops rows older than 7 days on
    every write to keep the sheet bounded.
    """
    if not new_rows:
        return 0
    sh.ensure_headers(client, S.MacroAlertStateRow.TAB_NAME, S.MacroAlertStateRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.MacroAlertStateRow.TAB_NAME)
    existing = ws.get_all_values()
    hdr = existing[0] if existing else list(S.MacroAlertStateRow.HEADERS)

    # Cutoff: drop any row whose event_time is older than 7 days from now.
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H%M%S")

    new_keys = {r.event_key for r in new_rows}
    keep: list[list[str]] = [hdr]
    pruned = 0
    for r in existing[1:]:
        if not r:
            continue
        if r[0] in new_keys:
            continue  # being replaced
        # Prune by event_time (col 3) being older than cutoff.
        try:
            event_time = r[3] if len(r) > 3 else ""
            if event_time and event_time < cutoff:
                pruned += 1
                continue
        except (IndexError, TypeError):
            pass
        keep.append(r)
    keep.extend(r.to_row() for r in new_rows)

    sh.upsert_tab(ws, keep)
    logger.info(f"✓ macro_alerts_state upserted: {len(new_rows)} (pruned {pruned} >7d old)")
    return len(new_rows)


def upsert_alert_state(client, rows: list[S.TriggerAlertRow], logger: logging.Logger) -> int:
    """UPSERT keyed by decision_key. Mirror of api_usage_scrape pattern."""
    sh.ensure_headers(client, S.TriggerAlertRow.TAB_NAME, S.TriggerAlertRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.TriggerAlertRow.TAB_NAME)
    existing = ws.get_all_values()
    hdr = existing[0] if existing else list(S.TriggerAlertRow.HEADERS)

    new_keys = {r.decision_key for r in rows}
    keep: list[list[str]] = [hdr]
    for r in existing[1:]:
        if not r:
            continue
        if r[0] in new_keys:
            continue
        keep.append(r)
    keep.extend(r.to_row() for r in rows)

    sh.upsert_tab(ws, keep)
    logger.info(f"✓ trigger_alerts upserted: {len(rows)}")
    return len(rows)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry", action="store_true", help="Print plan, no sheet write, no Telegram")
    p.add_argument("--force-resend", action="store_true",
                   help="Send Telegram even if last_alert_state was already act_now (debugging)")
    args = p.parse_args()

    logger = setup_logging("trigger-alerts")
    logger.info(f"trigger_alerts start (dry={args.dry}, force_resend={args.force_resend})")

    load_env()
    client = sh.authenticate()

    decisions = load_decisions(client, logger)
    if not decisions:
        logger.info("No watching decisions — nothing to do")
        return 0

    live_prices, live_changes = load_live_quotes(client)
    exposure_rec = load_exposure_rec(client)
    tv_daily, tv_weekly = load_tv_recs(client)
    prior_alerts = load_alert_state(client)

    # Macro-blackout gate (ported from ZeroDTE/backend/app/macro_news.py).
    # Within ±15 min of a high-impact US event, defer Telegram pushes
    # so we don't page "ACT NOW" 5 minutes before FOMC/CPI/NFP. Same
    # failure-mode protection ZeroDTE uses for 0DTE entries.
    macro = MacroFeed.fetch()
    in_blackout, blackout_event = macro.in_blackout_window()
    next_hi = macro.next_high_impact(within_hours=24)
    prior_macro_alerts = load_macro_alert_state(client)

    logger.info(
        f"Context: live_prices={len(live_prices)}  exposure={exposure_rec or '?'}  "
        f"tv_daily={len(tv_daily)}  tv_weekly={len(tv_weekly)}  prior_alerts={len(prior_alerts)}  "
        f"macro_events={len(macro.calendar)}"
    )
    if in_blackout and blackout_event:
        logger.warning(
            f"⚠ MACRO BLACKOUT: {blackout_event['event']} "
            f"in {blackout_event['_minutes_until']:+d}min — Telegram pushes will be deferred"
        )
    elif next_hi:
        logger.info(
            f"Next high-impact: {next_hi['event']} in {next_hi['_minutes_until']}min"
        )

    # Soft-alert opt-in. When set to "true" (env var or workflow input),
    # CLOSE-state transitions (within 3% of trigger but not crossed) will
    # fire a distinct, lower-priority Telegram. Default off so existing
    # behaviour is unchanged.
    include_close = os.environ.get("TRIGGER_ALERTS_INCLUDE_CLOSE", "").lower() in ("true", "1", "yes")

    now_iso = S.now_sgt_iso()
    state_rows: list[S.TriggerAlertRow] = []
    fires: list[tuple[Decision, TriggerEval, float]] = []
    soft_fires: list[tuple[Decision, TriggerEval, float]] = []
    skipped: list[tuple[Decision, str]] = []

    for d in decisions:
        cur = live_prices.get(d.ticker.upper())
        ev, skip_reason = evaluate_trigger_with_reason(
            d, cur, exposure_rec,
            tv_daily.get(d.ticker.upper(), ""),
            tv_weekly.get(d.ticker.upper(), ""),
        )
        if ev is None:
            skipped.append((d, skip_reason))
            continue

        key = decision_key(d)
        prior = prior_alerts.get(key, {})
        prior_state       = (prior.get("last_state") or "").lower()
        prior_alert_state = (prior.get("last_alert_state") or "").lower()

        # Hard-fire criteria: NEW transition into act_now.
        # - Skip if we already alerted on act_now for this row.
        # - Skip if prior_state was act_now too (same fire, just hovering).
        should_fire = (
            ev.state == "act_now"
            and prior_alert_state != "act_now"
            and prior_state != "act_now"
        ) or (args.force_resend and ev.state == "act_now")

        # Soft-fire criteria (opt-in): NEW transition into close from
        # dormant. Suppress repeats by checking prior_alert_state too,
        # so a price hovering close→ready→close doesn't re-page.
        should_soft_fire = include_close and (
            ev.state == "close"
            and prior_alert_state not in ("close", "act_now")
            and prior_state not in ("close", "act_now")
        )

        if should_fire:
            new_alert_state = "act_now"
            new_alert_at    = now_iso
        elif should_soft_fire:
            new_alert_state = "close"
            new_alert_at    = now_iso
        else:
            new_alert_state = prior_alert_state or ""
            new_alert_at    = prior.get("last_alert_at") or ""

        state_rows.append(S.TriggerAlertRow(
            decision_key=key,
            ticker=d.ticker.upper(),
            account=d.account.lower(),
            strategy=d.strategy.upper(),
            last_state=ev.state,
            last_alert_state=new_alert_state,
            last_alert_at=new_alert_at,
            current_price=cur or 0.0,
            entry_price=d.entry,
            blocking_gates=" | ".join(ev.blocking_gates),
            updated_at=now_iso,
        ))

        if should_fire:
            fires.append((d, ev, cur or 0.0))
        elif should_soft_fire:
            soft_fires.append((d, ev, cur or 0.0))

    # Per-row visibility — was previously a silent count. Show every
    # evaluated row's state + every skipped row's reason. Makes silent
    # drops debuggable next time something fails to fire as expected.
    logger.info(f"Evaluated {len(state_rows)} watching decisions:")
    for row in state_rows:
        gate_str = f"  blocked: {row.blocking_gates}" if row.blocking_gates else ""
        pct_to_trigger = (
            (row.current_price - row.entry_price) / row.entry_price
            if row.entry_price else 0
        )
        logger.info(
            f"  • {row.ticker:6} {row.account:7} {row.strategy:10} "
            f"state={row.last_state:8} cur=${row.current_price:>7.2f} entry=${row.entry_price:>7.2f} "
            f"({pct_to_trigger:+.1%}){gate_str}"
        )
    if skipped:
        logger.info(f"Skipped {len(skipped)} unevaluable decisions:")
        for d, reason in skipped:
            logger.info(f"  · {d.ticker:6} {d.account:7} {d.strategy or '(no strat)':10}  {reason}")
    logger.info(
        f"Fires: {len(fires)} act_now transition(s)"
        + (f"; {len(soft_fires)} close-state soft fire(s)" if include_close else f"; close-state alerts disabled (set TRIGGER_ALERTS_INCLUDE_CLOSE=true to enable, would have fired {len(soft_fires)})")
    )

    # ────────────────────────────────────────────────────────────────
    # Plan macro-news lane (computed pre-dry-return so previews work):
    # 1) Blackout edge trigger — if in window and not already alerted.
    # 2) Hot-news edge trigger — top 3 not-yet-alerted hot headlines.
    # Flood caps HOT_NEWS_PING_CAP / HOT_NEWS_FRESH_MIN are module-level
    # constants (top of file) so the held-news lane can reference them.
    # ────────────────────────────────────────────────────────────────
    macro_blackout_plan: tuple[str, dict] | None = None
    if in_blackout and blackout_event:
        bo_event_time = blackout_event.get("_t_iso", "")
        bo_key = f"blackout:{(blackout_event.get('event') or 'unknown')}-{bo_event_time}"
        if bo_key not in prior_macro_alerts:
            macro_blackout_plan = (bo_key, blackout_event)

    # Recency cutoff for news — ISO timestamps from MacroFeed are UTC.
    fresh_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=HOT_NEWS_FRESH_MIN)).isoformat()

    # Gate is HOT_KEYWORDS-based only. The "so what" interpretation layer
    # was deleted — the keyword heuristic produced canned output that read
    # as headline-restated, and LLM enrichment would re-introduce API cost.
    # Reasoning lives in the daily brief now (Multi Day Swing topic, once a
    # day, Opus-quality). Macro pings are just real-time tape-mover flags:
    # headline + clickable source link.
    macro_news_plan: list[dict] = [
        n for n in macro.news
        if n.get("hot")
        and n.get("id")
        and (n.get("datetime") or "") >= fresh_cutoff
        and f"news:{n['id']}" not in prior_macro_alerts
    ][:HOT_NEWS_PING_CAP]

    # ── Macro-surprise plan — today's US releases with a real beat/miss ──
    # interpret_surprise filters to playbook events (CPI/NFP/FOMC/...) with a
    # non-trivial surprise; dedup keeps it once per release. The free, tailored
    # "so what" — no AI tokens.
    MACRO_SURPRISE_CAP = 3
    macro_surprise_plan: list[tuple[str, dict]] = []
    all_leans: list[tuple[str, str]] = []   # (label, lean) across ALL today's prints
    for ev in load_macro_prints(client):
        interp = mp.interpret_surprise(
            ev["event"], ev["actual"], ev["forecast"], ev["previous"], ev["unit"])
        if not interp:
            continue
        all_leans.append((interp["label"], interp["lean"]))
        skey = f"macro_print:{ev['date'][:10]}-{ev['event']}"
        if skey in prior_macro_alerts:
            continue
        macro_surprise_plan.append((skey, interp))
    macro_surprise_plan = macro_surprise_plan[:MACRO_SURPRISE_CAP]

    # Persist the net lean (from ALL of today's prints, not just newly-alerted) so
    # build_daily_plan can tilt sizing. Risk-off dominates a tie (defense wins).
    if all_leans and not args.dry:
        today = date.today().isoformat()
        leans = [l for _, l in all_leans]
        order = ["risk_off", "hawkish", "dovish", "risk_on"]
        net_lean = max(set(leans), key=lambda x: (leans.count(x), -order.index(x) if x in order else -9))
        summary = " · ".join(f"{lab}→{ln}" for lab, ln in all_leans[:5])
        try:
            sh.ensure_headers(client, S.MacroLeanRow.TAB_NAME, S.MacroLeanRow.HEADERS)
            ws = sh._open_sheet(client).worksheet(S.MacroLeanRow.TAB_NAME)
            existing = ws.get_all_values()
            keep = [existing[0]] if existing else [S.MacroLeanRow.HEADERS]
            keep += [r for r in (existing[1:] if existing else []) if r and r[0][:10] != today]
            keep.append(S.MacroLeanRow(date=today, net_lean=net_lean, summary=summary,
                                       updated_at=now_iso).to_row())
            sh.upsert_tab(ws, keep)
            logger.info(f"  ✓ macro_lean: {net_lean} ({summary})")
        except Exception as e:
            logger.warning(f"  ✗ macro_lean write failed: {e}")

    n_hot = sum(1 for n in macro.news if n.get("hot"))
    n_fresh = sum(1 for n in macro.news if n.get("hot") and (n.get("datetime") or "") >= fresh_cutoff)
    logger.info(
        f"Macro plan: blackout={'YES' if macro_blackout_plan else 'no'} | "
        f"news={len(macro_news_plan)} of {n_hot} hot "
        f"({n_fresh} fresh, {len(prior_macro_alerts)} already alerted) | "
        f"surprises={len(macro_surprise_plan)}"
    )

    # ── Portfolio-ticker mirror plan (B) ───────────────────────────────
    # When a hot headline mentions any held ticker, also send a copy to
    # the Multi Day Swing topic so portfolio-relevant news lands in the
    # decisions lane. The mirror is a SEPARATE Telegram message (different
    # leading line) — the original ping still goes to Macro News too.
    portfolio_tickers = load_portfolio_tickers(client)
    logger.info(f"Portfolio tickers (for mirror): {sorted(portfolio_tickers) or '(none)'}")

    def _matched_tickers(text: str) -> list[str]:
        """Return portfolio tickers mentioned in `text` (case-insensitive,
        word-boundary match so 'OPEN' doesn't match 'opens')."""
        import re as _re
        if not text or not portfolio_tickers:
            return []
        hits: list[str] = []
        upper = text.upper()
        for tk in portfolio_tickers:
            # Cheap pre-filter then word-boundary check
            if tk in upper and _re.search(rf"\b{_re.escape(tk)}\b", upper):
                hits.append(tk)
        return hits

    # ────────────────────────────────────────────────────────────────
    # Plan the three held-book lanes (spread-defense / held-news /
    # market-pressure) — added after the June 5-9 2026 incident where
    # held put credit spreads rode an SPX selloff with zero pages.
    # All three dedup through the same macro_alerts_state ledger and
    # are NOT gated by the macro blackout: the blackout exists to stop
    # ENTRY pings minutes before FOMC/CPI — these are exit-side risk
    # alerts on positions already held (same reasoning as the macro-news
    # pings above, which also bypass it).
    # ────────────────────────────────────────────────────────────────
    today_sgt = S.now_sgt_date()
    # Pressure dedups per US-SESSION day, not SGT day: the US session
    # crosses SGT midnight, and the SGT-date key re-armed WARN at
    # 00:00 SGT mid-session (2026-06-11 incident — WARN re-paged ~00:10
    # for the same selloff already paged 23:36, then the deepening tape
    # at 01:51-03:32 was silently deduped against that midnight page).
    us_session_day = S.us_market_date()
    prior_keys = set(prior_macro_alerts)

    option_legs = load_open_option_legs(client, logger)
    defense_plan = plan_defense_pings(option_legs, live_prices, prior_keys, today_sgt)

    held_news_plan = plan_held_news_pings(
        load_news_sentiment_rows(client),
        portfolio_tickers,
        prior_keys,
        held_news_fresh_cutoff(),
    )

    pressure_plan = plan_market_pressure(
        live_changes, portfolio_tickers, prior_keys, us_session_day)

    # Log line distinguishes "tape below threshold" from "in band but
    # already paged this session" — both used to print as "none", which
    # made the dedup suppression indistinguishable from a dropped WARN.
    pressure_sev_now = pressure_severity(
        live_changes.get("SPY"), live_changes.get("QQQ"))
    if pressure_plan:
        pressure_desc = pressure_plan["severity"]
    elif pressure_sev_now:
        pressure_desc = f"{pressure_sev_now}-already-paged({us_session_day})"
    else:
        pressure_desc = "none"

    n_short_legs = sum(1 for l in option_legs if _f(l.get("qty")) < 0)
    logger.info(
        f"Lane plans: defense={len(defense_plan)} (of {n_short_legs} short legs) | "
        f"held_news={len(held_news_plan)} | "
        f"pressure={pressure_desc} "
        f"(SPY {live_changes.get('SPY', '?')}% QQQ {live_changes.get('QQQ', '?')}%)"
    )

    if args.dry:
        for d, ev, cur in fires:
            logger.info(f"  [DRY] would fire ACT_NOW: {d.ticker} {d.account} entry=${d.entry:.2f} → cur=${cur:.2f}  ({ev.direction})")
        for d, ev, cur in soft_fires:
            tag = "would fire CLOSE" if include_close else "would-have-fired CLOSE (gated)"
            logger.info(f"  [DRY] {tag}: {d.ticker} {d.account} entry=${d.entry:.2f} → cur=${cur:.2f}  ({ev.pct_to_trigger:+.1%})")
        if macro_blackout_plan:
            _, ev = macro_blackout_plan
            logger.info(f"  [DRY] would fire BLACKOUT: {ev.get('event')} ({ev.get('_minutes_until')}min)")
        for n in macro_news_plan:
            logger.info(f"  [DRY] would fire NEWS: [{n.get('source','?')}] {n.get('headline','')[:80]}")
        for _, it in macro_surprise_plan:
            logger.info(f"  [DRY] would fire SURPRISE: {it['label']} {it['actual']} vs {it['forecast']} "
                        f"({it['direction']} → {it['lean']})")
        if not macro_blackout_plan and not macro_news_plan and not macro_surprise_plan:
            logger.info("  [DRY] no macro pings queued")
        for plan in defense_plan:
            logger.info(
                f"  [DRY] would fire DEFENSE {plan['level'].upper()}: {plan['ticker']} "
                f"{plan['underlying']:.2f} vs short {plan['strike']:g}{plan['right']} "
                f"({plan['label']} exp {plan['expiry']}, {plan['dte']} DTE)"
            )
        for n in held_news_plan:
            logger.info(
                f"  [DRY] would fire HELD NEWS: {n['ticker']} {n['score']:+.2f} "
                f"{n['headline'][:70]}"
            )
        if pressure_plan:
            logger.info(
                f"  [DRY] would fire PRESSURE {pressure_plan['severity']}: "
                f"SPY {pressure_plan['spy']} QQQ {pressure_plan['qqq']} "
                f"worst={pressure_plan['worst']}"
            )
        if not defense_plan and not held_news_plan and not pressure_plan:
            logger.info("  [DRY] no defense/held-news/pressure pings queued")
        return 0

    # Persist state regardless of whether any fired (so dormant→close
    # transitions still get recorded for next-run dedup logic).
    if state_rows:
        upsert_alert_state(client, state_rows, logger)

    # Send Telegrams — hard fires (ACT NOW) first, then soft fires (CLOSE).
    # Macro blackout gates ALL outbound pushes: in-window events still
    # update the trigger_alerts sheet (so the next-run dedup still works)
    # but Telegram is suppressed to avoid paging during FOMC/CPI/NFP.
    sent = 0
    deferred = 0
    for d, ev, cur in fires:
        if in_blackout and blackout_event:
            deferred += 1
            logger.warning(
                f"  ⏸ ACT_NOW deferred (macro blackout — {blackout_event['event']} "
                f"{blackout_event['_minutes_until']:+d}min): {d.ticker} {d.account}"
            )
            continue
        try:
            tg.ping_trigger_act_now(
                ticker=d.ticker.upper(),
                account=d.account.lower(),
                strategy=d.strategy.upper(),
                entry_price=d.entry,
                current_price=cur,
                direction=ev.direction,
                pwa_url=PWA_URL,
            )
            sent += 1
            logger.info(f"  ✓ sent ACT_NOW: {d.ticker} {d.account}")
        except Exception as e:
            logger.warning(f"  ✗ ACT_NOW failed: {d.ticker} {d.account}: {e}")

    soft_sent = 0
    soft_deferred = 0
    for d, ev, cur in soft_fires:
        if in_blackout and blackout_event:
            soft_deferred += 1
            logger.warning(
                f"  ⏸ CLOSE deferred (macro blackout): {d.ticker} {d.account}"
            )
            continue
        try:
            tg.ping_trigger_close(
                ticker=d.ticker.upper(),
                account=d.account.lower(),
                strategy=d.strategy.upper(),
                entry_price=d.entry,
                current_price=cur,
                direction=ev.direction,
                pct_to_trigger=ev.pct_to_trigger,
                pwa_url=PWA_URL,
            )
            soft_sent += 1
            logger.info(f"  ✓ sent CLOSE: {d.ticker} {d.account}")
        except Exception as e:
            logger.warning(f"  ✗ CLOSE failed: {d.ticker} {d.account}: {e}")

    # ────────────────────────────────────────────────────────────────
    # Execute the macro-news plan computed above (live mode only).
    # Both event types are deduped via macro_alerts_state sheet so
    # subsequent cron runs don't re-fire the same alert.
    # ────────────────────────────────────────────────────────────────
    macro_state_rows: list[S.MacroAlertStateRow] = []
    macro_pinged = 0

    if macro_blackout_plan:
        bo_key, ev = macro_blackout_plan
        try:
            tg.ping_macro_blackout(
                event_name=ev.get("event", "Unknown event"),
                minutes_until=ev.get("_minutes_until", 0),
                impact=ev.get("impact", "high"),
                pwa_url=PWA_URL,
            )
            macro_pinged += 1
            logger.info(f"  ✓ sent BLACKOUT: {ev.get('event')}")
        except Exception as e:
            logger.warning(f"  ✗ BLACKOUT failed: {e}")
        macro_state_rows.append(S.MacroAlertStateRow(
            event_key=bo_key,
            event_type="blackout",
            event_summary=ev.get("event", ""),
            event_time=ev.get("_t_iso", ""),
            alerted_at=now_iso,
            updated_at=now_iso,
        ))
    elif in_blackout and blackout_event:
        logger.info(f"  · BLACKOUT already alerted: {blackout_event.get('event')}")

    # Live regime context for the macro pings — computed once (same for all).
    regime_ctx = _regime_context(client)
    if regime_ctx:
        logger.info(f"  · regime context for pings: {regime_ctx}")

    swing_mirrored = 0
    for n in macro_news_plan:
        news_key = f"news:{n['id']}"
        # Held-ticker match BEFORE the ping so the "so what" can flag exposure.
        text_for_match = f"{n.get('headline', '')} {n.get('summary', '')}"
        matched = _matched_tickers(text_for_match)
        try:
            tg.ping_macro_news(
                headline=n.get("headline", ""),
                source=n.get("source", ""),
                url=n.get("url", ""),
                category=n.get("category", ""),
                context=regime_ctx,
                held=matched,
            )
            macro_pinged += 1
            cat_tag = f" [{n.get('category', '?')}]"
            logger.info(f"  ✓ sent NEWS{cat_tag}: {n.get('headline', '')[:60]}")
        except Exception as e:
            logger.warning(f"  ✗ NEWS failed: {e}")

        # Mirror to Multi Day Swing if the headline mentions any held ticker.
        # Done inside the same loop so dedup state covers both routes.
        if matched:
            try:
                tg.ping_macro_news_to_swing(
                    headline=n.get("headline", ""),
                    matched_tickers=matched,
                    source=n.get("source", ""),
                    url=n.get("url", ""),
                )
                swing_mirrored += 1
                logger.info(f"    ↳ mirrored to swing topic (tickers: {matched})")
            except Exception as e:
                logger.warning(f"    ↳ swing mirror failed: {e}")

        macro_state_rows.append(S.MacroAlertStateRow(
            event_key=news_key,
            event_type="hot_news",
            event_summary=n.get("headline", "")[:200],
            event_time=n.get("datetime", now_iso),
            alerted_at=now_iso,
            updated_at=now_iso,
        ))

    # Macro-surprise pings — tailored "so what" on today's US releases.
    for skey, interp in macro_surprise_plan:
        try:
            tg.ping_macro_surprise(interp)
            macro_pinged += 1
            logger.info(f"  ✓ sent SURPRISE: {interp['label']} {interp['direction']} → {interp['lean']}")
        except Exception as e:
            logger.warning(f"  ✗ SURPRISE failed: {e}")
        macro_state_rows.append(S.MacroAlertStateRow(
            event_key=skey,
            event_type="macro_surprise",
            event_summary=f"{interp['label']} {interp['actual']} vs {interp['forecast']} ({interp['direction']})"[:200],
            event_time=now_iso,
            alerted_at=now_iso,
            updated_at=now_iso,
        ))

    # ────────────────────────────────────────────────────────────────
    # Execute the three held-book lanes. Ledger rows are appended ONLY
    # after a successful send — a failed Telegram naturally retries on
    # the next run instead of being recorded as alerted.
    # ────────────────────────────────────────────────────────────────

    # ── Spread-defense lane (incident fix) ──────────────────────────
    defense_sent = 0
    for plan in defense_plan:
        try:
            tg.ping_spread_defense(
                ticker=plan["ticker"],
                right=plan["right"],
                strike=plan["strike"],
                expiry=plan["expiry"],
                dte=plan["dte"],
                underlying=plan["underlying"],
                level=plan["level"],
                label=plan["label"],
                account=plan["account"],
            )
            defense_sent += 1
            logger.info(
                f"  ✓ sent DEFENSE {plan['level'].upper()}: {plan['ticker']} "
                f"{plan['underlying']:.2f} vs short {plan['strike']:g}{plan['right']}"
            )
        except Exception as e:
            logger.warning(f"  ✗ DEFENSE failed: {plan['ticker']} {plan['strike']:g}{plan['right']}: {e}")
            continue
        for k in plan["keys_to_mark"]:
            macro_state_rows.append(S.MacroAlertStateRow(
                event_key=k,
                event_type="spread_defense",
                event_summary=(
                    f"{plan['ticker']} {plan['underlying']:.2f} vs short "
                    f"{plan['strike']:g}{plan['right']} {plan['level']} "
                    f"({plan['label']} exp {plan['expiry']})"
                )[:200],
                event_time=now_iso,
                alerted_at=now_iso,
                updated_at=now_iso,
            ))

    # ── Held-name news lane ──────────────────────────────────────────
    held_news_sent = 0
    for n in held_news_plan:
        try:
            tg.ping_held_news(
                ticker=n["ticker"],
                headline=n["headline"],
                sentiment_score=n["score"],
                sentiment_label=n["label"],
                source=n["source"],
                url=n["url"],
            )
            held_news_sent += 1
            logger.info(f"  ✓ sent HELD NEWS: {n['ticker']} {n['score']:+.2f} {n['headline'][:60]}")
        except Exception as e:
            logger.warning(f"  ✗ HELD NEWS failed: {n['ticker']}: {e}")
            continue
        macro_state_rows.append(S.MacroAlertStateRow(
            event_key=n["key"],
            event_type="held_news",
            event_summary=f"{n['ticker']} {n['score']:+.2f} {n['headline']}"[:200],
            event_time=n["datetime"] or now_iso,
            alerted_at=now_iso,
            updated_at=now_iso,
        ))

    # ── Market-pressure lane ─────────────────────────────────────────
    pressure_sent = 0
    if pressure_plan:
        try:
            tg.ping_market_pressure(
                severity=pressure_plan["severity"],
                spy_pct=pressure_plan["spy"],
                qqq_pct=pressure_plan["qqq"],
                worst_held=pressure_plan["worst"],
                posture=exposure_rec,
            )
            pressure_sent = 1
            logger.info(
                f"  ✓ sent PRESSURE {pressure_plan['severity']}: "
                f"SPY {pressure_plan['spy']} QQQ {pressure_plan['qqq']}"
            )
            for k in pressure_plan["keys_to_mark"]:
                macro_state_rows.append(S.MacroAlertStateRow(
                    event_key=k,
                    event_type="market_pressure",
                    event_summary=(
                        f"{pressure_plan['severity']} SPY {pressure_plan['spy']} "
                        f"QQQ {pressure_plan['qqq']} worst {pressure_plan['worst']}"
                    )[:200],
                    event_time=now_iso,
                    alerted_at=now_iso,
                    updated_at=now_iso,
                ))
        except Exception as e:
            logger.warning(f"  ✗ PRESSURE failed: {e}")

    if macro_state_rows:
        upsert_macro_alert_state(client, macro_state_rows, logger)

    total_deferred = deferred + soft_deferred
    logger.info(
        f"trigger_alerts done — sent {sent}/{len(fires)} act_now"
        + (f", {soft_sent}/{len(soft_fires)} close" if include_close else "")
        + (f", {macro_pinged} macro" if macro_pinged else "")
        + (f", {swing_mirrored} swing-mirror" if swing_mirrored else "")
        + (f", {defense_sent} defense" if defense_sent else "")
        + (f", {held_news_sent} held-news" if held_news_sent else "")
        + (f", {pressure_sent} pressure" if pressure_sent else "")
        + (f"; {total_deferred} deferred by macro blackout" if total_deferred else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
