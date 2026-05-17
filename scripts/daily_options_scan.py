"""
daily_options_scan.py — Cloud-native replacement for the IBKR-required
Daily Scan card on the PWA Options page.

Scans the user's WATCHLIST (current positions + decision queue + a curated
cross-reference) via yfinance for fresh CSP/CC opportunities each morning.
Writes to the `scan_results` sheet that the PWA Daily Scan card reads.

Differences from market_scan.py:
  - market_scan: BROAD universe (LunarCrush + WSB + quality watchlist)
                 → option_recommendations sheet (history archive; brain
                   reads last 30 rows for context per generate_wsr_full.py
                   and generate_daily_brief.py — no PWA surface since
                   Phase D of the Decisions↔Ideas merge)
  - daily_options_scan: USER'S OWN tickers (positions + queue)
                 → scan_results sheet → "Daily Scan" card (executable)

Triggered daily by .github/workflows/daily-options-scan.yml at 10:35 SGT
(US market open + 3h, fresh option chains).

Usage:
  python scripts/daily_options_scan.py            # full live scan
  python scripts/daily_options_scan.py --dry      # print, no sheet write
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Same thresholds as trading_rules.py CSP_RULES / CC_RULES
CSP_DTE_RANGE   = (15, 50)
CC_DTE_RANGE    = (15, 50)
TARGET_DTE      = 35
CSP_OTM_RANGE   = (0.02, 0.18)   # 2%-18% OTM
CC_OTM_RANGE    = (0.01, 0.10)   # 1%-10% OTM
MIN_OI          = 50
MIN_MID         = 0.05
MIN_CSP_YIELD   = 12.0    # annualised %
MIN_CC_YIELD    = 10.0
MIN_PRICE       = 3.0
MAX_PRICE       = 800
MAX_PER_TICKER  = 2       # at most 1 CSP + 1 CC per ticker

# LONG_CALL — directional play for gov confluence catalysts
# When Congress is cluster buying + fresh contracts, a long call
# captures the upside thesis the confluence data implies.
LC_DTE_RANGE    = (30, 60)       # 30-60 DTE for swing thesis
LC_TARGET_DTE   = 45
LC_DELTA_RANGE  = (0.35, 0.65)   # ATM-ish, 0.40-0.60 sweet spot
LC_MAX_PREMIUM_PCT = 0.05        # max 5% of underlying as premium
LC_MIN_OI       = 20             # lower bar than income trades
LC_MIN_QUALITY  = 40             # minimum quality score to emit a LONG_CALL

# IRON CONDOR — neutral range-bound play, tastytrade criteria
IC_DTE_RANGE    = (30, 55)
IC_TARGET_DTE   = 45
IC_OTM_RANGE    = (0.07, 0.16)   # 7-16% OTM ≈ ~15-25Δ
IC_WING_WIDTHS  = [5, 10]        # try $5 wings first, then $10
IC_MIN_CREDIT_RATIO = 0.30       # credit/width ≥ 30%
IC_MIN_IVR      = 40             # need elevated IV environment
IC_MIN_OI       = 20
IC_MIN_QUALITY  = 30

# CREDIT SPREADS — directional plays, tastytrade criteria
CS_DTE_RANGE    = (25, 50)
CS_TARGET_DTE   = 42
CS_OTM_RANGE    = (0.04, 0.12)   # 4-12% OTM ≈ ~20-35Δ
CS_WING_WIDTHS  = [5, 10]
CS_MIN_CREDIT_RATIO = 0.28       # ~1/3 width credit
CS_MIN_IVR      = 25             # lower bar than IC
CS_MIN_OI       = 20
CS_MIN_QUALITY  = 25

# PMCC — Poor Man's Covered Call (diagonal spread)
PMCC_LEAPS_MIN_DTE  = 270        # 9+ months out
PMCC_LEAPS_ITM      = (0.05, 0.20)   # 5-20% ITM ≈ 0.65-0.85Δ
PMCC_SHORT_DTE_RANGE = (25, 50)
PMCC_SHORT_OTM      = (0.04, 0.12)   # 4-12% OTM ≈ 0.20-0.35Δ
PMCC_MAX_COST_RATIO = 0.80       # LEAPS cost < 80% of strike width
PMCC_MIN_OI         = 10
PMCC_MIN_QUALITY    = 30


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("daily-scan")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


def gather_watchlist(logger: logging.Logger) -> list[str]:
    """Collect the user's tickers — positions + decision queue. Deduplicate."""
    from src.sync import load_env
    from src import sheets as sh
    load_env()
    client = sh.authenticate()
    ss = sh._open_sheet(client)

    tickers: set[str] = set()
    for tab in ("positions_caspar", "positions_sarah"):
        try:
            rows = ss.worksheet(tab).get_all_values()
            if len(rows) > 1:
                headers = rows[0]
                data = [dict(zip(headers, r)) for r in rows[1:] if any(r)]
                latest_date = max(r.get("date", "") for r in data)
                for r in data:
                    if r.get("date") == latest_date and r.get("ticker"):
                        tickers.add(r["ticker"].strip().upper())
        except Exception as e:
            logger.warning(f"{tab}: {e}")

    # Decision queue
    try:
        rows = ss.worksheet("decision_queue").get_all_values()
        if len(rows) > 1:
            headers = rows[0]
            for r in rows[1:]:
                if not r:
                    continue
                row = dict(zip(headers, r))
                if row.get("ticker"):
                    tickers.add(row["ticker"].strip().upper())
    except Exception as e:
        logger.warning(f"decision_queue: {e}")

    # Gov confluence — pull in tickers with recent gov contract / congress
    # activity so the scan covers them even if not in portfolio/queue
    try:
        import datetime as _dt
        from src import schema as S
        ws_gc = ss.worksheet(S.GovConfluenceSignalRow.TAB_NAME)
        gc_rows = ws_gc.get_all_values()
        if len(gc_rows) > 1:
            gc_hdr = gc_rows[0]
            gc_cols = {h: i for i, h in enumerate(gc_hdr)}
            seven_d = (_dt.date.today() - _dt.timedelta(days=7)).isoformat()
            gov_added = 0
            for r in gc_rows[1:]:
                if len(r) <= gc_cols.get("date", 0) or r[gc_cols["date"]] < seven_d:
                    continue
                tk = r[gc_cols["ticker"]].strip().upper()
                if tk and tk not in tickers:
                    tickers.add(tk)
                    gov_added += 1
            if gov_added:
                logger.info(f"  +{gov_added} tickers from gov_confluence_signals")
    except Exception as e:
        logger.warning(f"gov_confluence_signals: {e}")

    # Screen candidates — pull in VCP/CANSLIM breakout tickers
    try:
        ws_sc = ss.worksheet(S.ScreenCandidateRow.TAB_NAME)
        sc_rows = ws_sc.get_all_values()
        if len(sc_rows) > 1:
            sc_hdr = sc_rows[0]
            sc_cols = {h: i for i, h in enumerate(sc_hdr)}
            seven_d2 = (_dt.date.today() - _dt.timedelta(days=7)).isoformat()
            sc_added = 0
            for r in sc_rows[1:]:
                sc_date = r[sc_cols.get("date", 0)] if sc_cols.get("date", 0) < len(r) else ""
                if sc_date < seven_d2:
                    continue
                try:
                    sc_score = float(r[sc_cols.get("score", 0)] if sc_cols.get("score", 0) < len(r) else 0)
                except (TypeError, ValueError):
                    sc_score = 0
                if sc_score < 60:
                    continue
                tk = (r[sc_cols.get("ticker", 0)] if sc_cols.get("ticker", 0) < len(r) else "").strip().upper()
                if tk and tk not in tickers:
                    tickers.add(tk)
                    sc_added += 1
            if sc_added:
                logger.info(f"  +{sc_added} tickers from screen_candidates (breakout triggers)")
    except Exception as e:
        logger.warning(f"screen_candidates: {e}")

    # Filter SGX-only tickers (yfinance needs .SI suffix and we don't write those to scan_results)
    SGX = {"C6L", "G3B", "D05", "O39", "U11", "Z74", "V03"}
    tickers = {t for t in tickers if t not in SGX and len(t) <= 5 and t.isalpha()}

    return sorted(tickers)


def _hv30(yt) -> float:
    """Legacy wrapper — use _technical_context() instead for new code."""
    ctx = _technical_context(yt)
    return ctx.get("hv30", 0.0)


