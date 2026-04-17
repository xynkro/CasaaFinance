"""
technical_score.py — Strategy-specific technical scoring.

Takes indicator dict (from indicators.compute_indicators) and produces a score
in [-100, +100] for each strategy: BUY, CSP, CC, LONG_CALL, LONG_PUT.

Positive = environment favors that strategy. Negative = environment hostile.

Design choice vs the XLSM:
  - Signals are CONTINUOUS (not binary) — RSI 72 and RSI 95 get different weights.
  - Each strategy has its OWN weights — CC sellers want overbought, CSP sellers
    want oversold, stock buyers want neither extreme.
  - Score is normalized to [-100, 100] so thresholds are interpretable.
  - Alongside the score we emit the reasoning components for audit / UI.
"""
from __future__ import annotations

from typing import Any


# -----------------------------------------------------------------------------
# Signal extraction — each returns a value in roughly [-1, +1] representing
# strength/direction. These are then weighted per strategy below.
# -----------------------------------------------------------------------------

def _sig_rsi(rsi: float) -> float:
    """
    RSI signal. Oversold = negative (bearish pressure but potentially reversal),
    Overbought = positive.
    -1 = very oversold (RSI 0), +1 = very overbought (RSI 100), 0 = neutral (50)
    """
    return (rsi - 50) / 50


def _sig_stoch(k: float, d: float) -> float:
    """Stochastic signal, similar scaling to RSI."""
    avg = (k + d) / 2
    return (avg - 50) / 50


def _sig_macd(macd_hist: float, close: float) -> float:
    """MACD histogram strength relative to price. Positive = bullish momentum."""
    if close <= 0:
        return 0.0
    # hist normalized by price (rough proxy for magnitude)
    norm = macd_hist / close
    # typical range ~±0.01, clip to ±1
    return max(-1.0, min(1.0, norm * 100))


def _sig_macd_cross(cross: str) -> float:
    """Recent MACD crossover event (within last 3 bars)."""
    if cross == "bullish":
        return 1.0
    if cross == "bearish":
        return -1.0
    return 0.0


def _sig_bb_pct_b(pct_b: float) -> float:
    """BB %B. 0 = at lower band (pressure/oversold), 1 = upper band (overbought)."""
    return (pct_b - 0.5) * 2  # map [0,1] -> [-1, +1]


def _sig_bb_squeeze(squeeze: bool) -> float:
    """Squeeze = pending breakout. Neutral direction but strategically relevant."""
    return 1.0 if squeeze else 0.0


def _sig_wvf(wvf_bottom: bool) -> float:
    """Williams VIX Fix bottom signal = capitulation / bullish reversal."""
    return 1.0 if wvf_bottom else 0.0


def _sig_trend(trend: str) -> float:
    """Trend classification to numeric."""
    return {
        "Strong Uptrend": 1.0,
        "Uptrend": 0.5,
        "Sideways": 0.0,
        "Downtrend": -0.5,
        "Strong Downtrend": -1.0,
        "Unknown": 0.0,
    }.get(trend, 0.0)


def _sig_momentum(momentum_5d: float) -> float:
    """5-day % move, mapped to [-1, +1] with soft clip at ±10%."""
    return max(-1.0, min(1.0, momentum_5d / 10.0))


def _sig_volume_spike(vol_spike_type: str) -> float:
    """Volume spike with direction."""
    if vol_spike_type == "bullish":
        return 1.0
    if vol_spike_type == "bearish":
        return -1.0
    return 0.0


def _sig_divergence(div: str) -> float:
    """RSI/price divergence signals reversal."""
    if div == "bullish":
        return 1.0
    if div == "bearish":
        return -1.0
    return 0.0


def _sig_candle(candle: str) -> float:
    """Last candle pattern as a small directional signal."""
    return {
        "engulfing_bullish": 1.0,
        "hammer_bullish": 0.8,
        "strong_bullish": 0.6,
        "engulfing_bearish": -1.0,
        "shooting_star_bearish": -0.8,
        "strong_bearish": -0.6,
        "doji": 0.0,
        "hammer_neutral": 0.2,
        "neutral": 0.0,
        "none": 0.0,
    }.get(candle, 0.0)


