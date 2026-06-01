"""
gex.py — dealer Gamma Exposure (GEX) regime math.

WHY THIS EXISTS
  The market's intraday character is shaped by how options dealers must hedge.
  Barbon & Buraschi (2021, "Gamma Fragility", SSRN 3725454) document the link:
  when dealers are net LONG gamma they hedge AGAINST moves (sell rallies / buy
  dips) → volatility is suppressed → the tape PINS / chops. When dealers are
  net SHORT gamma they hedge WITH moves (buy rallies / sell dips) → volatility
  is amplified → the tape TRENDS / squeezes.

  For a PREMIUM SELLER (CSP / CC / credit spreads), that distinction is a direct
  risk gate: positive-gamma days are friendly (theta decays, price pins inside
  your short strikes); negative-gamma days carry gap risk straight through them.

CONVENTION (the canonical retail / SqueezeMetrics simplification)
  Dealer positioning isn't observable, so we use the standard heuristic that
  customers are net long puts (hedging) and net short calls (overwriting) — i.e.
  dealers are long calls and short puts. Each strike contributes signed dealer
  dollar-gamma:
      call:  +gamma · OI · 100 · spot² · 0.01     (dealer long gamma)
      put :  −gamma · OI · 100 · spot² · 0.01     (dealer short gamma)
  The "· spot² · 0.01" expresses the $ change in dealer delta per 1% move; 100
  is the contract multiplier. Net GEX = Σ over the chain.

  This is a HEURISTIC, not ground truth — it is most meaningful on index / very
  liquid names (SPY, QQQ, mega-caps) and noise on thin single-name chains.

All functions are pure and unit-tested. Gamma is recomputed from Black-Scholes
(reusing src.wheel_continuation.bs_gamma) so the gamma-flip search can re-evaluate
the book at hypothetical spot levels.
"""
from __future__ import annotations

from typing import Iterable, Optional

from src.wheel_continuation import bs_gamma

CONTRACT_MULTIPLIER = 100
DEFAULT_R = 0.045

# An option spec is a dict: {"strike": float, "T": years, "sigma": iv_decimal,
#                            "oi": int, "right": "C"|"P"}.


def signed_dollar_gamma(opt: dict, spot: float, r: float = DEFAULT_R) -> float:
    """Dealer dollar-gamma for one strike at `spot`, signed (calls +, puts −).

    Units: $ change in dealer delta per 1% move in the underlying.
    """
    if spot <= 0:
        return 0.0
    g = bs_gamma(spot, float(opt["strike"]), float(opt["T"]),
                 float(opt["sigma"]), r)
    base = g * float(opt["oi"]) * CONTRACT_MULTIPLIER * spot * spot * 0.01
    return base if str(opt["right"]).upper().startswith("C") else -base


def net_gex(options: Iterable[dict], spot: float, r: float = DEFAULT_R) -> float:
    """Net dealer dollar-gamma across the whole chain at `spot`."""
    return sum(signed_dollar_gamma(o, spot, r) for o in options)


def gross_gex(options: Iterable[dict], spot: float, r: float = DEFAULT_R) -> float:
    """Sum of |signed dollar-gamma| — the scale used to judge if net is decisive."""
    return sum(abs(signed_dollar_gamma(o, spot, r)) for o in options)


def gex_by_strike(options: Iterable[dict], spot: float,
                  r: float = DEFAULT_R) -> dict[float, float]:
    """Aggregate signed dealer dollar-gamma per strike (calls + puts netted)."""
    agg: dict[float, float] = {}
    for o in options:
        k = float(o["strike"])
        agg[k] = agg.get(k, 0.0) + signed_dollar_gamma(o, spot, r)
    return agg


def _wall(options: Iterable[dict], spot: float, right: str,
          side: str, r: float) -> Optional[float]:
    """Strike with the largest |dealer dollar-gamma| for one option right,
    preferring strikes on the relevant side of spot (calls above, puts below)."""
    mag: dict[float, float] = {}
    for o in options:
        if not str(o["right"]).upper().startswith(right):
            continue
        k = float(o["strike"])
        mag[k] = mag.get(k, 0.0) + abs(signed_dollar_gamma(o, spot, r))
    if not mag:
        return None
    if side == "above":
        pool = {k: v for k, v in mag.items() if k >= spot} or mag
    else:
        pool = {k: v for k, v in mag.items() if k <= spot} or mag
    return max(pool, key=pool.get)


