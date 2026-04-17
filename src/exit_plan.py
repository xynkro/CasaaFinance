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
        "atr_stop_mult": 2.0,            # 2x ATR below current — tracking stop
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

    if profit_capture >= 0.5:
        status = "PROFIT_TARGET_HIT"
        recommendation = f"CLOSE — {profit_capture * 100:.0f}% profit captured. Redeploy capital."
        parts.append("50% target achieved")
    elif profit_capture >= 0.75:
        status = "PROFIT_TARGET_HIT"
        recommendation = f"CLOSE IMMEDIATELY — {profit_capture * 100:.0f}% captured. Free capital for next trade."
        parts.append("Excellent result — free up buying power")
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