def _sig_fib_support(close: float, support: float, resistance: float) -> float:
    """
    Proximity to support/resistance:
      near support = positive (bullish bounce candidate)
      near resistance = negative
    """
    if close <= 0 or resistance <= support:
        return 0.0
    # How close to support vs resistance on a 0-1 scale
    position = (close - support) / (resistance - support)
    # Near support (position near 0) = +1; near resistance (position near 1) = -1
    return max(-1.0, min(1.0, 1 - 2 * position))


# -----------------------------------------------------------------------------
# Strategy weights. The key is each strategy's *preference* for the signal.
# Positive weight on a signal means the strategy benefits when that signal is
# positive; negative weight means it benefits when the signal is negative.
#
# Example:
#   - "CC" (covered call seller) benefits when stock is overbought (high RSI
#     signal), because that increases odds of pullback → CC expires OTM.
#     So CC has +4 on rsi.
#   - "CSP" (cash-secured put seller) benefits when stock is oversold and
#     near support → bounce likely → put expires OTM.
#     So CSP has -4 on rsi (negative RSI signal = bullish bounce setup).
# -----------------------------------------------------------------------------

STRATEGY_WEIGHTS: dict[str, dict[str, float]] = {
    "BUY": {
        "rsi":            -2,   # overbought BAD for fresh entry
        "stoch":          -2,
        "macd":           +3,   # bullish momentum GOOD
        "macd_cross":     +4,
        "bb_pct_b":       -2,   # price at upper band = stretched, bad entry
        "bb_squeeze":     +2,   # pending breakout = opportunity
        "wvf":            +5,   # market bottom = best entry
        "trend":          +5,   # uptrend critical for buying
        "momentum":       +3,
        "volume_spike":   +2,
        "divergence":     +2,
        "candle":         +2,
        "fib_support":    +3,   # near support = good buy zone
    },
    "CSP": {
        # Cash-secured put seller: wants oversold + support holding + bullish reversal
        # so the put expires worthless
        "rsi":            -4,   # oversold helps (negative RSI signal = bullish)
        "stoch":          -3,
        "macd":           +3,   # bullish momentum keeps price up
        "macd_cross":     +4,
        "bb_pct_b":       -3,   # near lower band, bounce expected
        "bb_squeeze":     +1,
        "wvf":            +6,   # best CSP timing
        "trend":          +3,   # uptrend favors CSP
        "momentum":       +2,
        "volume_spike":   +2,   # bullish spike confirms
        "divergence":     +4,   # bullish divergence strong
        "candle":         +3,
        "fib_support":    +5,   # near support best CSP entry
    },
    "CC": {
        # Covered call seller: wants overbought + resistance + bearish reversal
        # so the call expires worthless
        "rsi":            +4,   # overbought helps (call expiry OTM)
        "stoch":          +3,
        "macd":           -2,   # bearish momentum helps the CC
        "macd_cross":     -3,
        "bb_pct_b":       +3,   # near upper band = pullback likely
        "bb_squeeze":     +1,
        "wvf":            -3,   # market bottom = wrong time for CC
        "trend":          +1,   # slight uptrend OK (IV persists); strong uptrend risky
        "momentum":       -2,
        "volume_spike":   -2,   # bullish spike = risk of being called away
        "divergence":     -3,   # bearish divergence helps the CC seller
        "candle":         -2,
        "fib_support":    -3,   # near support = upside setup = bad for CC
    },
    "LONG_CALL": {
        "rsi":            -2,
        "stoch":          -2,
        "macd":           +4,
        "macd_cross":     +5,
        "bb_pct_b":       -1,
        "bb_squeeze":     +3,   # squeeze breakout = leveraged long call upside
        "wvf":            +4,
        "trend":          +4,
        "momentum":       +3,
        "volume_spike":   +3,
        "divergence":     +3,
        "candle":         +2,
        "fib_support":    +3,
    },
    "LONG_PUT": {
        "rsi":            +3,
        "stoch":          +3,
        "macd":           -4,
        "macd_cross":     -5,
        "bb_pct_b":       +2,
        "bb_squeeze":     +2,
        "wvf":            -3,
        "trend":          -4,
        "momentum":       -3,
        "volume_spike":   -2,
        "divergence":     -3,
        "candle":         -2,
        "fib_support":    -2,
    },
}


