"""
exit_plan.py — For each open stock/option position, compute an exit plan daily.

Per the rule: "Every entry must have an exit strategy unless it's a blue chip."

Blue chip classification:
  - Blue chip = monitor only, no hard time stop, wide % stop below 200 SMA
  - Income/ETF = monitor only, stop at -20% or below 200 SMA
  - Speculative = tight stops, time stop 45d, ATR-based
  - Commodity ETF = monitor, wide stop

Exit plan for STOCK:
  - Stop loss: max of (entry × (1 - max_drawdown), support, entry − 2×ATR)
  - Target 1: nearest Fib resistance above entry
  - Target 2: 1.382 Fib extension or +2×ATR above T1
  - Time stop: days since entry (only enforced for speculative)
  - Status: HEALTHY / WARNING (near stop) / STOP_TRIGGERED / T1_HIT / T2_HIT

Exit plan for OPTION (short CSP/CC):
  - CLOSE at 50% profit captured (theta-gang standard)
  - ROLL if ITM within 7d (avoid assignment unless you want it)
  - LET EXPIRE if OTM within 2d
  - CLOSE if breach detected (confidence spike, catalyst fires)
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional


# ---------- Ticker classification ----------

BLUE_CHIPS = {
    "AAPL", "MSFT", "NVDA", "META", "GOOG", "GOOGL", "AMZN",
    "V", "MA", "UNH", "JNJ", "PG", "KO", "PEP", "WMT", "HD",
    "JPM", "BAC", "XOM", "CVX", "TMO", "MRK", "PFE", "LLY",
    "BRK.B", "BRK.A", "AVGO", "ORCL", "CSCO", "NFLX", "DIS",
    "PM", "MO", "CRM", "IBM", "ACN",
}

BROAD_ETFS = {
    "SPY", "QQQ", "VOO", "VTI", "IVV", "VEA", "IEFA", "IWM",
    "VT", "ACWI", "SCHD", "VYM", "SPLG", "DIA",
}

COMMODITY_ETFS = {
    "GLDM", "SLV", "IAU", "GLD", "USO", "SIL", "URA", "TLT",
    "IEF", "LQD", "HYG",
}

LEVERAGED_ETFS = {
    "TQQQ", "UPRO", "SSO", "SOXL", "SPXL", "UDOW",
}


def classify_ticker(ticker: str) -> str:
    """Return one of: 'blue_chip' | 'etf_broad' | 'etf_commodity' | 'etf_leveraged' | 'speculative'."""
    t = ticker.upper()
    if t in BLUE_CHIPS:
        return "blue_chip"
    if t in BROAD_ETFS:
        return "etf_broad"
    if t in COMMODITY_ETFS:
        return "etf_commodity"
    if t in LEVERAGED_ETFS:
        return "etf_leveraged"
    return "speculative"


# ---------- Stop-loss and target rules per category ----------

CATEGORY_RULES: dict[str, dict[str, Any]] = {
    "blue_chip": {
        "max_drawdown": 0.30,            # hard stop at -30% from entry
        "atr_stop_mult": 0,              # no ATR stop (noise for blue chips)
        "time_stop_days": None,          # no time stop
        "sma_warning": "sma_200",        # SMA break = WARNING signal, not hard stop
        "profit_trim_at_t1": False,      # let winners run
        "description": "Long-term hold; hard stop at -30%, monitor 200 SMA break as warning",
    },
    "etf_broad": {
        "max_drawdown": 0.20,
        "atr_stop_mult": 0,
        "time_stop_days": None,
        "sma_warning": "sma_200",
        "profit_trim_at_t1": False,
        "description": "Core portfolio; DCA strategy",
    },
    "etf_commodity": {
        "max_drawdown": 0.25,
        "atr_stop_mult": 0,
        "time_stop_days": None,
        "sma_warning": "sma_200",
        "profit_trim_at_t1": False,
        "description": "Hedge / inflation play",
    },
    "etf_leveraged": {
        "max_drawdown": 0.20,            # 3x leveraged ETFs decay; tighter
        "atr_stop_mult": 2.5,
        "time_stop_days": 90,
        "sma_warning": "sma_50",
        "profit_trim_at_t1": True,       # take profits aggressively
        "description": "Tactical leveraged — trim on strength",
    },
    "speculative": {
        "max_drawdown": 0.15,            # hard -15% stop
        "atr_stop_mult": 3.0,            # 3x ATR Chandelier exit (Le Beau: PF 1.61 at 3×, beats 2×)
        "time_stop_days": 45,            # reassess if stagnant 45d
        "sma_warning": "sma_50",
        "profit_trim_at_t1": True,       # trim at resistance
        "description": "Speculative — tight stop, active management",
    },
}


# ---------- Compute exit plan ----------

def compute_stock_exit_plan(
    ticker: str,
    entry_price: float,
    current_price: float,
    qty: float,
    indicators: dict[str, Any],
    days_held: Optional[int] = None,
) -> dict[str, Any]:
    """Compute exit plan for a stock position."""
    category = classify_ticker(ticker)
    rules = CATEGORY_RULES[category]

    atr = float(indicators.get("atr_14", 0))
    support = float(indicators.get("support", 0))
    resistance = float(indicators.get("resistance", 0))
    fib_0764 = float(indicators.get("fib_0764", 0))
    fib_0618 = float(indicators.get("fib_0618", 0))
    fib_0382 = float(indicators.get("fib_0382", 0))
    sma_200 = float(indicators.get("sma_200", 0))
    sma_50 = float(indicators.get("sma_50", 0))
    swing_high = float(indicators.get("swing_high", 0))
    upl_pct = (current_price - entry_price) / entry_price if entry_price > 0 else 0

    # Stop loss candidates — we want the highest (tightest) floor below current price
    stop_candidates = []
    # Percentage drawdown (primary hard stop)
    pct_stop = entry_price * (1 - rules["max_drawdown"])
    stop_candidates.append(("pct", pct_stop))
    # Support (only if current price is meaningfully above support)
    if support > 0 and support < current_price * 0.98:
        stop_candidates.append(("support", support * 0.98))
    # Fib 0.764 (deepest retracement — only if above pct_stop)
    if fib_0764 > pct_stop and fib_0764 < current_price * 0.98:
        stop_candidates.append(("fib_0.764", fib_0764))
    # ATR-based trailing stop (uses CURRENT price, not entry — acts as a real trailing stop)
    if rules["atr_stop_mult"] > 0 and atr > 0:
        atr_stop = current_price - rules["atr_stop_mult"] * atr
        if atr_stop > pct_stop * 0.9:  # don't use ATR if weaker than % floor
            stop_candidates.append(("atr_trailing", atr_stop))

    # Pick the highest (tightest) valid stop, but must be BELOW current price
    valid_stops = [(k, v) for k, v in stop_candidates if 0 < v < current_price]
    if valid_stops:
        stop_key, stop_loss = max(valid_stops, key=lambda x: x[1])
    else:
        # Position already below all normal stops — use percentage as reference
        stop_key, stop_loss = "pct", pct_stop

    # SMA break warning (NOT a hard stop — just a signal)
    sma_key = rules.get("sma_warning", "")
    sma_warning_triggered = False
    sma_level = 0.0
    if sma_key == "sma_200" and sma_200 > 0:
        sma_level = sma_200
        sma_warning_triggered = current_price < sma_200
    elif sma_key == "sma_50" and sma_50 > 0:
        sma_level = sma_50
        sma_warning_triggered = current_price < sma_50

    # Profit targets
    # T1 = nearest Fib resistance above entry
    t1_candidates = []
    for fib in (fib_0382, fib_0618, resistance):
        if fib > entry_price and fib > current_price * 0.98:
            t1_candidates.append(fib)
    target_1 = min(t1_candidates) if t1_candidates else entry_price * 1.10

    # T2 = 1.382 Fib extension above swing high, OR T1 + 2×ATR
    if swing_high > 0:
        rng = swing_high - min(support, entry_price * 0.8)
        fib_ext_1382 = swing_high + rng * 0.382
    else:
        fib_ext_1382 = 0
    t2_candidates = [target_1 + 2 * atr if atr > 0 else target_1 * 1.05]
    if fib_ext_1382 > target_1:
        t2_candidates.append(fib_ext_1382)
    target_2 = max(t2_candidates)

    # Status determination
    status = "HEALTHY"
    recommendation = ""
    reasoning_parts = []

    # Special case: position already deeply below pct stop (bag / wheel candidate)
    already_bagged = upl_pct <= -rules["max_drawdown"]

    if already_bagged:
        status = "BAG"
        recommendation = (
            f"BAG — {upl_pct * 100:+.1f}% from entry. "
            f"If not wheeling, exit. If wheeling, manage via CC at breakeven+."
        )
        reasoning_parts.append(f"Already past -{rules['max_drawdown'] * 100:.0f}% hard stop")
    elif current_price <= stop_loss:
        status = "STOP_TRIGGERED"
        recommendation = f"EXIT — price ${current_price:.2f} breached ${stop_loss:.2f} stop ({stop_key})"
        reasoning_parts.append(f"Stop triggered at {stop_key}")
    elif current_price < stop_loss * 1.03:
        status = "WARNING"
        distance = (current_price - stop_loss) / current_price * 100
        recommendation = f"WARNING — {distance:.1f}% from stop at ${stop_loss:.2f}"
        reasoning_parts.append(f"Near stop ({stop_key})")
    elif current_price >= target_2:
        status = "T2_HIT"
        recommendation = f"TRIM / TRAIL — T2 ${target_2:.2f} reached ({upl_pct * 100:+.1f}%)"
        reasoning_parts.append("T2 hit — take profits or trail stop to T1")
    elif current_price >= target_1:
        status = "T1_HIT"
        if rules["profit_trim_at_t1"]:
            recommendation = f"TRIM 1/3, raise stop to breakeven — T1 ${target_1:.2f} reached"
            reasoning_parts.append("T1 hit — trim partial, protect profits")
        else:
            recommendation = f"T1 ${target_1:.2f} reached — let winner run (blue chip)"
            reasoning_parts.append("T1 hit — continue holding")
    else:
        recommendation = f"HOLD — stop ${stop_loss:.2f} / T1 ${target_1:.2f}"

    # SMA warning — add as secondary note, not primary status
    if sma_warning_triggered and status not in ("BAG", "STOP_TRIGGERED"):
        reasoning_parts.append(f"below {sma_key.upper().replace('_', ' ')} (${sma_level:.2f})")
        if status == "HEALTHY":
            status = "WARNING"
            recommendation = f"HOLD WITH CAUTION — below {sma_key.upper().replace('_', ' ')}; stop ${stop_loss:.2f} / T1 ${target_1:.2f}"

    # Time stop check
    time_stop_days = rules["time_stop_days"]
    if time_stop_days and days_held and days_held >= time_stop_days:
        if upl_pct < 0.05:  # less than 5% gain in that time
            if status == "HEALTHY":
                status = "TIME_STOP"
                recommendation = f"REASSESS — {days_held}d held, only {upl_pct * 100:+.1f}% gain. Reassess thesis."
                reasoning_parts.append(f"Time stop triggered ({days_held}d)")

    # Catalyst awareness
    if indicators.get("catalyst_flag"):
        reasoning_parts.append("catalyst active — elevated risk")

    return {
        "ticker": ticker,
        "category": category,
        "is_blue_chip": category in ("blue_chip", "etf_broad", "etf_commodity"),
        "entry": entry_price,
        "current": current_price,
        "upl_pct": upl_pct,
        "stop_loss": stop_loss,
        "stop_key": stop_key,
        "target_1": target_1,
        "target_2": target_2,
        "time_stop_days": time_stop_days or 0,
        "days_held": days_held or 0,
        "status": status,
        "recommendation": recommendation,
        "reasoning": " · ".join(reasoning_parts) if reasoning_parts else rules["description"],
    }


# Deep-loser guard (Tranche 3 / F1): there is no roll counter in the system, so
# instead of "after N rolls accept assignment" we gate on the LOSS itself. A
# short option whose buyback cost has reached 2× the credit received (profit
# capture = -1.0, i.e. down 1× credit) is a position rolling can't fix — it just
# defers the loss and ties up capital. Standard premium-selling stop.
ROLL_GIVEUP_PROFIT_CAPTURE = -1.0


def compute_option_exit_plan(
    option: dict[str, Any],
    indicators: dict[str, Any],
) -> dict[str, Any]:
    """
    Compute exit plan for a short option position (CSP/CC).

    Standard theta-gang rules:
      - Close at 50% profit captured
      - Roll out if ITM within 7 DTE
      - Let expire if OTM with <3 DTE
      - Close if confidence breaches or catalyst hits
    """
    credit = float(option.get("credit", 0))       # per share
    current_price = float(option.get("last", 0))  # current option price per share
    dte = int(option.get("dte", 0))
    moneyness = option.get("moneyness", "?")
    confidence = int(option.get("confidence_pct", 0))
    ticker = option.get("ticker", "")

    # Live-underlying intrinsic floor (Tranche 3 / F2). The option `last` is from
    # the morning grab and can be hours/a day stale; the underlying is refreshed
    # live. A SHORT option's buyback cost can NEVER be below its intrinsic value,
    # so floor current_price at intrinsic from the LIVE underlying. This catches
    # exactly the case the stale mark hides — the underlying gapped through the
    # strike since the grab, so the real loss is larger than `last` implies.
    # No IV guesswork; intrinsic is a hard lower bound, so this only corrects
    # understated losses, never invents them.
    strike = float(option.get("strike", 0) or 0)
    underlying_live = float(option.get("underlying_last", 0) or 0)
    right = (option.get("right", "") or "").upper()
    if strike > 0 and underlying_live > 0 and right in ("P", "C"):
        intrinsic = (max(0.0, strike - underlying_live) if right == "P"
                     else max(0.0, underlying_live - strike))
        current_price = max(current_price, intrinsic)

    if credit <= 0:
        return {
            "ticker": ticker,
            "status": "HOLD",
            "recommendation": "No exit plan — missing credit data",
            "reasoning": "",
            "profit_capture_pct": 0,
            "target_close_at": 0,
        }

    # Profit capture: (credit received − current option price) / credit received
    profit_capture = (credit - current_price) / credit
    target_close_at = credit * 0.5  # 50% of original credit

    status = "HEALTHY"
    parts = []

    if profit_capture >= 0.75:
        status = "PROFIT_TARGET_HIT"
        recommendation = f"CLOSE IMMEDIATELY — {profit_capture * 100:.0f}% captured. Free capital for next trade."
        parts.append("Excellent result — free up buying power")
    elif profit_capture >= 0.5:
        status = "PROFIT_TARGET_HIT"
        recommendation = f"CLOSE — {profit_capture * 100:.0f}% profit captured. Redeploy capital."
        parts.append("50% target achieved")
    elif profit_capture <= ROLL_GIVEUP_PROFIT_CAPTURE:
        status = "STOP_ROLL"
        recommendation = (
            f"STOP ROLLING — down {abs(profit_capture) * 100:.0f}% of credit "
            f"(buyback ${current_price:.2f} vs ${credit:.2f} collected). "
            f"Accept assignment or close for the loss; rolling a position this "
            f"deep just defers the loss and ties up capital."
        )
        parts.append("Loss ≥ 1× credit — rolling defers, doesn't fix")
    elif moneyness == "ITM" and dte <= 7:
        status = "ROLL_OR_ASSIGN"
        recommendation = f"ROLL or ACCEPT assignment — ITM with {dte}d DTE"
        parts.append("ITM near expiry")
    elif dte <= 2 and moneyness == "OTM":
        status = "LET_EXPIRE"
        recommendation = f"LET EXPIRE — OTM, {dte}d to expiry"
        parts.append("Theta decay complete")
    elif confidence >= 65:
        status = "BREACH_WARNING"
        recommendation = f"CONSIDER CLOSING — confidence {confidence}% signals breach risk"
        parts.append("Assignment risk elevated")
    elif indicators.get("catalyst_flag"):
        earnings_days = int(indicators.get("earnings_days_away", -1))
        if 0 <= earnings_days <= dte:
            status = "CATALYST_WARNING"
            recommendation = f"EARNINGS ${earnings_days}d (inside DTE) — consider closing before event"
            parts.append("Earnings within DTE")
    else:
        recommendation = f"HOLD — {profit_capture * 100:.0f}% captured, target close at ${target_close_at:.2f}"

    return {
        "ticker": ticker,
        "status": status,
        "recommendation": recommendation,
        "reasoning": " · ".join(parts),
        "profit_capture_pct": round(profit_capture * 100, 1),
        "target_close_at": round(target_close_at, 4),
    }


# ---------- Credit Spread Exit Management ----------
# Dynamic stop-loss trailing for defined-risk verticals (PCS/CCS/IC).
#
# 3-phase stop system:
#   Phase INITIAL  (profit < 25%): stop at loss = 1× credit (spread cost doubles)
#   Phase TRAILING_BE (25-50%):    stop at breakeven (cost = credit)
#   Phase TAKE_PROFIT (≥ 50%):     close, or trail to lock 25% min profit
#
# Mechanical rules:
#   - 21 DTE close (gamma acceleration — Tastytrade backtest: 45 DTE entry +
#     21 DTE exit beats hold-to-expiry by 15% risk-adjusted)
#   - 50% profit target (buy back at half of credit)
#   - 75%+ profit: close immediately
#   - Short strike tested (price within 2%): flag ROLL_OR_CLOSE
#   - Earnings inside DTE: CATALYST_WARNING
# ----------

SPREAD_PROFIT_TARGET = 0.50         # close at 50% of max profit
SPREAD_PROFIT_IMMEDIATE = 0.75      # close immediately at 75%
SPREAD_MECHANICAL_DTE = 21          # gamma-risk close threshold
SPREAD_STOP_INITIAL_MULT = 2.0     # initial stop: spread cost = 2× credit (loss = 1× credit)
SPREAD_STOP_BE_THRESHOLD = 0.25    # trail to breakeven after 25% profit
SPREAD_STOP_LOCK_PCT = 0.25        # lock 25% profit when in take-profit phase
SPREAD_SHORT_TESTED_PCT = 0.02     # flag roll when price within 2% of short strike


def compute_spread_exit_plan(
    spread: dict[str, Any],
    indicators: dict[str, Any],
) -> dict[str, Any]:
    """
    Compute exit plan for a credit spread position (PCS, CCS, or IC).

    Unlike single-leg CSP/CC, credit spreads have defined max loss (width - credit)
    and benefit from dynamic stop-loss trailing that ratchets tighter as profit grows.

    spread dict keys:
        ticker, strategy (PCS/CCS/IC), net_credit (per-share credit received),
        current_spread_value (per-share cost to buy back), dte,
        short_strike, long_strike, underlying_last, width (optional, computed if absent)

    Returns dict with: status, recommendation, reasoning, profit_capture_pct,
        target_close_at, stop_value, stop_phase, width, max_loss_per_share,
        net_credit, current_value
    """
    ticker = spread.get("ticker", "")
    strategy = spread.get("strategy", "PCS")
    net_credit = float(spread.get("net_credit", 0))
    current_value = float(spread.get("current_spread_value", 0))
    dte = int(spread.get("dte", 0))
    short_strike = float(spread.get("short_strike", 0))
    long_strike = float(spread.get("long_strike", 0))
    underlying = float(spread.get("underlying_last", 0))

    # Width: distance between strikes (always positive)
    width = float(spread.get("width", 0))
    if width <= 0 and short_strike > 0 and long_strike > 0:
        width = abs(short_strike - long_strike)
    max_loss = max(0, width - net_credit) if width > 0 else net_credit

    if net_credit <= 0:
        return {
            "ticker": ticker, "strategy": strategy,
            "status": "HOLD",
            "recommendation": "No exit plan — missing credit data",
            "reasoning": "",
            "profit_capture_pct": 0.0,
            "target_close_at": 0.0,
            "stop_value": 0.0,
            "stop_phase": "UNKNOWN",
            "width": width,
            "max_loss_per_share": max_loss,
            "net_credit": net_credit,
            "current_value": current_value,
        }

    # ── Profit tracking ──────────────────────────────────────────────
    # profit = credit received - cost to buy back (positive = winning)
    pnl_per_share = net_credit - current_value
    profit_pct = pnl_per_share / net_credit if net_credit > 0 else 0

    # ── Dynamic stop levels (per-share spread cost thresholds) ────────
    # stop_value = spread cost at which we close for a loss / to protect gains
    if profit_pct >= SPREAD_PROFIT_TARGET:
        # Phase 3: take profit — trail to lock at least 25% of credit
        stop_value = net_credit * (1 - SPREAD_STOP_LOCK_PCT)
        phase = "TAKE_PROFIT"
    elif profit_pct >= SPREAD_STOP_BE_THRESHOLD:
        # Phase 2: trailing breakeven — close if spread cost rises back to credit
        stop_value = net_credit
        phase = "TRAILING_BE"
    else:
        # Phase 1: initial — stop at 2× credit (loss = 1× credit = max you could make)
        stop_value = net_credit * SPREAD_STOP_INITIAL_MULT
        phase = "INITIAL"

    # Target close value: buy back spread at 50% of original credit
    target_close_value = net_credit * (1 - SPREAD_PROFIT_TARGET)

    # ── Status determination ──────────────────────────────────────────
    status = "HEALTHY"
    recommendation = ""
    parts: list[str] = []

    # Check distance from short strike (for roll/close trigger)
    short_tested = False
    if underlying > 0 and short_strike > 0:
        dist_to_short_pct = abs(underlying - short_strike) / short_strike
        # Directional check: for PCS the danger is price dropping TO short put,
        # for CCS the danger is price rising TO short call
        if strategy in ("PCS",):
            price_approaching = underlying <= short_strike * (1 + SPREAD_SHORT_TESTED_PCT)
        elif strategy in ("CCS",):
            price_approaching = underlying >= short_strike * (1 - SPREAD_SHORT_TESTED_PCT)
        else:
            # IC: either side could be tested
            price_approaching = dist_to_short_pct <= SPREAD_SHORT_TESTED_PCT
        short_tested = price_approaching and dist_to_short_pct <= SPREAD_SHORT_TESTED_PCT

    # Priority cascade (highest severity first)
    if profit_pct >= SPREAD_PROFIT_IMMEDIATE:
        status = "PROFIT_TARGET_HIT"
        recommendation = (
            f"CLOSE NOW — {profit_pct * 100:.0f}% profit captured "
            f"(credit ${net_credit:.2f}, buyback ${current_value:.2f}). "
            f"Redeploy capital."
        )
        parts.append("Excellent result — free buying power immediately")

    elif profit_pct >= SPREAD_PROFIT_TARGET:
        status = "PROFIT_TARGET_HIT"
        recommendation = (
            f"CLOSE — {profit_pct * 100:.0f}% profit target hit. "
            f"Buy back at ${current_value:.2f} (credit was ${net_credit:.2f})."
        )
        parts.append("50% target achieved — standard close")

    elif dte <= SPREAD_MECHANICAL_DTE and dte > 0:
        status = "MECHANICAL_CLOSE"
        pnl_label = f"{profit_pct * 100:+.0f}%" if profit_pct != 0 else "flat"
        recommendation = (
            f"CLOSE — {dte}d DTE (21 DTE mechanical close). "
            f"Gamma risk accelerates. P&L: {pnl_label}."
        )
        parts.append(f"21 DTE mechanical close ({dte}d remaining)")

    elif dte <= 0:
        status = "EXPIRED"
        recommendation = f"EXPIRED — review outcome. P&L: {profit_pct * 100:+.0f}%."
        parts.append("Position expired")

    elif short_tested and profit_pct < 0:
        status = "ROLL_OR_CLOSE"
        recommendation = (
            f"ROLL OR CLOSE — short ${short_strike:.0f} strike tested "
            f"(underlying ${underlying:.2f}). "
            f"P&L: {profit_pct * 100:+.0f}%. "
            f"Consider rolling out in time for net credit."
        )
        parts.append("Short strike tested — roll for credit or cut loss")

    elif current_value >= stop_value and phase == "INITIAL":
        loss_per_share = current_value - net_credit
        status = "STOP_TRIGGERED"
        recommendation = (
            f"CLOSE LOSS — spread cost ${current_value:.2f} breached "
            f"${stop_value:.2f} stop (1× credit loss). "
            f"Loss: ${loss_per_share:.2f}/share."
        )
        parts.append("Dynamic stop triggered (loss = credit received)")

    elif current_value >= stop_value and phase == "TRAILING_BE":
        status = "STOP_TRIGGERED"
        recommendation = (
            f"CLOSE — spread cost ${current_value:.2f} breached breakeven stop "
            f"${stop_value:.2f}. Protect remaining capital."
        )
        parts.append("Trailing breakeven stop triggered")

    elif profit_pct < -0.30:
        status = "WARNING"
        recommendation = (
            f"WARNING — losing {abs(profit_pct) * 100:.0f}% "
            f"(cost ${current_value:.2f} vs credit ${net_credit:.2f}). "
            f"Stop at ${stop_value:.2f}. Monitor closely."
        )
        parts.append("Underwater but stop not yet hit")

    else:
        recommendation = (
            f"HOLD — {profit_pct * 100:+.0f}% captured. "
            f"Target close at ${target_close_value:.2f}. "
            f"Stop: ${stop_value:.2f} ({phase})."
        )

    # ── Catalyst overlay ──────────────────────────────────────────────
    if indicators.get("catalyst_flag") and status in ("HEALTHY", "HOLD"):
        earnings_days = int(indicators.get("earnings_days_away", -1))
        if 0 <= earnings_days <= dte:
            status = "CATALYST_WARNING"
            recommendation = (
                f"EARNINGS in {earnings_days}d (inside DTE) — "
                f"consider closing before event. P&L: {profit_pct * 100:+.0f}%."
            )
            parts.append("Earnings within DTE — binary risk")

    return {
        "ticker": ticker,
        "strategy": strategy,
        "status": status,
        "recommendation": recommendation,
        "reasoning": " · ".join(parts) if parts else f"{strategy} spread — monitoring",
        "profit_capture_pct": round(profit_pct * 100, 1),
        "target_close_at": round(target_close_value, 4),
        "stop_value": round(stop_value, 4),
        "stop_phase": phase,
        "width": round(width, 2),
        "max_loss_per_share": round(max_loss, 4),
        "net_credit": round(net_credit, 4),
        "current_value": round(current_value, 4),
    }
