"""
trigger_alerts.py — every-N-min poll that fires Telegram pushes when a
WATCHING decision transitions into ACT_NOW.

Mirrors the client-side `evaluateTrigger()` in `pwa/src/data.ts` so a
user who only opens the app once a day still gets paged at the moment
the brain's level + all its gates clear simultaneously.

Inputs (all read from Sheets):
  - decision_queue   → all WATCHING rows
  - live_prices      → ticker → current price (5-min cron)
  - exposure_posture → for "exposure:NEW_ENTRY_ALLOWED" gate
  - tv_signals       → for "tv_daily:BUY", "tv_weekly:BUY" gates

Output:
  - trigger_alerts sheet (per-decision state ledger)
  - Telegram push when state transitions DORMANT/CLOSE/READY → ACT_NOW
    (same row staying ACT_NOW across runs is suppressed)

Schedule: every 10 min during US market hours (13:30-21:00 UTC, Mon-Fri)
plus pre/post market if extended. See .github/workflows/trigger-alerts.yml.

Manual run:
  python scripts/trigger_alerts.py        # write + send
  python scripts/trigger_alerts.py --dry  # print, no sheet write, no telegram
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("trigger-alerts")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


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


def load_live_prices(client) -> dict[str, float]:
    """ticker (uppercase) → last_price."""
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.LivePriceRow.TAB_NAME)
    except Exception:
        return {}
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {}
    hdr = rows[0]
    try:
        c_t = hdr.index("ticker")
        c_l = hdr.index("last")
    except ValueError:
        return {}
    out: dict[str, float] = {}
    for r in rows[1:]:
        if len(r) <= max(c_t, c_l):
            continue
        try:
            out[r[c_t].upper()] = float(r[c_l] or 0)
        except (TypeError, ValueError):
            continue
    return out


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

    ws.clear()
    ws.update(values=keep, range_name="A1", value_input_option="USER_ENTERED")
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

    ws.clear()
    ws.update(values=keep, range_name="A1", value_input_option="USER_ENTERED")
    logger.info(f"✓ trigger_alerts upserted: {len(rows)}")
    return len(rows)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry", action="store_true", help="Print plan, no sheet write, no Telegram")
    p.add_argument("--force-resend", action="store_true",
                   help="Send Telegram even if last_alert_state was already act_now (debugging)")
    args = p.parse_args()

    logger = _setup_logging()
    logger.info(f"trigger_alerts start (dry={args.dry}, force_resend={args.force_resend})")

    load_env()
    client = sh.authenticate()

    decisions = load_decisions(client, logger)
    if not decisions:
        logger.info("No watching decisions — nothing to do")
        return 0

    live_prices  = load_live_prices(client)
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
    # ────────────────────────────────────────────────────────────────
    # Caps protecting against floods:
    #   - HOT_NEWS_PING_CAP    : max pings per cron run
    #   - HOT_NEWS_FRESH_MIN   : recency window — only ping news younger
    #     than this. The Finnhub cache holds 24h of news but alerting on
    #     hour-old headlines is just spam. 60min keeps pings actionable.
    HOT_NEWS_PING_CAP = 3
    HOT_NEWS_FRESH_MIN = 60

    macro_blackout_plan: tuple[str, dict] | None = None
    if in_blackout and blackout_event:
        bo_event_time = blackout_event.get("_t_iso", "")
        bo_key = f"blackout:{(blackout_event.get('event') or 'unknown')}-{bo_event_time}"
        if bo_key not in prior_macro_alerts:
            macro_blackout_plan = (bo_key, blackout_event)

    # Recency cutoff for news — ISO timestamps from MacroFeed are UTC.
    from datetime import datetime, timedelta, timezone as _tz
    fresh_cutoff = (datetime.now(_tz.utc) - timedelta(minutes=HOT_NEWS_FRESH_MIN)).isoformat()

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
    for ev in load_macro_prints(client):
        interp = mp.interpret_surprise(
            ev["event"], ev["actual"], ev["forecast"], ev["previous"], ev["unit"])
        if not interp:
            continue
        skey = f"macro_print:{ev['date'][:10]}-{ev['event']}"
        if skey in prior_macro_alerts:
            continue
        macro_surprise_plan.append((skey, interp))
    macro_surprise_plan = macro_surprise_plan[:MACRO_SURPRISE_CAP]

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

    if macro_state_rows:
        upsert_macro_alert_state(client, macro_state_rows, logger)

    total_deferred = deferred + soft_deferred
    logger.info(
        f"trigger_alerts done — sent {sent}/{len(fires)} act_now"
        + (f", {soft_sent}/{len(soft_fires)} close" if include_close else "")
        + (f", {macro_pinged} macro" if macro_pinged else "")
        + (f", {swing_mirrored} swing-mirror" if swing_mirrored else "")
        + (f"; {total_deferred} deferred by macro blackout" if total_deferred else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