# ── Support/Resistance Entry Timing ──────────────────────────────────
# Credit spreads are more profitable when entered at key technical levels:
#   PCS (bullish): price near support → bounce expected → put decay accelerates
#   CCS (bearish): price near resistance → rejection expected → call decay accelerates
# RSI confirmation layers on top: oversold + support = higher-conviction PCS.
#
# Support = 20-day rolling low (simple but effective for swing-range levels)
# Resistance = 20-day rolling high
# RSI-14 = standard Wilder calculation

SR_BONUS_NEAR_LEVEL = 15       # score bonus when price is within 3% of S/R
SR_BONUS_RSI_CONFIRM = 10      # additional bonus when RSI confirms
SR_PROXIMITY_PCT = 0.03        # "near" = within 3%
SR_RSI_OVERSOLD = 35           # PCS confirmation threshold
SR_RSI_OVERBOUGHT = 65         # CCS confirmation threshold
SR_IC_DUAL_BONUS = 8           # IC bonus when both sides have S/R context


def _technical_context(yt) -> dict:
    """
    Compute HV30, RSI-14, and 20d support/resistance from 60d daily data.

    Single yfinance fetch serves both the existing HV30 requirement and the
    new support/resistance entry timing. Returns dict with:
      hv30 (float %): 30-day historical volatility annualised
      rsi_14 (float): RSI-14, 0-100
      support (float): 20-day rolling low (price floor)
      resistance (float): 20-day rolling high (price ceiling)
    """
    try:
        hist = yt.history(period="60d", interval="1d", auto_adjust=True)
        if hist.empty or len(hist) < 20:
            return {"hv30": 0.0, "rsi_14": 50.0, "support": 0.0, "resistance": 0.0}

        closes = hist["Close"].dropna()
        if len(closes) < 20:
            return {"hv30": 0.0, "rsi_14": 50.0, "support": 0.0, "resistance": 0.0}

        # HV30 — same as legacy _hv30()
        log_rets = closes.pct_change().dropna().apply(lambda x: math.log(1 + x))
        hv30 = float(log_rets.std() * math.sqrt(252) * 100) if len(log_rets) > 5 else 0.0

        # RSI-14 (Wilder smoothing)
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta.where(delta < 0, 0.0))
        avg_gain = gain.rolling(14, min_periods=14).mean()
        avg_loss = loss.rolling(14, min_periods=14).mean()
        # Avoid division by zero
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        rsi_series = 100 - (100 / (1 + rs))
        rsi_14 = float(rsi_series.iloc[-1]) if len(rsi_series) >= 14 else 50.0
        if math.isnan(rsi_14):
            rsi_14 = 50.0

        # Support / Resistance — 20-day rolling low/high
        recent_20 = closes.iloc[-20:]
        support = float(recent_20.min())
        resistance = float(recent_20.max())

        return {
            "hv30": round(hv30, 1),
            "rsi_14": round(rsi_14, 1),
            "support": round(support, 2),
            "resistance": round(resistance, 2),
        }
    except Exception:
        return {"hv30": 0.0, "rsi_14": 50.0, "support": 0.0, "resistance": 0.0}


def _sr_bonus_pcs(price: float, ctx: dict) -> tuple[float, str]:
    """Score bonus for PCS when price is near support (bullish bounce expected)."""
    bonus = 0.0
    notes_parts: list[str] = []
    support = ctx.get("support", 0)
    rsi = ctx.get("rsi_14", 50)
    if support > 0 and price > 0:
        dist = (price - support) / price
        if 0 < dist <= SR_PROXIMITY_PCT:
            bonus += SR_BONUS_NEAR_LEVEL
            notes_parts.append(f"near support ${support:.0f} ({dist * 100:.1f}%)")
    if rsi < SR_RSI_OVERSOLD:
        bonus += SR_BONUS_RSI_CONFIRM
        notes_parts.append(f"RSI {rsi:.0f} oversold")
    return bonus, " · ".join(notes_parts)


def _sr_bonus_ccs(price: float, ctx: dict) -> tuple[float, str]:
    """Score bonus for CCS when price is near resistance (bearish rejection expected)."""
    bonus = 0.0
    notes_parts: list[str] = []
    resistance = ctx.get("resistance", 0)
    rsi = ctx.get("rsi_14", 50)
    if resistance > 0 and price > 0:
        dist = (resistance - price) / price
        if 0 < dist <= SR_PROXIMITY_PCT:
            bonus += SR_BONUS_NEAR_LEVEL
            notes_parts.append(f"near resistance ${resistance:.0f} ({dist * 100:.1f}%)")
    if rsi > SR_RSI_OVERBOUGHT:
        bonus += SR_BONUS_RSI_CONFIRM
        notes_parts.append(f"RSI {rsi:.0f} overbought")
    return bonus, " · ".join(notes_parts)