def compute_signals(ind: dict[str, Any]) -> dict[str, float]:
    """Extract normalized signals from indicator dict."""
    return {
        "rsi":          _sig_rsi(ind.get("rsi_14", 50.0)),
        "stoch":        _sig_stoch(ind.get("stoch_k", 50.0), ind.get("stoch_d", 50.0)),
        "macd":         _sig_macd(ind.get("macd_hist", 0.0), ind.get("close", 1.0)),
        "macd_cross":   _sig_macd_cross(ind.get("macd_cross", "none")),
        "bb_pct_b":     _sig_bb_pct_b(ind.get("bb_pct_b", 0.5)),
        "bb_squeeze":   _sig_bb_squeeze(ind.get("bb_squeeze", False)),
        "wvf":          _sig_wvf(ind.get("wvf_bottom", False)),
        "trend":        _sig_trend(ind.get("trend", "Unknown")),
        "momentum":     _sig_momentum(ind.get("momentum_5d", 0.0)),
        "volume_spike": _sig_volume_spike(ind.get("vol_spike_type", "none")),
        "divergence":   _sig_divergence(ind.get("divergence", "none")),
        "candle":       _sig_candle(ind.get("candle_pattern", "none")),
        "fib_support":  _sig_fib_support(
            ind.get("close", 0.0),
            ind.get("support", 0.0),
            ind.get("resistance", 0.0),
        ),
    }


def compute_scores(ind: dict[str, Any]) -> dict[str, float]:
    """
    Compute score per strategy, each in [-100, +100].
    Returns dict with keys: BUY, CSP, CC, LONG_CALL, LONG_PUT
    """
    if not ind:
        return {k: 0.0 for k in STRATEGY_WEIGHTS}

    signals = compute_signals(ind)
    out = {}
    for strat, weights in STRATEGY_WEIGHTS.items():
        score = 0.0
        max_possible = 0.0
        for sig_name, weight in weights.items():
            s = signals.get(sig_name, 0.0)
            score += s * weight
            max_possible += abs(weight)
        if max_possible > 0:
            out[strat] = round(score / max_possible * 100, 1)
        else:
            out[strat] = 0.0
    return out


def score_label(score: float) -> str:
    """Bucket a score into a label."""
    if score >= 60:
        return "STRONG"
    if score >= 30:
        return "FAVORABLE"
    if score > -30:
        return "NEUTRAL"
    if score > -60:
        return "UNFAVORABLE"
    return "HOSTILE"


def entry_exit_signal(ind: dict[str, Any], scores: dict[str, float]) -> str:
    """
    Produce a simple BUY / HOLD / SELL (SL) signal for stock positions.
    Based on BUY score + trend + key reversal signals.
    """
    buy_score = scores.get("BUY", 0.0)
    trend = ind.get("trend", "Unknown")
    close = ind.get("close", 0.0)
    support = ind.get("support", 0.0)

    # Hard sell if price broke below 60-day support (stop-loss)
    if support > 0 and close > 0 and close < support * 0.98:
        return "SELL (SL)"

    if buy_score >= 50 and trend in ("Strong Uptrend", "Uptrend", "Sideways"):
        return "BUY"
    if buy_score <= -40 or trend == "Strong Downtrend":
        return "SELL (SL)"
    return "HOLD"


def top_signal_reasons(ind: dict[str, Any], strategy: str, limit: int = 3) -> list[str]:
    """Return the top signals that drove this strategy's score (for UI explain)."""
    if strategy not in STRATEGY_WEIGHTS:
        return []
    signals = compute_signals(ind)
    weights = STRATEGY_WEIGHTS[strategy]
    contributions = []
    for sig_name, weight in weights.items():
        s = signals.get(sig_name, 0.0)
        contrib = s * weight
        if abs(contrib) < 0.5:
            continue
        contributions.append((sig_name, contrib, s))
    contributions.sort(key=lambda x: abs(x[1]), reverse=True)

    friendly = {
        "rsi": "RSI", "stoch": "Stoch",
        "macd": "MACD", "macd_cross": "MACD cross",
        "bb_pct_b": "BB position", "bb_squeeze": "BB squeeze",
        "wvf": "WVF bottom", "trend": "Trend",
        "momentum": "Momentum", "volume_spike": "Volume",
        "divergence": "Divergence", "candle": "Candle",
        "fib_support": "Fib position",
    }
    out = []
    for sig_name, contrib, raw in contributions[:limit]:
        label = friendly.get(sig_name, sig_name)
        direction = "+" if contrib > 0 else "−"
        out.append(f"{direction}{label}")
    return out
