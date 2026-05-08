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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sync import load_env       # noqa: E402
from src import sheets as sh        # noqa: E402
from src import schema as S         # noqa: E402
from src import telegram as tg      # noqa: E402
from src.macro_blackouts import MacroFeed  # noqa: E402

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

    if args.dry:
        for d, ev, cur in fires:
            logger.info(f"  [DRY] would fire ACT_NOW: {d.ticker} {d.account} entry=${d.entry:.2f} → cur=${cur:.2f}  ({ev.direction})")
        for d, ev, cur in soft_fires:
            tag = "would fire CLOSE" if include_close else "would-have-fired CLOSE (gated)"
            logger.info(f"  [DRY] {tag}: {d.ticker} {d.account} entry=${d.entry:.2f} → cur=${cur:.2f}  ({ev.pct_to_trigger:+.1%})")
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

    total_deferred = deferred + soft_deferred
    logger.info(
        f"trigger_alerts done — sent {sent}/{len(fires)} act_now"
        + (f", {soft_sent}/{len(soft_fires)} close" if include_close else "")
        + (f"; {total_deferred} deferred by macro blackout" if total_deferred else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