def _best_expiry(expiries: tuple[str, ...], dte_range: tuple[int, int] = (15, 50), target: int = TARGET_DTE) -> str | None:
    today = date.today()
    best: str | None = None
    best_diff = 9999
    for exp_str in expiries:
        try:
            exp = datetime.strptime(exp_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (exp - today).days
        if dte_range[0] <= dte <= dte_range[1]:
            diff = abs(dte - target)
            if diff < best_diff:
                best_diff = diff
                best = exp_str
    return best


def _option_mid(row) -> float:
    bid = float(row.get("bid", 0) or 0)
    ask = float(row.get("ask", 0) or 0)
    if bid > 0 or ask > 0:
        return (bid + ask) / 2
    return float(row.get("lastPrice", 0) or 0)


# ── Black-Scholes helpers ──────────────────────────────────────────
# yfinance doesn't return greeks and its impliedVolatility is garbage
# after hours (bid/ask=0 → can't solve). We compute delta and IV
# ourselves from option mid price using standard BSM.

_RISK_FREE = 0.043  # ~4.3% 10-yr yield as of mid-2026

def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erfc — no scipy dependency."""
    return 0.5 * math.erfc(-x / math.sqrt(2))

def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

def _bsm_price(S: float, K: float, T: float, sigma: float,
               right: str = "P", r: float = _RISK_FREE) -> float:
    """BSM European option price. right='P' or 'C'."""
    if T <= 0 or sigma <= 0:
        return max(0, (K - S) if right == "P" else (S - K))
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if right == "C":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    else:
        return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)

def _bsm_delta(S: float, K: float, T: float, sigma: float,
               right: str = "P", r: float = _RISK_FREE) -> float:
    """BSM delta. Returns negative for puts, positive for calls."""
    if T <= 0 or sigma <= 0:
        if right == "C":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    if right == "C":
        return _norm_cdf(d1)
    return _norm_cdf(d1) - 1.0

def _implied_vol(price: float, S: float, K: float, T: float,
                 right: str = "P", r: float = _RISK_FREE,
                 tol: float = 1e-5, max_iter: int = 50) -> float:
    """Newton-Raphson IV solver. Returns annualised vol (e.g. 0.35 = 35%).
    Falls back to 0.0 if unsolvable."""
    if price <= 0 or T <= 0 or S <= 0 or K <= 0:
        return 0.0
    # Intrinsic value check
    intrinsic = max(0, (K - S) if right == "P" else (S - K))
    if price <= intrinsic + tol:
        return 0.001  # deep ITM, near-zero extrinsic
    # Initial guess from Brenner-Subrahmanyam approximation
    sigma = math.sqrt(2 * math.pi / T) * price / S
    sigma = max(0.05, min(sigma, 5.0))
    for _ in range(max_iter):
        bp = _bsm_price(S, K, T, sigma, right, r)
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        vega = S * _norm_pdf(d1) * math.sqrt(T)
        if vega < 1e-12:
            break
        sigma -= (bp - price) / vega
        sigma = max(0.001, min(sigma, 10.0))
        if abs(bp - price) < tol:
            break
    return sigma if 0.001 < sigma < 10.0 else 0.0

def _compute_greeks(row, price: float, dte: int, right: str = "P") -> tuple[float, float]:
    """Compute (delta, iv_pct) for an option row using BSM.
    Returns (delta as -0.xx for puts / +0.xx for calls, iv as % e.g. 35.0)."""
    mid = _option_mid(row)
    K = float(row.get("strike", 0))
    T = dte / 365.0
    if mid <= 0 or K <= 0 or price <= 0 or T <= 0:
        return (0.0, 0.0)
    iv = _implied_vol(mid, price, K, T, right)
    delta = _bsm_delta(price, K, T, iv, right)
    return (round(delta, 4), round(iv * 100, 1))


def _estimate_ivr(iv_pct: float, hv30_pct: float) -> float:
    """IV Rank proxy from IV/HV ratio. Returns 0-100.

    True IV Rank needs 52-week IV data (IBKR has this); this heuristic
    uses the current IV vs realised vol ratio as a stand-in:
      ratio 1.0 → IVR ≈ 50, ratio 1.5 → IVR ≈ 75, ratio 0.7 → IVR ≈ 35
    """
    if hv30_pct <= 0:
        return 50.0  # neutral when HV unknown
    ratio = iv_pct / hv30_pct
    return max(0, min(100, 50 + (ratio - 1.0) * 50))


def _atm_iv(puts_df, calls_df, price: float, dte: int = 35) -> float:
    """ATM implied vol from near-the-money options using BSM solver.
    Returns % (e.g. 30.0). Ignores yfinance's broken impliedVolatility."""
    near = 0.05  # within 5% of price
    T = dte / 365.0
    ivs: list[float] = []
    for df, right in [(puts_df, "P"), (calls_df, "C")]:
        if df.empty:
            continue
        near_df = df[
            (df["strike"] >= price * (1 - near)) &
            (df["strike"] <= price * (1 + near))
        ]
        for _, row in near_df.iterrows():
            mid = _option_mid(row)
            K = float(row.get("strike", 0))
            if mid > 0 and K > 0 and T > 0:
                iv = _implied_vol(mid, price, K, T, right)
                if iv > 0.01:  # filter out unsolvable
                    ivs.append(iv)
    if ivs:
        return float(sum(ivs) / len(ivs)) * 100
    return 0.0


def _best_leaps_expiry(expiries: tuple[str, ...], min_dte: int = 270) -> str | None:
    """Find LEAPS expiry >= min_dte days out, closest to 365 days."""
    today = date.today()
    best: str | None = None
    best_diff = 9999
    for exp_str in expiries:
        try:
            exp = datetime.strptime(exp_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (exp - today).days
        if dte >= min_dte:
            diff = abs(dte - 365)
            if diff < best_diff:
                best_diff = diff
                best = exp_str
    return best


def _long_call_quality(
    fi, price: float, gov_info: dict, logger: logging.Logger, ticker: str,
) -> tuple[float, list[str]]:
    """Score a LONG_CALL opportunity on fundamentals + trend + multi-signal.

    Returns (quality_score, reasons).
    quality_score 0-100; only emit candidate if >= LC_MIN_QUALITY (40).

    Components (max 100):
      Contract materiality  (0-30): contract revenue relative to market cap
      Trend health          (0-30): price vs SMA50/SMA200 — don't buy calls
                                    into confirmed downtrends
      Multi-signal          (0-25): congress cluster buying, insider buying,
                                    or analyst upgrades confirming the thesis
      IV efficiency         (0-15): lower IV = cheaper calls = better entry
    """
    score = 0.0
    reasons: list[str] = []

    # ── Contract materiality ──────────────────────────────────────────
    market_cap = 0.0
    sma50 = None
    sma200 = None
    try:
        market_cap = float(fi.market_cap or 0)
    except Exception:
        pass

    # Extract contract $ from thesis_oneliner if we have it, otherwise
    # assume the contract_score alone tells us "something is there."
    contract_score = float(gov_info.get("contract_score", 0))
    if market_cap > 0 and contract_score > 0:
        # contract_score is 0-100 from the screener (100 = massive).
        # Approximate: score 100 ≈ contracts > 5% of market cap,
        # score 50 ≈ ~1%, score 20 ≈ ~0.2%.  We use it as a proxy.
        if contract_score >= 80:
            score += 30
            reasons.append(f"contract_score={contract_score:.0f} (massive vs ${market_cap/1e9:.1f}B mktcap)")
        elif contract_score >= 50:
            score += 20
            reasons.append(f"contract_score={contract_score:.0f} (significant)")
        elif contract_score >= 20:
            score += 10
            reasons.append(f"contract_score={contract_score:.0f} (notable)")
        else:
            reasons.append(f"contract_score={contract_score:.0f} (minor)")
    elif contract_score > 0:
        # No market cap data — give partial credit
        score += min(contract_score / 5, 15)
        reasons.append(f"contract_score={contract_score:.0f} (mktcap unknown)")

    # ── Trend health ──────────────────────────────────────────────────
    try:
        sma50 = float(fi.fifty_day_average or 0)
        sma200 = float(fi.two_hundred_day_average or 0)
    except Exception:
        pass

    if sma50 and sma50 > 0:
        if price > sma50:
            score += 15
            reasons.append(f"above SMA50 ${sma50:.0f}")
        else:
            pct_below = (sma50 - price) / sma50 * 100
            score -= min(pct_below, 10)  # penalty up to -10
            reasons.append(f"BELOW SMA50 ${sma50:.0f} by {pct_below:.0f}%")

    if sma200 and sma200 > 0:
        if price > sma200:
            score += 15
            reasons.append(f"above SMA200 ${sma200:.0f}")
        else:
            pct_below = (sma200 - price) / sma200 * 100
            score -= min(pct_below, 15)  # heavier penalty
            reasons.append(f"BELOW SMA200 ${sma200:.0f} by {pct_below:.0f}%")

    # ── Multi-signal confirmation ─────────────────────────────────────
    congress = float(gov_info.get("congress_score", 0))
    insider = float(gov_info.get("insider_score", 0))
    analyst = float(gov_info.get("analyst_score", 0))

    if congress >= 30:
        score += 15
        reasons.append(f"congress cluster buying (score={congress:.0f})")
    elif congress >= 10:
        score += 5
        reasons.append(f"congress activity (score={congress:.0f})")

    if insider >= 20:
        score += 10
        reasons.append(f"insider buying (score={insider:.0f})")

    if analyst >= 20:
        score += 5

    # Contract-only signal with no confirming signals = weaker
    if congress == 0 and insider == 0 and analyst == 0:
        score -= 5
        reasons.append("contract-only (no confirming signals)")

    # ── IV efficiency ─────────────────────────────────────────────────
    # Lower IV = cheaper premium = better risk/reward for directional.
    # We don't have IV rank in gov_info yet, but the caller can add it.
    # For now, give +5 baseline (assume neutral) — deducted in scan if
    # IVR is extremely high.

    logger.debug(f"  {ticker}: LONG_CALL quality={score:.0f} — {'; '.join(reasons)}")
    return score, reasons


def scan_ticker(
    ticker: str,
    logger: logging.Logger,
    gov_info: dict | None = None,
    insider_info: dict | None = None,
    screen_info: dict | None = None,
) -> list[dict[str, Any]]:
    """Return CSP + CC + LONG_CALL candidates for a single ticker.

    LONG_CALL triggers (any one sufficient, quality-gated to >= 40):
      1. gov_info: gov confluence score >= 30 + not TRIM
      2. insider_info: cluster insider buying >= $500K in last 14 days
      3. screen_info: VCP/CANSLIM breakout candidate with score >= 60

    gov_info: dict from gov_confluence_signals {score, tier, strategy,
        contract_score, congress_score, insider_score, analyst_score}
    insider_info: dict {buy_value, buy_count, sell_value} — aggregated
        insider transactions for this ticker over last 14 days
    screen_info: dict {source, score, trigger_price, rationale} — from
        screen_candidates if this ticker passed VCP/CANSLIM screen
    """
    import yfinance as yf
    try:
        yt = yf.Ticker(ticker)
        fi = yt.fast_info
        price = float(fi.last_price or 0)
    except Exception as e:
        logger.debug(f"  {ticker}: price fail — {e}")
        return []
    if price < MIN_PRICE or price > MAX_PRICE:
        return []

    try:
        expiries = yt.options
    except Exception:
        return []
    expiry = _best_expiry(expiries)
    if not expiry:
        return []

    today = date.today()
    dte = (datetime.strptime(expiry, "%Y-%m-%d").date() - today).days
    expiry_iso = expiry.replace("-", "")  # YYYYMMDD

    try:
        chain = yt.option_chain(expiry)
    except Exception:
        return []

    tech_ctx = _technical_context(yt)
    hv30 = tech_ctx["hv30"]
    out: list[dict[str, Any]] = []

    # ── CSP ────────────────────────────────────────────────────────────────
    try:
        puts = chain.puts.copy()
        puts = puts[puts["openInterest"] >= MIN_OI]
        puts["mid"] = puts.apply(_option_mid, axis=1)
        puts = puts[puts["mid"] >= MIN_MID]
        # Strike 2-18% OTM (below price)
        puts = puts[(puts["strike"] >= price * (1 - CSP_OTM_RANGE[1])) &
                    (puts["strike"] <= price * (1 - CSP_OTM_RANGE[0]))]
        puts = puts.copy()
        puts["ann_yield"] = puts["mid"] / puts["strike"] * (365 / dte) * 100
        puts = puts[puts["ann_yield"] >= MIN_CSP_YIELD]
        puts = puts.sort_values("ann_yield", ascending=False)
        if not puts.empty:
            r = puts.iloc[0]
            spread_pct = 0.0
            bid = float(r.get("bid", 0) or 0)
            ask = float(r.get("ask", 0) or 0)
            mid = float(r["mid"])
            if mid > 0 and bid > 0 and ask > 0:
                spread_pct = (ask - bid) / mid * 100
            csp_delta, csp_iv = _compute_greeks(r, price, dte, "P")
            csp_ivr = _estimate_ivr(csp_iv, hv30)
            out.append({
                "ticker": ticker,
                "strategy": "CSP",
                "right": "P",
                "strike": float(r["strike"]),
                "expiry": expiry_iso,
                "dte": dte,
                "delta": csp_delta,
                "premium": round(mid, 2),
                "bid": round(bid, 2),
                "ask": round(ask, 2),
                "annual_yield_pct": round(float(r["ann_yield"]), 2),
                "cash_required": round(float(r["strike"]) * 100, 2),
                "breakeven": round(float(r["strike"]) - mid, 2),
                "iv": csp_iv,
                "iv_rank": round(csp_ivr, 1),
                "spread_pct": round(spread_pct, 2),
                "underlying_last": round(price, 2),
                "technical_score": 0.0,
                "composite_score": round(float(r["ann_yield"]), 2),
                "catalyst_flag": False,
                "hv30": round(hv30, 1),
                "notes": "",
            })
    except Exception as e:
        logger.debug(f"  {ticker}: CSP error — {e}")

    # ── CC ─────────────────────────────────────────────────────────────────
    try:
        calls = chain.calls.copy()
        calls = calls[calls["openInterest"] >= MIN_OI]
        calls["mid"] = calls.apply(_option_mid, axis=1)
        calls = calls[calls["mid"] >= MIN_MID]
        # Strike 1-10% OTM (above price)
        calls = calls[(calls["strike"] >= price * (1 + CC_OTM_RANGE[0])) &
                      (calls["strike"] <= price * (1 + CC_OTM_RANGE[1]))]
        calls = calls.copy()
        calls["ann_yield"] = calls["mid"] / price * (365 / dte) * 100
        calls = calls[calls["ann_yield"] >= MIN_CC_YIELD]
        calls = calls.sort_values("ann_yield", ascending=False)
        if not calls.empty:
            r = calls.iloc[0]
            bid = float(r.get("bid", 0) or 0)
            ask = float(r.get("ask", 0) or 0)
            mid = float(r["mid"])
            spread_pct = 0.0
            if mid > 0 and bid > 0 and ask > 0:
                spread_pct = (ask - bid) / mid * 100
            cc_delta, cc_iv = _compute_greeks(r, price, dte, "C")
            cc_ivr = _estimate_ivr(cc_iv, hv30)
            out.append({
                "ticker": ticker,
                "strategy": "CC",
                "right": "C",
                "strike": float(r["strike"]),
                "expiry": expiry_iso,
                "dte": dte,
                "delta": cc_delta,
                "premium": round(mid, 2),
                "bid": round(bid, 2),
                "ask": round(ask, 2),
                "annual_yield_pct": round(float(r["ann_yield"]), 2),
                "cash_required": round(price * 100, 2),
                "breakeven": round(price - mid, 2),
                "iv": cc_iv,
                "iv_rank": round(cc_ivr, 1),
                "spread_pct": round(spread_pct, 2),
                "underlying_last": round(price, 2),
                "technical_score": 0.0,
                "composite_score": round(float(r["ann_yield"]), 2),
                "catalyst_flag": False,
                "hv30": round(hv30, 1),
                "notes": "",
            })
    except Exception as e:
        logger.debug(f"  {ticker}: CC error — {e}")

    # ── LONG_CALL — quality-gated directional plays ─────────────────
    # Multiple triggers can fire LONG_CALL scanning (any one sufficient):
    #   1. Gov confluence: score >= 30 + not TRIM → contract catalyst
    #   2. Insider cluster buying: >= $500K net buying last 14d
    #   3. Technical breakout: VCP/CANSLIM screen candidate score >= 60
    # All paths still quality-gated to LC_MIN_QUALITY (40) before
    # emitting a candidate — trend health, multi-signal, IV checked.
    gov_bullish = (
        gov_info is not None
        and gov_info.get("score", 0) >= 30
        and gov_info.get("strategy", "") != "TRIM"
    )
    insider_bullish = (
        insider_info is not None
        and float(insider_info.get("buy_value", 0)) >= 500_000
        and float(insider_info.get("buy_value", 0)) > float(insider_info.get("sell_value", 0)) * 2
    )
    breakout_bullish = (
        screen_info is not None
        and float(screen_info.get("score", 0)) >= 60
    )
    lc_trigger = gov_bullish or insider_bullish or breakout_bullish

    if lc_trigger:
        # Build a synthetic gov_info for quality scoring when the trigger
        # is insider or breakout (non-gov sources). The quality function
        # uses gov sub-scores for multi-signal confirmation.
        lc_gov = gov_info or {}
        if not gov_bullish and insider_bullish:
            # Insider-driven: inject insider score so quality function sees it
            lc_gov = {
                "score": 0, "contract_score": 0, "congress_score": 0,
                "insider_score": min(100, float(insider_info.get("buy_value", 0)) / 10_000),
                "analyst_score": 0, "tier": "", "strategy": "",
            }
            logger.info(f"  {ticker}: LONG_CALL trigger — insider cluster ${insider_info.get('buy_value', 0)/1e3:.0f}K buying")
        elif not gov_bullish and breakout_bullish:
            # Breakout-driven: inject trend score
            lc_gov = {
                "score": 0, "contract_score": 0, "congress_score": 0,
                "insider_score": 0, "analyst_score": 0, "tier": "", "strategy": "",
            }
            logger.info(f"  {ticker}: LONG_CALL trigger — {screen_info.get('source', 'screen')} breakout (score={screen_info.get('score', 0)})")
        # Quality gate BEFORE option chain fetch (saves API calls)
        lc_quality, lc_reasons = _long_call_quality(fi, price, lc_gov, logger, ticker)

        # Breakout bonus: VCP/CANSLIM candidates get a trend-confirmation
        # boost since the screen already validated the setup.
        if breakout_bullish:
            breakout_bonus = min(20, float(screen_info.get("score", 0)) / 5)
            lc_quality += breakout_bonus
            lc_reasons.append(f"breakout bonus +{breakout_bonus:.0f} ({screen_info.get('source', 'screen')})")
        if lc_quality < LC_MIN_QUALITY:
            logger.info(
                f"  {ticker}: LONG_CALL skipped (quality={lc_quality:.0f} < {LC_MIN_QUALITY}) — "
                + "; ".join(lc_reasons)
            )
        else:
            try:
                lc_expiry = _best_expiry(expiries, dte_range=LC_DTE_RANGE, target=LC_TARGET_DTE)
                if lc_expiry and lc_expiry != expiry:
                    lc_chain = yt.option_chain(lc_expiry)
                    lc_dte = (datetime.strptime(lc_expiry, "%Y-%m-%d").date() - today).days
                    lc_expiry_iso = lc_expiry.replace("-", "")
                else:
                    lc_chain = chain
                    lc_dte = dte
                    lc_expiry_iso = expiry_iso

                calls = lc_chain.calls.copy()
                calls = calls[calls["openInterest"] >= LC_MIN_OI]
                calls["mid"] = calls.apply(_option_mid, axis=1)
                calls = calls[calls["mid"] >= MIN_MID]
                # Filter for delta range (ATM-ish)
                if "delta" in calls.columns:
                    calls = calls.copy()
                    calls["abs_delta"] = calls["delta"].abs()
                    calls = calls[
                        (calls["abs_delta"] >= LC_DELTA_RANGE[0]) &
                        (calls["abs_delta"] <= LC_DELTA_RANGE[1])
                    ]
                else:
                    # No delta column — approximate via moneyness
                    calls = calls[
                        (calls["strike"] >= price * 0.95) &
                        (calls["strike"] <= price * 1.10)
                    ]
                # Cap premium at 5% of underlying (don't overpay)
                calls = calls[calls["mid"] <= price * LC_MAX_PREMIUM_PCT]

                if not calls.empty:
                    # Pick the call closest to 0.50 delta (or closest to ATM)
                    if "abs_delta" in calls.columns:
                        calls = calls.copy()
                        calls["delta_dist"] = (calls["abs_delta"] - 0.50).abs()
                        best = calls.sort_values("delta_dist").iloc[0]
                    else:
                        calls = calls.copy()
                        calls["moneyness"] = (calls["strike"] / price - 1.0).abs()
                        best = calls.sort_values("moneyness").iloc[0]

                    r = best
                    bid = float(r.get("bid", 0) or 0)
                    ask = float(r.get("ask", 0) or 0)
                    mid = float(r["mid"])
                    spread_pct = 0.0
                    if mid > 0 and bid > 0 and ask > 0:
                        spread_pct = (ask - bid) / mid * 100

                    # Compute a meaningful technical_score from SMA/trend data
                    trend_score = 0.0
                    try:
                        sma50 = float(fi.fifty_day_average or 0)
                        sma200 = float(fi.two_hundred_day_average or 0)
                        if sma50 > 0 and price > sma50:
                            trend_score += 25
                        elif sma50 > 0:
                            trend_score -= 25
                        if sma200 > 0 and price > sma200:
                            trend_score += 25
                        elif sma200 > 0:
                            trend_score -= 25
                    except Exception:
                        pass

                    lc_delta, lc_iv = _compute_greeks(r, price, lc_dte, "C")
                    lc_ivr = _estimate_ivr(lc_iv, hv30)
                    out.append({
                        "ticker": ticker,
                        "strategy": "LONG_CALL",
                        "right": "C",
                        "strike": float(r["strike"]),
                        "expiry": lc_expiry_iso,
                        "dte": lc_dte,
                        "delta": lc_delta,
                        "premium": round(mid, 2),
                        "bid": round(bid, 2),
                        "ask": round(ask, 2),
                        "annual_yield_pct": 0.0,  # N/A for directional
                        "cash_required": round(mid * 100, 2),  # premium × 100
                        "breakeven": round(float(r["strike"]) + mid, 2),
                        "iv": lc_iv,
                        "iv_rank": round(lc_ivr, 1),
                        "spread_pct": round(spread_pct, 2),
                        "underlying_last": round(price, 2),
                        "technical_score": round(trend_score, 1),
                        "composite_score": round(lc_quality, 1),
                        "catalyst_flag": True,
                        "hv30": round(hv30, 1),
                        "notes": "",
                    })
                    logger.info(
                        f"  {ticker}: LONG_CALL quality={lc_quality:.0f} "
                        f"${r['strike']}C exp {lc_expiry_iso} "
                        f"trend={trend_score:+.0f} — {'; '.join(lc_reasons)}"
                    )
            except Exception as e:
                logger.debug(f"  {ticker}: LONG_CALL error — {e}")

    # ── IRON CONDOR — neutral range-bound play ──────────────────────
    # Tastytrade: ~20Δ short strikes, $5-$10 wings, 45 DTE,
    # IVR > 40 (proxy), credit/width ≥ 30%, manage at 50% profit.
    try:
        ic_expiry = _best_expiry(expiries, dte_range=IC_DTE_RANGE, target=IC_TARGET_DTE)
        if ic_expiry:
            ic_dte = (datetime.strptime(ic_expiry, "%Y-%m-%d").date() - today).days
            ic_expiry_iso = ic_expiry.replace("-", "")
            ic_chain = chain if ic_expiry == expiry else yt.option_chain(ic_expiry)

            ic_puts = ic_chain.puts.copy()
            ic_calls = ic_chain.calls.copy()
            ic_puts["mid"] = ic_puts.apply(_option_mid, axis=1)
            ic_calls["mid"] = ic_calls.apply(_option_mid, axis=1)
            ic_puts = ic_puts[(ic_puts["openInterest"] >= IC_MIN_OI) & (ic_puts["mid"] >= MIN_MID)]
            ic_calls = ic_calls[(ic_calls["openInterest"] >= IC_MIN_OI) & (ic_calls["mid"] >= MIN_MID)]

            atm_iv_ic = _atm_iv(ic_puts, ic_calls, price, ic_dte)
            est_ivr_ic = _estimate_ivr(atm_iv_ic, hv30)

            if est_ivr_ic >= IC_MIN_IVR and not ic_puts.empty and not ic_calls.empty:
                # Short put: 7-16% below price (~15-25Δ)
                sp_cands = ic_puts[
                    (ic_puts["strike"] >= price * (1 - IC_OTM_RANGE[1])) &
                    (ic_puts["strike"] <= price * (1 - IC_OTM_RANGE[0]))
                ]
                # Short call: 7-16% above price
                sc_cands = ic_calls[
                    (ic_calls["strike"] >= price * (1 + IC_OTM_RANGE[0])) &
                    (ic_calls["strike"] <= price * (1 + IC_OTM_RANGE[1]))
                ]

                if not sp_cands.empty and not sc_cands.empty:
                    short_put = sp_cands.sort_values("mid", ascending=False).iloc[0]
                    short_call = sc_cands.sort_values("mid", ascending=False).iloc[0]
                    sp_strike = float(short_put["strike"])
                    sc_strike = float(short_call["strike"])
                    sp_mid = float(short_put["mid"])
                    sc_mid = float(short_call["mid"])

                    for wing_w in IC_WING_WIDTHS:
                        lp_target = sp_strike - wing_w
                        lp_near = ic_puts[(ic_puts["strike"] - lp_target).abs() <= wing_w * 0.4]
                        if lp_near.empty:
                            continue
                        long_put = lp_near.loc[(lp_near["strike"] - lp_target).abs().idxmin()]

                        lc_target = sc_strike + wing_w
                        lc_near = ic_calls[(ic_calls["strike"] - lc_target).abs() <= wing_w * 0.4]
                        if lc_near.empty:
                            continue
                        long_call = lc_near.loc[(lc_near["strike"] - lc_target).abs().idxmin()]

                        lp_mid = _option_mid(long_put)
                        lc_mid = _option_mid(long_call)
                        net_credit = (sp_mid + sc_mid) - (lp_mid + lc_mid)
                        actual_width = max(
                            sp_strike - float(long_put["strike"]),
                            float(long_call["strike"]) - sc_strike,
                        )
                        if actual_width <= 0 or net_credit <= 0:
                            continue
                        credit_ratio = net_credit / actual_width

                        if credit_ratio >= IC_MIN_CREDIT_RATIO:
                            max_risk = actual_width - net_credit
                            ann_yield = (net_credit / max_risk) * (365 / ic_dte) * 100 if max_risk > 0 else 0
                            ic_score = min(100, credit_ratio * 120 + min(est_ivr_ic, 100) * 0.25 + (10 if ann_yield >= 25 else 0))

                            # IC S/R bonus: check both put-side (near support)
                            # and call-side (near resistance) context
                            ic_sr_bonus_put, ic_sr_note_put = _sr_bonus_pcs(price, tech_ctx)
                            ic_sr_bonus_call, ic_sr_note_call = _sr_bonus_ccs(price, tech_ctx)
                            if ic_sr_bonus_put > 0 and ic_sr_bonus_call > 0:
                                ic_score += SR_IC_DUAL_BONUS  # both sides have S/R context
                            elif ic_sr_bonus_put > 0 or ic_sr_bonus_call > 0:
                                ic_score += max(ic_sr_bonus_put, ic_sr_bonus_call) * 0.4  # partial credit

                            if ic_score >= IC_MIN_QUALITY:
                                lp_s = float(long_put["strike"])
                                lc_s = float(long_call["strike"])
                                notes = (
                                    f"SP:{sp_strike:.0f}/LP:{lp_s:.0f}"
                                    f"/SC:{sc_strike:.0f}/LC:{lc_s:.0f}"
                                    f" W:${actual_width:.0f}"
                                )
                                ic_sr_parts = [n for n in [ic_sr_note_put, ic_sr_note_call] if n]
                                if ic_sr_parts:
                                    notes += f" [{' | '.join(ic_sr_parts)}]"
                                out.append({
                                    "ticker": ticker, "strategy": "IC", "right": "",
                                    "strike": sp_strike, "expiry": ic_expiry_iso,
                                    "dte": ic_dte, "delta": 0.0,
                                    "premium": round(net_credit, 2),
                                    "bid": 0.0, "ask": 0.0,
                                    "annual_yield_pct": round(ann_yield, 2),
                                    "cash_required": round(max_risk * 100, 2),
                                    "breakeven": round(sp_strike - net_credit, 2),
                                    "iv": round(atm_iv_ic, 1),
                                    "iv_rank": round(est_ivr_ic, 1),
                                    "spread_pct": 0.0,
                                    "underlying_last": round(price, 2),
                                    "technical_score": 0.0,
                                    "composite_score": round(ic_score, 1),
                                    "catalyst_flag": False,
                                    "hv30": round(hv30, 1),
                                    "notes": notes,
                                })
                                logger.info(
                                    f"  ✓ {ticker:6} IC   {notes}  "
                                    f"{ic_dte}DTE  credit=${net_credit:.2f}  "
                                    f"ratio={credit_ratio:.0%}  IVR≈{est_ivr_ic:.0f}"
                                )
                                break  # prefer narrower wings
    except Exception as e:
        logger.debug(f"  {ticker}: IC error — {e}")

    # ── PUT CREDIT SPREAD — bullish directional ─────────────────────
    # Tastytrade: 20-30Δ short put, $5-$10 wings, 35-49 DTE,
    # credit ≥ 1/3 width, IVR ≥ 25, manage at 50% profit.
    try:
        cs_expiry = _best_expiry(expiries, dte_range=CS_DTE_RANGE, target=CS_TARGET_DTE)
        if cs_expiry:
            cs_dte = (datetime.strptime(cs_expiry, "%Y-%m-%d").date() - today).days
            cs_expiry_iso = cs_expiry.replace("-", "")
            cs_chain = chain if cs_expiry == expiry else yt.option_chain(cs_expiry)

            cs_puts = cs_chain.puts.copy()
            cs_calls_for_iv = cs_chain.calls.copy()
            cs_puts["mid"] = cs_puts.apply(_option_mid, axis=1)
            cs_puts = cs_puts[(cs_puts["openInterest"] >= CS_MIN_OI) & (cs_puts["mid"] >= MIN_MID)]

            atm_iv_cs = _atm_iv(cs_puts, cs_calls_for_iv, price, cs_dte)
            est_ivr_cs = _estimate_ivr(atm_iv_cs, hv30)

            if est_ivr_cs >= CS_MIN_IVR and not cs_puts.empty:
                sp_cands = cs_puts[
                    (cs_puts["strike"] >= price * (1 - CS_OTM_RANGE[1])) &
                    (cs_puts["strike"] <= price * (1 - CS_OTM_RANGE[0]))
                ]
                if not sp_cands.empty:
                    short_put = sp_cands.sort_values("mid", ascending=False).iloc[0]
                    sp_strike = float(short_put["strike"])
                    sp_mid = float(short_put["mid"])

                    for wing_w in CS_WING_WIDTHS:
                        lp_target = sp_strike - wing_w
                        lp_near = cs_puts[(cs_puts["strike"] - lp_target).abs() <= wing_w * 0.4]
                        if lp_near.empty:
                            continue
                        long_put = lp_near.loc[(lp_near["strike"] - lp_target).abs().idxmin()]
                        lp_mid = _option_mid(long_put)
                        actual_width = sp_strike - float(long_put["strike"])
                        net_credit = sp_mid - lp_mid

                        if actual_width <= 0 or net_credit <= 0:
                            continue
                        credit_ratio = net_credit / actual_width
                        if credit_ratio >= CS_MIN_CREDIT_RATIO:
                            max_risk = actual_width - net_credit
                            ann_yield = (net_credit / max_risk) * (365 / cs_dte) * 100 if max_risk > 0 else 0
                            pcs_score = min(100, credit_ratio * 100 + min(est_ivr_cs, 100) * 0.2 + (15 if ann_yield >= 20 else 0))

                            # Support/resistance entry timing bonus
                            sr_bonus, sr_note = _sr_bonus_pcs(price, tech_ctx)
                            pcs_score += sr_bonus

                            if pcs_score >= CS_MIN_QUALITY:
                                lp_s = float(long_put["strike"])
                                notes = f"SP:{sp_strike:.0f}/LP:{lp_s:.0f} W:${actual_width:.0f}"
                                if sr_note:
                                    notes += f" [{sr_note}]"
                                pcs_delta, _ = _compute_greeks(short_put, price, cs_dte, "P")
                                out.append({
                                    "ticker": ticker, "strategy": "PCS", "right": "P",
                                    "strike": sp_strike, "expiry": cs_expiry_iso,
                                    "dte": cs_dte,
                                    "delta": pcs_delta,
                                    "premium": round(net_credit, 2),
                                    "bid": 0.0, "ask": 0.0,
                                    "annual_yield_pct": round(ann_yield, 2),
                                    "cash_required": round(max_risk * 100, 2),
                                    "breakeven": round(sp_strike - net_credit, 2),
                                    "iv": round(atm_iv_cs, 1),
                                    "iv_rank": round(est_ivr_cs, 1),
                                    "spread_pct": 0.0,
                                    "underlying_last": round(price, 2),
                                    "technical_score": 0.0,
                                    "composite_score": round(pcs_score, 1),
                                    "catalyst_flag": False,
                                    "hv30": round(hv30, 1),
                                    "notes": notes,
                                })
                                logger.info(
                                    f"  ✓ {ticker:6} PCS  {notes}  "
                                    f"{cs_dte}DTE  credit=${net_credit:.2f}  "
                                    f"ratio={credit_ratio:.0%}  IVR≈{est_ivr_cs:.0f}"
                                )
                                break
    except Exception as e:
        logger.debug(f"  {ticker}: PCS error — {e}")

    # ── CALL CREDIT SPREAD — bearish directional ────────────────────
    # Mirror of PCS on the call side. Same tastytrade criteria.
    try:
        # Reuse cs_expiry/cs_chain if already fetched, else fetch
        ccs_expiry = _best_expiry(expiries, dte_range=CS_DTE_RANGE, target=CS_TARGET_DTE)
        if ccs_expiry:
            ccs_dte = (datetime.strptime(ccs_expiry, "%Y-%m-%d").date() - today).days
            ccs_expiry_iso = ccs_expiry.replace("-", "")
            ccs_chain = chain if ccs_expiry == expiry else yt.option_chain(ccs_expiry)

            ccs_calls = ccs_chain.calls.copy()
            ccs_puts_for_iv = ccs_chain.puts.copy()
            ccs_calls["mid"] = ccs_calls.apply(_option_mid, axis=1)
            ccs_calls = ccs_calls[(ccs_calls["openInterest"] >= CS_MIN_OI) & (ccs_calls["mid"] >= MIN_MID)]

            atm_iv_ccs = _atm_iv(ccs_puts_for_iv, ccs_calls, price, ccs_dte)
            est_ivr_ccs = _estimate_ivr(atm_iv_ccs, hv30)

            if est_ivr_ccs >= CS_MIN_IVR and not ccs_calls.empty:
                sc_cands = ccs_calls[
                    (ccs_calls["strike"] >= price * (1 + CS_OTM_RANGE[0])) &
                    (ccs_calls["strike"] <= price * (1 + CS_OTM_RANGE[1]))
                ]
                if not sc_cands.empty:
                    short_call = sc_cands.sort_values("mid", ascending=False).iloc[0]
                    sc_strike = float(short_call["strike"])
                    sc_mid = float(short_call["mid"])

                    for wing_w in CS_WING_WIDTHS:
                        lc_target = sc_strike + wing_w
                        lc_near = ccs_calls[(ccs_calls["strike"] - lc_target).abs() <= wing_w * 0.4]
                        if lc_near.empty:
                            continue
                        long_call = lc_near.loc[(lc_near["strike"] - lc_target).abs().idxmin()]
                        lc_mid = _option_mid(long_call)
                        actual_width = float(long_call["strike"]) - sc_strike
                        net_credit = sc_mid - lc_mid

                        if actual_width <= 0 or net_credit <= 0:
                            continue
                        credit_ratio = net_credit / actual_width
                        if credit_ratio >= CS_MIN_CREDIT_RATIO:
                            max_risk = actual_width - net_credit
                            ann_yield = (net_credit / max_risk) * (365 / ccs_dte) * 100 if max_risk > 0 else 0
                            ccs_score = min(100, credit_ratio * 100 + min(est_ivr_ccs, 100) * 0.2 + (15 if ann_yield >= 20 else 0))

                            # Support/resistance entry timing bonus
                            sr_bonus, sr_note = _sr_bonus_ccs(price, tech_ctx)
                            ccs_score += sr_bonus

                            if ccs_score >= CS_MIN_QUALITY:
                                lc_s = float(long_call["strike"])
                                notes = f"SC:{sc_strike:.0f}/LC:{lc_s:.0f} W:${actual_width:.0f}"
                                if sr_note:
                                    notes += f" [{sr_note}]"
                                ccs_delta, _ = _compute_greeks(short_call, price, ccs_dte, "C")
                                out.append({
                                    "ticker": ticker, "strategy": "CCS", "right": "C",
                                    "strike": sc_strike, "expiry": ccs_expiry_iso,
                                    "dte": ccs_dte,
                                    "delta": ccs_delta,
                                    "premium": round(net_credit, 2),
                                    "bid": 0.0, "ask": 0.0,
                                    "annual_yield_pct": round(ann_yield, 2),
                                    "cash_required": round(max_risk * 100, 2),
                                    "breakeven": round(sc_strike + net_credit, 2),
                                    "iv": round(atm_iv_ccs, 1),
                                    "iv_rank": round(est_ivr_ccs, 1),
                                    "spread_pct": 0.0,
                                    "underlying_last": round(price, 2),
                                    "technical_score": 0.0,
                                    "composite_score": round(ccs_score, 1),
                                    "catalyst_flag": False,
                                    "hv30": round(hv30, 1),
                                    "notes": notes,
                                })
                                logger.info(
                                    f"  ✓ {ticker:6} CCS  {notes}  "
                                    f"{ccs_dte}DTE  credit=${net_credit:.2f}  "
                                    f"ratio={credit_ratio:.0%}  IVR≈{est_ivr_ccs:.0f}"
                                )
                                break
    except Exception as e:
        logger.debug(f"  {ticker}: CCS error — {e}")

    # ── PMCC — Poor Man's Covered Call (diagonal spread) ────────────
    # Tastytrade: LEAPS 0.70-0.80Δ ITM 9+ months, short call 0.20-0.30Δ
    # OTM 30-45 DTE, LEAPS cost < 80% strike width.
    try:
        leaps_expiry = _best_leaps_expiry(expiries, min_dte=PMCC_LEAPS_MIN_DTE)
        pmcc_short_expiry = _best_expiry(expiries, dte_range=PMCC_SHORT_DTE_RANGE, target=CS_TARGET_DTE)
        if leaps_expiry and pmcc_short_expiry and leaps_expiry != pmcc_short_expiry:
            leaps_dte = (datetime.strptime(leaps_expiry, "%Y-%m-%d").date() - today).days
            pmcc_s_dte = (datetime.strptime(pmcc_short_expiry, "%Y-%m-%d").date() - today).days
            leaps_chain = yt.option_chain(leaps_expiry)
            pmcc_s_chain = chain if pmcc_short_expiry == expiry else yt.option_chain(pmcc_short_expiry)

            leaps_calls = leaps_chain.calls.copy()
            leaps_calls["mid"] = leaps_calls.apply(_option_mid, axis=1)
            leaps_calls = leaps_calls[(leaps_calls["openInterest"] >= PMCC_MIN_OI) & (leaps_calls["mid"] >= MIN_MID)]

            pmcc_short_calls = pmcc_s_chain.calls.copy()
            pmcc_short_calls["mid"] = pmcc_short_calls.apply(_option_mid, axis=1)
            pmcc_short_calls = pmcc_short_calls[(pmcc_short_calls["openInterest"] >= PMCC_MIN_OI) & (pmcc_short_calls["mid"] >= MIN_MID)]

            if not leaps_calls.empty and not pmcc_short_calls.empty:
                # LEAPS: 5-20% ITM (strike below current price)
                leaps_cands = leaps_calls[
                    (leaps_calls["strike"] >= price * (1 - PMCC_LEAPS_ITM[1])) &
                    (leaps_calls["strike"] <= price * (1 - PMCC_LEAPS_ITM[0]))
                ]
                # Short call: 4-12% OTM (above price)
                pmcc_sc_cands = pmcc_short_calls[
                    (pmcc_short_calls["strike"] >= price * (1 + PMCC_SHORT_OTM[0])) &
                    (pmcc_short_calls["strike"] <= price * (1 + PMCC_SHORT_OTM[1]))
                ]

                if not leaps_cands.empty and not pmcc_sc_cands.empty:
                    # LEAPS: pick closest to 10% ITM
                    leaps_cands = leaps_cands.copy()
                    leaps_cands["itm_dist"] = (1 - leaps_cands["strike"] / price - 0.10).abs()
                    leaps_call = leaps_cands.sort_values("itm_dist").iloc[0]
                    leaps_strike = float(leaps_call["strike"])
                    leaps_mid = float(leaps_call["mid"])

                    # Short call: pick closest to 8% OTM
                    pmcc_sc_cands = pmcc_sc_cands.copy()
                    pmcc_sc_cands["otm_dist"] = (pmcc_sc_cands["strike"] / price - 1.0 - 0.08).abs()
                    pmcc_short = pmcc_sc_cands.sort_values("otm_dist").iloc[0]
                    pmcc_sc_strike = float(pmcc_short["strike"])
                    pmcc_sc_mid = float(pmcc_short["mid"])

                    strike_width = pmcc_sc_strike - leaps_strike
                    if strike_width > 0 and leaps_mid > 0:
                        cost_ratio = leaps_mid / strike_width
                        if cost_ratio <= PMCC_MAX_COST_RATIO:
                            monthly_yield = (pmcc_sc_mid / leaps_mid) * (30 / pmcc_s_dte) * 100
                            ann_yield = monthly_yield * 12
                            pmcc_score = min(100, (1 - cost_ratio) * 80 + min(monthly_yield * 5, 30) + (10 if leaps_dte >= 365 else 0))

                            if pmcc_score >= PMCC_MIN_QUALITY:
                                leaps_exp_short = leaps_expiry[2:7].replace("-", "")  # YYMM
                                pmcc_s_expiry_iso = pmcc_short_expiry.replace("-", "")
                                notes = f"LEAPS:{leaps_strike:.0f}C {leaps_exp_short}/Short:{pmcc_sc_strike:.0f}C"
                                out.append({
                                    "ticker": ticker, "strategy": "PMCC", "right": "C",
                                    "strike": leaps_strike,
                                    "expiry": pmcc_s_expiry_iso,
                                    "dte": pmcc_s_dte,
                                    "delta": 0.0,
                                    "premium": round(pmcc_sc_mid, 2),
                                    "bid": 0.0, "ask": 0.0,
                                    "annual_yield_pct": round(ann_yield, 2),
                                    "cash_required": round(leaps_mid * 100, 2),
                                    "breakeven": round(leaps_strike + leaps_mid, 2),
                                    "iv": 0.0, "iv_rank": 0.0,
                                    "spread_pct": 0.0,
                                    "underlying_last": round(price, 2),
                                    "technical_score": 0.0,
                                    "composite_score": round(pmcc_score, 1),
                                    "catalyst_flag": False,
                                    "hv30": round(hv30, 1),
                                    "notes": notes,
                                })
                                logger.info(
                                    f"  ✓ {ticker:6} PMCC {notes}  "
                                    f"short {pmcc_s_dte}DTE  income=${pmcc_sc_mid:.2f}  "
                                    f"LEAPS ${leaps_mid:.2f} ({leaps_dte}d)  "
                                    f"yield≈{ann_yield:.0f}%"
                                )
    except Exception as e:
        logger.debug(f"  {ticker}: PMCC error — {e}")

    if out:
        for c in out:
            label = c['strategy']
            if label == "LONG_CALL":
                logger.info(
                    f"  ✓ {c['ticker']:6} {label} ${c['strike']:7.2f} "
                    f"{c['dte']}DTE  prem=${c['premium']:5.2f}  "
                    f"BE=${c['breakeven']:.2f}  gov_score={c['composite_score']:.0f}  "
                    f"u=${c['underlying_last']:.2f}"
                )
            elif label in ("IC", "PCS", "CCS", "PMCC"):
                logger.info(
                    f"  ✓ {c['ticker']:6} {label:4} {c.get('notes', '')}  "
                    f"{c['dte']}DTE  prem=${c['premium']:5.2f}  yield={c['annual_yield_pct']:5.1f}%  "
                    f"score={c['composite_score']:.0f}  u=${c['underlying_last']:.2f}"
                )
            else:
                logger.info(
                    f"  ✓ {c['ticker']:6} {label} ${c['strike']:7.2f} "
                    f"{c['dte']}DTE  prem=${c['premium']:5.2f}  yield={c['annual_yield_pct']:5.1f}%  "
                    f"u=${c['underlying_last']:.2f}"
                )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="Print, no sheet write")
    args = ap.parse_args()

    logger = _setup_logging()
    logger.info("=== daily-options-scan start ===")

    watchlist = gather_watchlist(logger)
    logger.info(f"Watchlist: {len(watchlist)} tickers — {', '.join(watchlist)}")
    if not watchlist:
        logger.error("No tickers to scan")
        return 1

    # Load gov confluence signals for catalyst tagging + directional gate
    from src.sync import load_env
    from src import sheets as sh
    from src import schema as S
    load_env()
    client = sh.authenticate()
    gov_data: dict[str, dict] = {}
    try:
        import datetime as _dt
        ss = sh._open_sheet(client)
        ws_gc = ss.worksheet(S.GovConfluenceSignalRow.TAB_NAME)
        gc_rows = ws_gc.get_all_values()
        if len(gc_rows) > 1:
            gc_hdr = gc_rows[0]
            gc_cols = {h: i for i, h in enumerate(gc_hdr)}

            def _safe_col(r, col_name: str, default=""):
                if col_name not in gc_cols or gc_cols[col_name] >= len(r):
                    return default
                return r[gc_cols[col_name]] or default

            seven_d = (_dt.date.today() - _dt.timedelta(days=7)).isoformat()
            for r in gc_rows[1:]:
                if len(r) <= gc_cols.get("date", 0) or r[gc_cols["date"]] < seven_d:
                    continue
                tk = r[gc_cols["ticker"]].upper()
                try:
                    sc = float(r[gc_cols["confluence_score"]] or 0)
                except (TypeError, ValueError):
                    sc = 0
                prev = gov_data.get(tk)
                if prev is None or sc > prev.get("score", 0):
                    # Carry sub-scores so LONG_CALL quality can check
                    # for multi-signal confirmation (not just contracts)
                    gov_data[tk] = {
                        "score": sc,
                        "tier": _safe_col(r, "tier"),
                        "strategy": _safe_col(r, "recommended_strategy"),
                        "contract_score": float(_safe_col(r, "contract_score", "0")),
                        "congress_score": float(_safe_col(r, "congress_score", "0")),
                        "insider_score": float(_safe_col(r, "insider_score", "0")),
                        "analyst_score": float(_safe_col(r, "analyst_score", "0")),
                    }
            logger.info(f"  loaded {len(gov_data)} gov confluence signals for catalyst tagging")
    except Exception as e:
        logger.warning(f"  gov confluence unavailable ({e}) — no catalyst tagging")

    # Load insider transactions for LONG_CALL trigger (cluster buying)
    insider_data: dict[str, dict] = {}
    try:
        import datetime as _dt2
        ws_ins = ss.worksheet(S.InsiderTransactionRow.TAB_NAME)
        ins_rows = ws_ins.get_all_values()
        if len(ins_rows) > 1:
            ins_hdr = ins_rows[0]
            ins_cols = {h: i for i, h in enumerate(ins_hdr)}
            fourteen_d = (_dt2.date.today() - _dt2.timedelta(days=14)).isoformat()
            for r in ins_rows[1:]:
                tx_date = r[ins_cols.get("transaction_date", 0)] if ins_cols.get("transaction_date", 0) < len(r) else ""
                if tx_date < fourteen_d:
                    continue
                tk = (r[ins_cols.get("ticker", 0)] if ins_cols.get("ticker", 0) < len(r) else "").upper()
                if not tk:
                    continue
                side = (r[ins_cols.get("side", 0)] if ins_cols.get("side", 0) < len(r) else "").lower()
                try:
                    val = abs(float(r[ins_cols.get("value_usd", 0)] if ins_cols.get("value_usd", 0) < len(r) else 0))
                except (TypeError, ValueError):
                    val = 0
                entry = insider_data.setdefault(tk, {"buy_value": 0, "buy_count": 0, "sell_value": 0})
                if side == "buy":
                    entry["buy_value"] += val
                    entry["buy_count"] += 1
                elif side == "sell":
                    entry["sell_value"] += val
            ins_with_buys = sum(1 for v in insider_data.values() if v["buy_value"] >= 500_000)
            logger.info(f"  loaded insider data for {len(insider_data)} tickers ({ins_with_buys} with cluster buying)")
    except Exception as e:
        logger.warning(f"  insider transactions unavailable ({e})")

    # Load screen candidates for LONG_CALL trigger (VCP/CANSLIM breakouts)
    screen_data: dict[str, dict] = {}
    try:
        ws_sc = ss.worksheet(S.ScreenCandidateRow.TAB_NAME)
        sc_rows = ws_sc.get_all_values()
        if len(sc_rows) > 1:
            sc_hdr = sc_rows[0]
            sc_cols = {h: i for i, h in enumerate(sc_hdr)}
            seven_d2 = (_dt.date.today() - _dt.timedelta(days=7)).isoformat()
            for r in sc_rows[1:]:
                sc_date = r[sc_cols.get("date", 0)] if sc_cols.get("date", 0) < len(r) else ""
                if sc_date < seven_d2:
                    continue
                tk = (r[sc_cols.get("ticker", 0)] if sc_cols.get("ticker", 0) < len(r) else "").upper()
                if not tk:
                    continue
                try:
                    sc_score = float(r[sc_cols.get("score", 0)] if sc_cols.get("score", 0) < len(r) else 0)
                except (TypeError, ValueError):
                    sc_score = 0
                prev = screen_data.get(tk)
                if prev is None or sc_score > float(prev.get("score", 0)):
                    screen_data[tk] = {
                        "source": r[sc_cols.get("source", 0)] if sc_cols.get("source", 0) < len(r) else "",
                        "score": sc_score,
                        "trigger_price": r[sc_cols.get("trigger_price", 0)] if sc_cols.get("trigger_price", 0) < len(r) else "",
                        "rationale": r[sc_cols.get("rationale", 0)] if sc_cols.get("rationale", 0) < len(r) else "",
                    }
            logger.info(f"  loaded {len(screen_data)} screen candidates for breakout triggers")
    except Exception as e:
        logger.warning(f"  screen candidates unavailable ({e})")

    all_candidates: list[dict] = []
    for ticker in watchlist:
        try:
            gov_info = gov_data.get(ticker) or None
            ins_info = insider_data.get(ticker) or None
            scr_info = screen_data.get(ticker) or None
            cands = scan_ticker(ticker, logger, gov_info=gov_info,
                                insider_info=ins_info, screen_info=scr_info)
            # Tag candidates with gov confluence catalyst flag + gate
            for c in cands:
                if gov_info:
                    if not c.get("catalyst_flag"):
                        c["catalyst_flag"] = True
                    gov_strategy = gov_info.get("strategy", "")
                    # Block CSPs where Congress is selling (TRIM signal)
                    if c["strategy"] == "CSP" and gov_strategy == "TRIM":
                        logger.info(f"  {ticker}: CSP blocked — Congress cluster selling")
                        continue
                    # Block CCs where gov confluence says BUY (Tier A/B catalyst)
                    if c["strategy"] == "CC" and gov_info.get("tier") in ("A", "B") and gov_strategy in ("BUY_DIP", "LONG_CALL"):
                        logger.info(f"  {ticker}: CC blocked — gov confluence Tier {gov_info['tier']} {gov_strategy}")
                        continue
                all_candidates.append(c)
        except Exception as e:
            logger.debug(f"  {ticker}: {e}")

    # Sort by yield desc
    all_candidates.sort(key=lambda c: c["annual_yield_pct"], reverse=True)
    logger.info(f"Total candidates found: {len(all_candidates)}")

    if args.dry:
        logger.info("[DRY] Would write to scan_results")
        return 0

    if not all_candidates:
        logger.warning("No candidates met threshold — sheet not updated")
        return 0

    # Write to scan_results (client already authenticated above)
    sh.ensure_headers(client, S.ScanResultRow.TAB_NAME, S.ScanResultRow.HEADERS)

    today_iso = datetime.now().strftime("%Y-%m-%d")
    rows_to_write: list[list[str]] = []
    for c in all_candidates:
        row = S.ScanResultRow(
            date=today_iso,
            ticker=c["ticker"],
            strategy=c["strategy"],
            right=c["right"],
            strike=c["strike"],
            expiry=c["expiry"],
            dte=c["dte"],
            delta=c["delta"],
            premium=c["premium"],
            bid=c["bid"],
            ask=c["ask"],
            annual_yield_pct=c["annual_yield_pct"],
            cash_required=c["cash_required"],
            breakeven=c["breakeven"],
            iv=c["iv"],
            iv_rank=c["iv_rank"],
            spread_pct=c["spread_pct"],
            underlying_last=c["underlying_last"],
            technical_score=c["technical_score"],
            composite_score=c["composite_score"],
            catalyst_flag=c["catalyst_flag"],
            notes=c.get("notes", ""),
        )
        rows_to_write.append(row.to_row())

    sh.append_rows(client, S.ScanResultRow.TAB_NAME, rows_to_write)
    logger.info(f"✓ Wrote {len(rows_to_write)} rows to scan_results")

    # ── Telegram → Options Intel topic ────────────────────────────────
    try:
        from src import telegram as tg
        tg.ping_options_intel(
            date=today_iso,
            candidates=all_candidates,
            pwa_url="https://xynkro.github.io/CasaaFinance/",
        )
        logger.info("✓ Options Intel digest sent to Telegram")
    except Exception as e:
        logger.warning(f"Telegram Options Intel ping failed: {e}")

    logger.info("=== daily-options-scan done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
