"""
options_defense.py — Daily defense brief for each open option position.

Purpose: answer "what do I need to DO today" for every open CSP/CC. This runs
every morning and compares today's metrics against yesterday's to highlight
*changes* — confidence spikes, environment flips, catalyst fires, profit
targets hit, stops approaching.

The output is a list of alerts with severity (CRITICAL/HIGH/MEDIUM/INFO), a
specific action recommendation, and supporting evidence. Pushed to the
`options_defense` sheet tab and surfaced at the top of the Options page.

Separation of concerns:
  - wheel_continuation = what's next when this expires (weeks out)
  - option_scanner = fresh idea generation (new candidates)
  - option_recommendations = weekly analyst notes (strategy-level context)
  - options_defense = TODAY'S action items for open positions (THIS FILE)
"""
from __future__ import annotations

from typing import Any


# Severity levels
CRITICAL = "CRITICAL"  # act today / within hours
HIGH = "HIGH"          # act this trading day
MEDIUM = "MEDIUM"      # review today, act this week
INFO = "INFO"          # monitor


def _severity_order(level: str) -> int:
    return {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3}.get(level, 4)


def compute_defense_alerts(
    today_option: dict[str, Any],
    yesterday_option: dict[str, Any] | None,
    today_indicator: dict[str, Any],
    yesterday_indicator: dict[str, Any] | None,
    exit_plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Generate defense alerts for a single open option.

    Args:
        today_option: Today's OptionRow-shaped dict with confidence_pct,
                      moneyness, dte, wheel_leg, right, strike, etc.
        yesterday_option: Yesterday's same dict (or None if no history)
        today_indicator: Today's indicator bundle incl tech scores + catalyst
        yesterday_indicator: Yesterday's indicators (or None)
        exit_plan: Exit plan dict with status, profit_capture_pct, etc.

    Returns list of alert dicts:
        {severity, title, description, action, delta_info}
    """
    alerts: list[dict[str, Any]] = []

    def _safe_int(v, default=0):
        try:
            return int(float(v)) if v not in (None, "") else default
        except (ValueError, TypeError):
            return default

    def _safe_float(v, default=0.0):
        try:
            return float(v) if v not in (None, "") else default
        except (ValueError, TypeError):
            return default

    ticker = today_option.get("ticker", "")
    right = today_option.get("right", "")
    strike = _safe_float(today_option.get("strike", 0))
    qty = _safe_float(today_option.get("qty", 0))
    dte = _safe_int(today_option.get("dte", 0))
    moneyness = today_option.get("moneyness", "?")
    confidence = _safe_int(today_option.get("confidence_pct", 0))
    wheel_leg = today_option.get("wheel_leg", "")
    catalyst = bool(today_option.get("catalyst_flag", False))

    today_pos = f"{ticker} ${strike:.2f}{right}"
    is_short = qty < 0

    # ========= 1. Confidence spike (day-over-day) =========
    if yesterday_option:
        yest_conf = _safe_int(yesterday_option.get("confidence_pct", 0))
        conf_delta = confidence - yest_conf

        if conf_delta >= 20:
            alerts.append({
                "severity": CRITICAL,
                "title": f"{today_pos}: confidence spike",
                "description": f"Assignment confidence jumped from {yest_conf}% to {confidence}% today (+{conf_delta}%)",
                "action": "Review position immediately — consider closing or rolling out",
                "delta_info": f"Δ+{conf_delta}% confidence",
            })
        elif conf_delta >= 10:
            alerts.append({
                "severity": HIGH,
                "title": f"{today_pos}: confidence rising",
                "description": f"Confidence {yest_conf}% → {confidence}% (+{conf_delta}%)",
                "action": "Monitor closely. If trend continues, consider defensive close.",
                "delta_info": f"Δ+{conf_delta}% confidence",
            })
        elif conf_delta <= -15:
            alerts.append({
                "severity": INFO,
                "title": f"{today_pos}: confidence improving",
                "description": f"Confidence dropped {yest_conf}% → {confidence}% ({conf_delta}%)",
                "action": "Position getting safer. Continue holding.",
                "delta_info": f"Δ{conf_delta}% confidence",
            })

    # ========= 2. Moneyness flip =========
    if yesterday_option:
        yest_moneyness = yesterday_option.get("moneyness", "?")
        if yest_moneyness != moneyness and is_short:
            # OTM → ATM or ATM → ITM is bad for shorts
            bad_flip = (yest_moneyness == "OTM" and moneyness in ("ATM", "ITM")) or \
                       (yest_moneyness == "ATM" and moneyness == "ITM")
            good_flip = (yest_moneyness == "ITM" and moneyness in ("ATM", "OTM")) or \
                        (yest_moneyness == "ATM" and moneyness == "OTM")
            if bad_flip:
                alerts.append({
                    "severity": CRITICAL if moneyness == "ITM" else HIGH,
                    "title": f"{today_pos}: moneyness worsened",
                    "description": f"Flipped {yest_moneyness} → {moneyness} overnight",
                    "action": "ITM short = assignment risk. Roll out or accept assignment.",
                    "delta_info": f"{yest_moneyness}→{moneyness}",
                })
            elif good_flip:
                alerts.append({
                    "severity": INFO,
                    "title": f"{today_pos}: moneyness improved",
                    "description": f"Flipped {yest_moneyness} → {moneyness}",
                    "action": "Premium should decay favorably. Hold.",
                    "delta_info": f"{yest_moneyness}→{moneyness}",
                })

    # ========= 3. Tech score environment flip =========
    # Relevant strategy for short options
    strat_key = "score_csp" if wheel_leg == "CSP" else "score_cc" if wheel_leg == "CC" else ""
    if strat_key and yesterday_indicator:
        # Today is from computed scores dict (keyed by "CSP"/"CC"); yesterday is from sheet row (keyed "score_csp"/"score_cc")
        today_score = _safe_float(today_indicator.get("CSP" if wheel_leg == "CSP" else "CC", 0))
        yest_score = _safe_float(yesterday_indicator.get(strat_key, 0))

        score_delta = today_score - yest_score
        if today_score < -20 and score_delta < -15:
            alerts.append({
                "severity": HIGH,
                "title": f"{today_pos}: environment turned hostile",
                "description": f"{wheel_leg} tech score {yest_score:+.0f} → {today_score:+.0f} ({score_delta:+.0f})",
                "action": f"Environment no longer favors {wheel_leg}. Consider closing for whatever premium is captured.",
                "delta_info": f"Δ{score_delta:+.0f} {wheel_leg} score",
            })
        elif today_score < -30:
            alerts.append({
                "severity": MEDIUM,
                "title": f"{today_pos}: environment hostile",
                "description": f"{wheel_leg} tech score {today_score:+.0f} — environment doesn't support this trade",
                "action": "Assignment risk elevated even if BS says low. Watch catalyst/momentum.",
                "delta_info": f"{wheel_leg} score {today_score:+.0f}",
            })

    # ========= 4. Catalyst newly detected =========
    if catalyst:
        yest_catalyst = bool(yesterday_option.get("catalyst_flag", False)) if yesterday_option else False
        earnings_days = _safe_int(today_indicator.get("earnings_days_away", -1), default=-1)
        earnings_in_dte = 0 <= earnings_days <= dte

        if not yest_catalyst:
            # Newly fired
            desc = "Volatility regime elevated"
            if earnings_in_dte:
                desc = f"Earnings in {earnings_days}d (inside {dte}d DTE)"
            alerts.append({
                "severity": HIGH if earnings_in_dte else MEDIUM,
                "title": f"{today_pos}: catalyst fired",
                "description": desc,
                "action": "Assess whether to close before event. Binary risk = hard to price.",
                "delta_info": "new catalyst",
            })
        elif earnings_in_dte and earnings_days <= 7:
            alerts.append({
                "severity": HIGH,
                "title": f"{today_pos}: earnings in {earnings_days}d",
                "description": f"Earnings imminent, inside option DTE",
                "action": "Close before earnings (recommended) or accept binary risk.",
                "delta_info": f"earnings {earnings_days}d",
            })

    # ========= 5. Profit target crossed =========
    if exit_plan:
        capture = _safe_float(exit_plan.get("profit_capture_pct", 0))
        yest_capture = 0.0
        if yesterday_option:
            credit = _safe_float(today_option.get("credit", 0))
            yest_last = _safe_float(yesterday_option.get("last", 0))
            if credit > 0 and yest_last > 0:
                yest_capture = (credit - yest_last) / credit * 100

        if capture >= 50 and yest_capture < 50:
            alerts.append({
                "severity": HIGH,
                "title": f"{today_pos}: 50% profit captured",
                "description": f"{capture:.0f}% of credit captured",
                "action": "CLOSE — free up capital for next trade. Standard theta-gang exit.",
                "delta_info": f"+{capture:.0f}% captured",
            })
        elif capture >= 75:
            alerts.append({
                "severity": CRITICAL,
                "title": f"{today_pos}: 75%+ captured",
                "description": f"{capture:.0f}% captured — diminishing returns on remaining premium",
                "action": "CLOSE immediately. Risk/reward no longer favorable.",
                "delta_info": f"+{capture:.0f}% captured",
            })

    # ========= 6. Loss limit (2× credit received) =========
    if is_short:
        credit = _safe_float(today_option.get("credit", 0))
        current_last = _safe_float(today_option.get("last", 0))
        if credit > 0 and current_last >= credit * 2:
            alerts.append({
                "severity": CRITICAL,
                "title": f"{today_pos}: loss limit breached",
                "description": f"Option price ${current_last:.2f} ≥ 2× credit ${credit:.2f} — mechanical stop",
                "action": "CLOSE NOW — loss exceeds 2× credit received. Tastytrade mechanical exit.",
                "delta_info": f"2× credit stop",
            })
        elif credit > 0 and current_last >= credit * 1.5:
            alerts.append({
                "severity": HIGH,
                "title": f"{today_pos}: approaching loss limit",
                "description": f"Option price ${current_last:.2f} is 1.5× credit ${credit:.2f}",
                "action": "Monitor closely. 2× credit mechanical stop at ${:.2f}.".format(credit * 2),
                "delta_info": f"1.5× credit",
            })

    # ========= 7. 21 DTE management rule (Tastytrade) =========
    if is_short and dte <= 21 and dte > 7:
        # Check if profitable — if so, close; if not, roll
        credit = _safe_float(today_option.get("credit", 0))
        current_last = _safe_float(today_option.get("last", 0))
        capture_pct = ((credit - current_last) / credit * 100) if credit > 0 else 0

        if capture_pct >= 50:
            alerts.append({
                "severity": HIGH,
                "title": f"{today_pos}: 21 DTE + profitable",
                "description": f"{dte} DTE, {capture_pct:.0f}% profit captured — close per Tastytrade 21 DTE rule",
                "action": "CLOSE — 50%+ captured at 21 DTE. Redeploy capital to next cycle.",
                "delta_info": f"{dte}d DTE, {capture_pct:.0f}% captured",
            })
        elif capture_pct >= 0:
            alerts.append({
                "severity": MEDIUM,
                "title": f"{today_pos}: 21 DTE management window",
                "description": f"{dte} DTE, {capture_pct:.0f}% captured — entering management zone",
                "action": "OTM: consider closing to free capital. ATM/ITM: roll out to next cycle.",
                "delta_info": f"{dte}d DTE, {capture_pct:.0f}% captured",
            })
        else:
            # Underwater at 21 DTE
            alerts.append({
                "severity": HIGH,
                "title": f"{today_pos}: 21 DTE underwater",
                "description": f"{dte} DTE, underwater ({capture_pct:.0f}%). Roll or close to limit loss.",
                "action": f"ROLL {'out-and-down' if wheel_leg == 'CSP' else 'out-and-up' if wheel_leg == 'CC' else 'out'} to next cycle. Do not hold through expiry underwater.",
                "delta_info": f"{dte}d DTE, {capture_pct:.0f}%",
            })

    # ========= 8. DTE milestones (7d, 3d, 1d) =========
    if is_short:
        if dte == 7:
            alerts.append({
                "severity": MEDIUM,
                "title": f"{today_pos}: 7 DTE",
                "description": "Entering final week",
                "action": "If ITM, prepare to roll. If OTM, let theta decay work.",
                "delta_info": "7d DTE",
            })
        elif dte == 3:
            alerts.append({
                "severity": HIGH if moneyness != "OTM" else MEDIUM,
                "title": f"{today_pos}: 3 DTE",
                "description": "3 days to expiry",
                "action": "ITM: roll NOW. ATM: decide today. OTM: monitor, let expire.",
                "delta_info": "3d DTE",
            })
        elif dte <= 1:
            alerts.append({
                "severity": CRITICAL if moneyness != "OTM" else HIGH,
                "title": f"{today_pos}: expires today/tomorrow",
                "description": f"{dte}d to expiry",
                "action": "OTM: let expire. ITM/ATM: act now to close or roll.",
                "delta_info": f"{dte}d DTE",
            })

    # ========= 9. Stop conditions on underlying =========
    if exit_plan:
        exit_status = exit_plan.get("status", "")
        if exit_status == "STOP_TRIGGERED":
            alerts.append({
                "severity": HIGH,
                "title": f"{today_pos}: underlying stop triggered",
                "description": f"Underlying {ticker} stock stop was triggered",
                "action": "If holding shares (CC), reconsider the CC. May want to close option + stock together.",
                "delta_info": "stock stop triggered",
            })

    # ========= 10. Confidence already high (persistent) =========
    if confidence >= 60 and (not yesterday_option or _safe_int(yesterday_option.get("confidence_pct", 0)) >= 60):
        # Only surface if not already covered by spike
        if not any(a["title"].startswith(f"{today_pos}: confidence") for a in alerts):
            alerts.append({
                "severity": HIGH,
                "title": f"{today_pos}: persistent high confidence",
                "description": f"Confidence {confidence}% for 2+ days",
                "action": "Breach risk material. Consider closing for current P&L rather than waiting.",
                "delta_info": f"{confidence}% conf",
            })

    # ========= 11. VIX Regime alert (market-wide IV context) =========
    vix_val = _safe_float(today_indicator.get("_vix", 0))
    if is_short and vix_val > 0:
        if vix_val >= 35:
            alerts.append({
                "severity": CRITICAL,
                "title": f"{today_pos}: VIX crisis regime ({vix_val:.1f})",
                "description": (
                    f"VIX at {vix_val:.1f} — crisis level. Market-wide IV elevated, "
                    f"all short premium at heightened risk."
                ),
                "action": "CLOSE all short premium or tighten to breakeven stops. Buy protection (puts).",
                "delta_info": f"VIX {vix_val:.1f} crisis",
            })
        elif vix_val >= 25:
            alerts.append({
                "severity": HIGH,
                "title": f"{today_pos}: VIX elevated ({vix_val:.1f})",
                "description": (
                    f"VIX at {vix_val:.1f} — elevated regime. Short premium risk increased."
                ),
                "action": "Review all positions. Close marginal trades; hold only high-conviction + profitable.",
                "delta_info": f"VIX {vix_val:.1f} elevated",
            })

    return alerts


MAX_ALERTS_PER_POSITION = 4  # 11 alert types now (added VIX regime)


def build_defense_brief(
    today_options: list[dict[str, Any]],
    yesterday_options_by_key: dict[str, dict[str, Any]],  # keyed by "account|ticker|right|strike"
    today_indicators: dict[str, dict],                    # keyed by ticker
    yesterday_indicators_by_ticker: dict[str, dict],
    exit_plans_by_key: dict[str, dict],                   # keyed by "account|ticker"
    vix: float = 0.0,
) -> list[dict[str, Any]]:
    """
    Build the complete defense brief across all open options. Returns a flat
    list of alerts sorted by severity, consolidated to avoid alert fatigue.

    Per-position consolidation: keep the top N alerts by severity for each
    position. If more exist, the Nth alert's description notes how many
    additional alerts were suppressed so nothing is silently lost.
    """
    all_alerts: list[dict[str, Any]] = []

    for opt in today_options:
        account = opt.get("account", "")
        ticker = opt.get("ticker", "")
        right = opt.get("right", "")
        strike = float(opt.get("strike", 0))
        key = f"{account}|{ticker}|{right}|{strike:.2f}"

        yest_opt = yesterday_options_by_key.get(key)
        today_ind = dict(today_indicators.get(ticker, {}))
        today_ind["_vix"] = vix  # inject VIX for regime alert
        yest_ind = yesterday_indicators_by_ticker.get(ticker)
        exit_plan = exit_plans_by_key.get(f"{account}|{ticker}")

        alerts = compute_defense_alerts(
            opt, yest_opt, today_ind, yest_ind, exit_plan,
        )
        for a in alerts:
            a["account"] = account
            a["ticker"] = ticker
            a["strike"] = strike
            a["right"] = right

        alerts.sort(key=lambda a: _severity_order(a["severity"]))

        if len(alerts) > MAX_ALERTS_PER_POSITION:
            suppressed = len(alerts) - MAX_ALERTS_PER_POSITION
            kept = alerts[:MAX_ALERTS_PER_POSITION]
            kept[-1]["description"] += f" (+{suppressed} more alert{'s' if suppressed > 1 else ''})"
            alerts = kept

        all_alerts.extend(alerts)

    all_alerts.sort(key=lambda a: _severity_order(a["severity"]))
    return all_alerts