def call_wall(options: Iterable[dict], spot: float, r: float = DEFAULT_R) -> Optional[float]:
    """Largest call-gamma strike at/above spot — acts as resistance / a magnet
    cap. Don't buy calls into it."""
    return _wall(options, spot, "C", "above", r)


def put_wall(options: Iterable[dict], spot: float, r: float = DEFAULT_R) -> Optional[float]:
    """Largest put-gamma strike at/below spot — acts as support."""
    return _wall(options, spot, "P", "below", r)


def gamma_flip_level(options: Iterable[dict], spot: float, r: float = DEFAULT_R,
                     lo: float = 0.85, hi: float = 1.15,
                     steps: int = 120) -> Optional[float]:
    """Spot price at which net dealer gamma crosses zero ("zero-gamma" level).

    Below the flip dealers are typically short gamma (trend); above it, long
    gamma (pin). Found by recomputing net GEX over a spot grid and locating the
    sign change nearest current spot. Returns None if no crossing in [lo,hi]·spot.
    """
    opts = list(options)
    if spot <= 0 or not opts or steps < 2:
        return None
    width = (hi - lo) * spot
    prev_s = lo * spot
    prev_n = net_gex(opts, prev_s, r)
    best: Optional[float] = None
    best_dist = float("inf")
    for i in range(1, steps + 1):
        s = lo * spot + width * i / steps
        n = net_gex(opts, s, r)
        if prev_n == 0.0:
            cross = prev_s
        elif (prev_n < 0) != (n < 0):
            # linear interpolation of the zero crossing between prev_s and s
            denom = (n - prev_n)
            cross = prev_s + (s - prev_s) * (-prev_n / denom) if denom else (prev_s + s) / 2
        else:
            prev_s, prev_n = s, n
            continue
        dist = abs(cross - spot)
        if dist < best_dist:
            best, best_dist = cross, dist
        prev_s, prev_n = s, n
    return best


def classify_regime(net: float, gross: float, neutral_frac: float = 0.10) -> str:
    """POSITIVE_PINNED | NEGATIVE_TREND | NEUTRAL.

    Scale-free: a chain is NEUTRAL when net gamma is small relative to gross
    gamma (the longs and shorts roughly cancel), so the same thresholds work
    across SPY, QQQ, and single names of very different size.
    """
    if gross <= 0:
        return "NEUTRAL"
    if abs(net) / gross < neutral_frac:
        return "NEUTRAL"
    return "POSITIVE_PINNED" if net > 0 else "NEGATIVE_TREND"


def premium_gate(regime: str) -> str:
    """Map a regime to a premium-selling instruction for the executor.

    SELL_OK     — positive gamma, vol suppressed → friendly for CSP/CC/spreads.
    SELL_CAUTION— negative gamma, gap risk → stand down / widen short strikes.
    NORMAL      — no decisive signal.
    """
    return {
        "POSITIVE_PINNED": "SELL_OK",
        "NEGATIVE_TREND": "SELL_CAUTION",
    }.get(regime, "NORMAL")


def regime_note(symbol: str, spot: float, net: float, flip: Optional[float],
                call_wall_k: Optional[float], put_wall_k: Optional[float],
                regime: str) -> str:
    """One-line human summary for the PWA banner + Telegram."""
    bn = net / 1e9
    bits = [f"{symbol} net GEX {bn:+.2f}$bn"]
    if flip:
        rel = (spot - flip) / spot * 100 if spot else 0.0
        side = "above" if spot >= flip else "below"
        bits.append(f"spot {abs(rel):.1f}% {side} flip {flip:,.0f}")
    if call_wall_k:
        bits.append(f"call wall {call_wall_k:,.0f}")
    if put_wall_k:
        bits.append(f"put wall {put_wall_k:,.0f}")
    tail = {
        "POSITIVE_PINNED": "dealers long gamma → vol suppressed, premium-selling friendly.",
        "NEGATIVE_TREND": "dealers short gamma → vol expansion / gap risk, sell premium with caution.",
        "NEUTRAL": "mixed positioning → no decisive gamma signal.",
    }.get(regime, "")
    return " · ".join(bits) + (". " + tail if tail else "")
