"""
Quality scoring for Unusual Options Activity.

The raw UOA feed answers "was there a lot of volume?" — which is not the
question. Reviewing the 2026-08-24 digest, 4 of the 10 loudest alerts were deep
ITM options trading at PARITY (ARM $430 put with $0.85 of time value; AMZN $220
call with $0.32). Those are stock substitutes, financing legs, or arbitrage —
100-delta instruments with no optionality. Nobody trading on information buys a
$193 put for $0.85 of time value; they buy cheap convexity. Worse, three of them
ranked loudest *because* their open interest was 1–4, so Vol/OI exploded
arithmetically (620x on OI=1 is a division artifact, not a signal).

This module adds the four things that separate informative flow from noise:

  1. AGGRESSOR SIDE — the scanner already pulls bid/ask/lastPrice from yfinance
     and discards them. Comparing the trade print to the quote gives a
     Lee-Ready-style read of who initiated, which turns "a PUT traded" into
     "a put was BOUGHT (bearish)" vs "a put was SOLD (bullish)" — opposite
     conclusions from the same row.
  2. EXTRINSIC VALUE — near-parity contracts carry no view; filter them out.
  3. OPEN-INTEREST FLOOR — Vol/OI is meaningless when OI is a handful.
  4. PERSISTENCE — a one-off print is noise; the same ticker and direction
     recurring across days is far harder to explain away as hedging.

IMPORTANT LIMITATION, stated up front: `lastPrice` is the last trade of the
session while bid/ask are the quote at scan time (end of day). The aggressor
read is therefore a PROXY, not tick-level trade-condition data. It is materially
better than nothing and it is free, but it is not proof, and it should be graded
against outcomes before anything is traded on it.
"""
from __future__ import annotations

from collections import defaultdict

# A print within this fraction of the spread from bid/ask is called initiated.
# 0.35 → at/above 65% of the spread = buyer-initiated; at/below 35% = seller.
AGGRESSOR_TOL = 0.35

# Time value below this share of premium ⇒ a parity/stock-substitute contract.
MIN_EXTRINSIC_PCT = 5.0

# Vol/OI is not computed below this open interest (division artifact guard).
MIN_OI_FOR_RATIO = 50

BULLISH, BEARISH, NEUTRAL, UNKNOWN = "BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def extrinsic_value(side: str, strike: float, spot: float, premium: float) -> float:
    """Time value in the premium (premium − intrinsic), floored at 0."""
    s = (side or "").upper()
    intrinsic = max(0.0, (strike - spot) if s.startswith("P") else (spot - strike))
    return max(0.0, premium - intrinsic)


def extrinsic_pct(side: str, strike: float, spot: float, premium: float) -> float:
    """Time value as a percentage of premium. 0 when premium is unusable."""
    if premium <= 0:
        return 0.0
    return extrinsic_value(side, strike, spot, premium) / premium * 100.0


def is_near_parity(side: str, strike: float, spot: float, premium: float,
                   min_pct: float = MIN_EXTRINSIC_PCT) -> bool:
    """True for stock-substitute / financing contracts carrying no directional view."""
    return extrinsic_pct(side, strike, spot, premium) < min_pct


def safe_vol_oi(volume: float, open_interest: float,
                min_oi: int = MIN_OI_FOR_RATIO) -> float | None:
    """Vol/OI, or None when OI is too small for the ratio to mean anything."""
    oi = _f(open_interest)
    if oi < min_oi:
        return None
    return _f(volume) / oi


def aggressor_side(last: float, bid: float, ask: float,
                   tol: float = AGGRESSOR_TOL) -> str:
    """Who initiated: BUY_INITIATED | SELL_INITIATED | MID | UNKNOWN.

    Position of the print within the bid-ask spread. At/near the ask implies the
    buyer crossed (lifted the offer); at/near the bid implies the seller hit the
    bid. Returns UNKNOWN on a crossed, zero, or absent quote rather than guessing.
    """
    last, bid, ask = _f(last), _f(bid), _f(ask)
    if last <= 0 or bid <= 0 or ask <= 0 or ask < bid:
        return "UNKNOWN"
    span = ask - bid
    if span <= 0:
        return "UNKNOWN"
    pos = (last - bid) / span
    if pos >= 1 - tol:
        return "BUY_INITIATED"
    if pos <= tol:
        return "SELL_INITIATED"
    return "MID"


def directional_read(side: str, aggressor: str) -> tuple[str, str]:
    """(structure, bias) — the long/short call/put question, answered.

    CALL bought  → LONG_CALL,  bullish        PUT bought → LONG_PUT,  bearish
    CALL sold    → SHORT_CALL, bearish/neutral PUT sold  → SHORT_PUT, bullish
    Anything unresolved returns UNCLEAR/UNKNOWN — never a guess.
    """
    s = (side or "").upper()
    is_call = s.startswith("C")
    if aggressor == "BUY_INITIATED":
        return ("LONG_CALL", BULLISH) if is_call else ("LONG_PUT", BEARISH)
    if aggressor == "SELL_INITIATED":
        return ("SHORT_CALL", BEARISH) if is_call else ("SHORT_PUT", BULLISH)
    return "UNCLEAR", UNKNOWN


def classify_open_close(volume: float, oi_today: float, oi_next: float | None,
                        tolerance: float = 0.30) -> str:
    """OPENING | CLOSING | MIXED | UNKNOWN from the next session's OI change.

    OI rising by roughly the traded volume means new positions were opened (the
    informative case). OI falling means positions were closed — a roll or an
    exit, not a fresh view. Requires the FOLLOWING day's OI, so it is always a
    day late; that is inherent, not a defect.
    """
    if oi_next is None:
        return "UNKNOWN"
    vol = _f(volume)
    if vol <= 0:
        return "UNKNOWN"
    delta = _f(oi_next) - _f(oi_today)
    if delta >= vol * (1 - tolerance):
        return "OPENING"
    if delta <= -vol * (1 - tolerance):
        return "CLOSING"
    if delta > vol * 0.15:
        return "MIXED"
    if delta < -vol * 0.15:
        return "MIXED"
    return "MIXED"


def persistence(alerts: list[dict], ticker: str, bias: str) -> int:
    """Distinct days this ticker showed the same directional bias.

    Repetition is the cheapest defence against reading one hedge as a signal.
    """
    days = {(a.get("date") or "")[:10] for a in alerts
            if (a.get("ticker") or "").upper() == (ticker or "").upper()
            and a.get("bias") == bias and (a.get("date") or "")}
    return len(days)


def quality_score(*, extrinsic_pct_val: float, vol_oi: float | None,
                  aggressor: str, notional: float, persist_days: int) -> int:
    """0–100 confidence that a print reflects a directional VIEW.

    Deliberately harsh: a contract with no time value, an unusable Vol/OI, and
    an unreadable aggressor scores near zero however large the notional. Size
    alone is the weakest evidence — it is what made the parity trades look loud.
    """
    score = 0
    # Real optionality (0-30) — the single best discriminator.
    score += min(30, int(extrinsic_pct_val * 0.3))
    # Genuine volume surprise (0-25), only when OI is large enough to trust.
    if vol_oi is not None:
        score += min(25, int(vol_oi * 5))
    # Direction actually readable (0-25).
    score += {"BUY_INITIATED": 25, "SELL_INITIATED": 25, "MID": 8}.get(aggressor, 0)
    # Size (0-10), capped — big is not the same as informed.
    score += min(10, int(_f(notional) / 1_000_000 * 2))
    # Repetition across sessions (0-10).
    score += min(10, max(0, persist_days - 1) * 5)
    return max(0, min(100, score))
