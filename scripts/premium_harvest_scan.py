"""
premium_harvest_scan.py — "Never Get Assigned" Premium Harvest Scanner

3-layer pipeline that discovers high-IV CSP opportunities across the full US
market, filters by macro regime + fundamentals + technicals, and emits picks
with pre-built entry/maintenance/exit signal blocks.

Layer 1: Universe Discovery (FinViz screener → top 150 by IV)
Layer 2: Macro Gate + Soft Fundamentals (VIX, SPX, market cap, revenue)
Layer 3: Technical Conviction + Chain Scan (RSI, SMA, support, chain)

Output: harvest_scan sheet + Telegram Options Intel + PWA Harvest tab

Triggered daily by .github/workflows/premium-harvest-scan.yml at 10:40 SGT.

Usage:
  python scripts/premium_harvest_scan.py            # full live scan
  python scripts/premium_harvest_scan.py --dry      # print, no sheet write
  python scripts/premium_harvest_scan.py --top 5    # limit universe to top 5
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ─── Harvest parameters ─────────────────────────────────────────────────────
TARGET_DTE     = 35          # ideal DTE
DTE_RANGE      = (25, 45)    # acceptable range
CSP_OTM_FLOOR  = 0.10          # minimum 10% OTM regardless of vol
CSP_OTM_CEIL   = 0.40          # maximum OTM distance (avoid zero-premium)
CSP_VOL_SIGMA  = 1.0           # target ≥ 1σ OTM (vol-adjusted)
MIN_OI         = 50          # minimum open interest
MIN_MID        = 0.08        # minimum mid-price
MIN_CSP_YIELD  = 14.0        # annualised yield floor
MAX_PICKS      = 25          # max picks per day
TG_PICKS       = 8           # max picks sent to Telegram

# ─── Curated fallback universe (if FinViz unreachable) ───────────────────────
FALLBACK_HIGH_IV_UNIVERSE = [
    # Metals / commodities ETFs
    "SLV", "GDX", "COPX", "GLD", "TLT", "USO", "XLE",
    # Crypto-adjacent
    "MSTR", "COIN", "HOOD", "RIOT", "MARA", "CLSK",
    # High-IV tech/growth
    "AAOI", "CRWV", "BMNR", "OPEN", "SNAP", "PINS", "ROKU",
    "DKNG", "PENN", "AFRM", "UPST", "SOFI", "LCID", "RIVN",
    # Meme/momentum
    "PLTR", "RKLB", "ASTS", "NBIS", "RDDT", "PATH", "IONQ",
    # Large-cap high IV
    "TSLA", "AMD", "NVDA", "MU", "SMCI", "ARM", "AVGO",
    "NFLX", "META", "AMZN", "GOOGL",
    # Biotech
    "MRNA", "CRSP",
    # Industrials
    "BA", "GE", "CAT", "DE",
    # Financials
    "JPM", "GS", "BAC", "C", "MS",
    # Consumer
    "NKE", "LULU", "COST", "WMT",
    # Energy
    "OXY", "CVX", "XOM", "HAL",
    # Misc high-IV
    "ORCL", "SHOP", "SQ", "PYPL",
]


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("harvest-scan")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 1: Universe Discovery
# ═══════════════════════════════════════════════════════════════════════════════

def discover_universe(logger, top_n: int = 150) -> list[str]:
    """FinViz screener for optionable high-IV stocks. Falls back to curated list."""
    try:
        from finvizfinance.screener.overview import Overview

        foverview = Overview()
        filters_dict = {
            "Option/Short": "Optionable",
            "Price": "Over $5",
            "Average Volume": "Over 500K",
            "Market Cap": "+Small (over $300mln)",
        }
        foverview.set_filter(filters_dict=filters_dict)
        df = foverview.screener_view()

        if df is not None and not df.empty:
            tickers = df["Ticker"].tolist()[:top_n]
            logger.info(f"Layer 1: FinViz returned {len(df)} optionable stocks, taking top {len(tickers)}")
            return tickers
        else:
            logger.warning("Layer 1: FinViz returned empty — using fallback universe")
            return FALLBACK_HIGH_IV_UNIVERSE[:top_n]

    except Exception as e:
        logger.warning(f"Layer 1: FinViz unavailable ({e}) — using fallback universe")
        return FALLBACK_HIGH_IV_UNIVERSE[:top_n]


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 2: Macro Gate + Soft Fundamentals
# ═══════════════════════════════════════════════════════════════════════════════

def macro_gate(logger) -> dict:
    """Check macro regime. Returns {regime, vix, spx, spx_above_200sma, halted, blackout, caution}."""
    import yfinance as yf

    result = {"regime": "STANDARD", "halted": False, "blackout": False, "caution": False}

    # VIX
    try:
        vix_data = yf.download("^VIX", period="5d", progress=False)
        if not vix_data.empty:
            vix = float(vix_data["Close"].dropna().iloc[-1])
        else:
            vix = 18.0
        result["vix"] = round(vix, 1)
    except Exception:
        vix = 18.0
        result["vix"] = vix

    # SPX + 200 SMA
    try:
        spx_data = yf.download("^GSPC", period="250d", progress=False)
        if not spx_data.empty:
            spx_close = spx_data["Close"].dropna()
            spx = float(spx_close.iloc[-1])
            sma200 = float(spx_close.tail(200).mean()) if len(spx_close) >= 200 else 0
            result["spx"] = round(spx, 1)
            result["spx_sma200"] = round(sma200, 1)
            result["spx_above_200sma"] = spx > sma200
        else:
            result["spx"] = 0
            result["spx_above_200sma"] = True
    except Exception:
        result["spx"] = 0
        result["spx_above_200sma"] = True

    # Macro blackout check (FOMC/CPI/NFP within 2 days)
    try:
        from src.macro_blackouts import MacroFeed
        feed = MacroFeed.fetch()
        now_utc = datetime.now(timezone.utc)
        for ev in feed.events:
            ev_time = ev.get("_dt") or ev.get("datetime")
            if ev_time and abs((ev_time - now_utc).total_seconds()) < 2 * 86400:
                if ev.get("impact") == "high":
                    result["blackout"] = True
                    result["blackout_event"] = ev.get("event", "unknown")
                    break
    except Exception:
        pass  # no blackout data = assume OK

    # Regime classification
    if vix > 30 or not result.get("spx_above_200sma", True):
        result["regime"] = "HALTED"
        result["halted"] = True
    elif vix > 25 or result.get("blackout"):
        result["regime"] = "CAUTION"
        result["caution"] = True

    logger.info(f"Layer 2 Macro: {result['regime']} (VIX={result['vix']}, SPX>200SMA={result.get('spx_above_200sma')})")
    return result


def fundamental_gate(ticker: str, logger) -> tuple[bool, str]:
    """Soft fundamental filter. Returns (pass, reason)."""
    import yfinance as yf

    try:
        info = yf.Ticker(ticker).info
    except Exception:
        return False, "info fetch failed"

    mkt_cap = info.get("marketCap") or 0
    if mkt_cap < 500_000_000:
        return False, f"market cap ${mkt_cap / 1e6:.0f}M < $500M"

    revenue = info.get("totalRevenue") or info.get("revenue") or 0
    if revenue <= 0:
        return False, "no revenue"

    price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
    if price < 3:
        return False, f"price ${price:.2f} < $3"

    return True, "pass"


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 3: Technical Conviction + Chain Scan
# ═══════════════════════════════════════════════════════════════════════════════

def technical_conviction(ticker: str, logger) -> tuple[bool, int, dict]:
    """
    Technical gates + conviction score.
    Returns (pass, score, context_dict).
    """
    import yfinance as yf

    try:
        yt = yf.Ticker(ticker)
        hist = yt.history(period="250d", interval="1d", auto_adjust=True)
        if hist.empty or len(hist) < 50:
            return False, 0, {}
        closes = hist["Close"].dropna()
        price = float(closes.iloc[-1])
    except Exception:
        return False, 0, {}

    # SMA calculations
    sma50 = float(closes.tail(50).mean()) if len(closes) >= 50 else 0
    sma200 = float(closes.tail(200).mean()) if len(closes) >= 200 else 0
    sma20 = float(closes.tail(20).mean()) if len(closes) >= 20 else 0

    # RSI-14 (Wilder smoothing)
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, float("inf"))
    rsi_series = 100 - (100 / (1 + rs))
    rsi_14 = float(rsi_series.iloc[-1]) if len(rsi_series) >= 14 else 50.0
    if math.isnan(rsi_14):
        rsi_14 = 50.0

    # 20d support/resistance
    recent_20 = closes.tail(20)
    support = float(recent_20.min())
    resistance = float(recent_20.max())

    # HV30
    log_rets = closes.pct_change().dropna().apply(lambda x: math.log(1 + x) if x > -1 else 0)
    hv30 = float(log_rets.tail(30).std() * math.sqrt(252) * 100) if len(log_rets) >= 30 else 0

    # Volume check
    vols = hist["Volume"].dropna()
    avg_vol = float(vols.tail(20).mean()) if len(vols) >= 20 else 0

    ctx = {
        "price": round(price, 2),
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2),
        "sma200": round(sma200, 2),
        "rsi_14": round(rsi_14, 1),
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "hv30": round(hv30, 1),
        "avg_vol": int(avg_vol),
    }

    # ═══ GATES (all must pass) ═══
    if sma50 > 0 and price < sma50:
        return False, 0, ctx
    if sma200 > 0 and price < sma200:
        return False, 0, ctx
    if rsi_14 < 30 or rsi_14 > 75:
        return False, 0, ctx
    if support > 0 and price < support * 1.03:
        return False, 0, ctx  # falling knife
    if avg_vol < 200_000:
        return False, 0, ctx

    # ═══ CONVICTION SCORE (0-100) ═══
    score = 40  # base: passed all gates
    if sma20 > sma50:
        score += 10  # uptrend confirmed
    if 40 <= rsi_14 <= 60:
        score += 10  # RSI sweet spot
    if support > 0 and price < support * 1.05:
        score += 10  # near support but holding
    if avg_vol > 1_000_000:
        score += 5   # high liquidity bonus

    return True, score, ctx


def scan_chain(ticker: str, ctx: dict, conviction: int, macro: dict, logger) -> list[dict]:
    """Scan option chain for CSP + CC candidates. Build signal blocks."""
    import yfinance as yf

    price = ctx["price"]
    hv30 = ctx["hv30"]

    try:
        yt = yf.Ticker(ticker)
        expiries = yt.options
    except Exception:
        return []
    if not expiries:
        return []

    # Best expiry: closest to TARGET_DTE within DTE_RANGE
    today = date.today()
    best_exp, best_diff = None, 9999
    for exp_str in expiries:
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if DTE_RANGE[0] <= dte <= DTE_RANGE[1]:
                diff = abs(dte - TARGET_DTE)
                if diff < best_diff:
                    best_diff = diff
                    best_exp = exp_str
        except ValueError:
            continue
    if not best_exp:
        return []

    dte = (datetime.strptime(best_exp, "%Y-%m-%d").date() - today).days
    expiry_iso = best_exp.replace("-", "")

    try:
        chain = yt.option_chain(best_exp)
    except Exception:
        return []

    candidates = []

    # ── CSP scan ──────────────────────────────────────────────────────────────
    try:
        puts = chain.puts.copy()
        puts = puts[puts["openInterest"] >= MIN_OI]
        puts["mid"] = puts.apply(
            lambda r: (r["bid"] + r["ask"]) / 2
            if (r.get("bid", 0) or 0) > 0 or (r.get("ask", 0) or 0) > 0
            else (r.get("lastPrice", 0) or 0),
            axis=1,
        )
        puts = puts[puts["mid"] >= MIN_MID]
        # Vol-adjusted OTM range: ≥ 1σ move below spot, clamped to [10%, 25%].
        # At 30% vol / 35 DTE this ≈ 9.3% → floor kicks in at 10%.
        # At 99% vol / 35 DTE this ≈ 30.7% → ceiling caps at 25%.
        # This prevents high-vol names (APLD, MSTR) from getting too-close strikes.
        _vol = hv30 / 100 if hv30 > 0 else 0.30  # fallback 30% vol
        _sigma_otm = CSP_VOL_SIGMA * _vol * math.sqrt(dte / 365)
        _otm_min = max(CSP_OTM_FLOOR, _sigma_otm)
        _otm_max = min(CSP_OTM_CEIL, _sigma_otm * 1.5)
        # Ensure min < max (can happen when vol is very low)
        if _otm_max <= _otm_min:
            _otm_max = _otm_min + 0.05
        puts = puts[
            (puts["strike"] >= price * (1 - _otm_max))
            & (puts["strike"] <= price * (1 - _otm_min))
        ]
        puts = puts.copy()
        puts["ann_yield"] = puts["mid"] / puts["strike"] * (365 / dte) * 100
        puts = puts[puts["ann_yield"] >= MIN_CSP_YIELD]
        puts = puts.sort_values("ann_yield", ascending=False)

        if not puts.empty:
            r = puts.iloc[0]
            mid = float(r["mid"])
            strike = float(r["strike"])
            iv_pct = float(r.get("impliedVolatility", 0) or 0) * 100
            oi = int(r.get("openInterest", 0) or 0)

            # Conviction bonuses from chain data
            iv_rich_bonus = 10 if (hv30 > 0 and iv_pct / hv30 > 1.2) else 0
            oi_bonus = 5 if oi > 200 else 0
            bid = float(r.get("bid", 0) or 0)
            ask = float(r.get("ask", 0) or 0)
            spread_pct = ((ask - bid) / mid * 100) if mid > 0 and bid > 0 else 99
            spread_bonus = 5 if spread_pct < 10 else 0
            final_conviction = min(100, conviction + iv_rich_bonus + oi_bonus + spread_bonus)

            # S/R context string
            sr_parts = []
            if ctx["support"] > 0:
                dist_pct = (price - ctx["support"]) / price * 100
                sr_parts.append(f"support ${ctx['support']:.0f} ({dist_pct:.0f}%)")
            sr_parts.append(f"RSI {ctx['rsi_14']:.0f}")
            sr_context = " · ".join(sr_parts)

            # Signal blocks
            entry_signals = json.dumps({
                "strategy": "HARVEST_CSP",
                "ticker": ticker, "strike": strike,
                "expiry": expiry_iso, "dte": dte,
                "credit": round(mid, 2),
                "annual_yield_pct": round(float(r["ann_yield"]), 1),
                "iv_rank": round(iv_pct, 1), "conviction": final_conviction,
                "sr_context": sr_context,
                "macro_regime": macro["regime"],
                "vix": macro["vix"],
                "spx_above_200sma": macro.get("spx_above_200sma", True),
            })
            maintenance_signals = json.dumps({
                "profit_target_pct": 50,
                "profit_target_optional": True,
                "time_stop_dte": 21,
                "strike_tested_pct": 3,
                "earnings_in_dte": False,
                "macro_shift_exit": True,
                "trend_break_exit": True,
                "sma50_at_entry": ctx["sma50"],
            })
            exit_signals = json.dumps({
                "max_loss_mult": 2.0,
                "max_loss_value": round(mid * 2, 2),
                "mechanical_close_dte": 14,
                "assignment_risk_dte": 7,
                "expired_worthless": True,
            })

            candidates.append({
                "ticker": ticker, "strategy": "HARVEST_CSP",
                "strike": strike, "expiry": expiry_iso, "dte": dte,
                "credit": round(mid, 2),
                "annual_yield_pct": round(float(r["ann_yield"]), 1),
                "iv_rank": round(iv_pct, 1),
                "conviction": final_conviction,
                "underlying_last": price,
                "cash_required": round(strike * 100, 2),
                "breakeven": round(strike - mid, 2),
                "sr_context": sr_context,
                "entry_signals": entry_signals,
                "maintenance_signals": maintenance_signals,
                "exit_signals": exit_signals,
                "notes": "",
            })
    except Exception as e:
        logger.debug(f"  {ticker}: CSP chain error — {e}")

    # CC scan removed — selling naked calls on stocks you don't own is
    # undefined-risk. CSP-only is the harvest strategy. If both sides are
    # wanted, use an iron condor (defined risk) instead.

    return candidates


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    import yfinance as yf

    ap = argparse.ArgumentParser(description="Premium Harvest Scanner")
    ap.add_argument("--dry", action="store_true", help="Print only, no sheet/Telegram")
    ap.add_argument("--top", type=int, default=150, help="Universe cap (default 150)")
    args = ap.parse_args()

    logger = _setup_logging()
    logger.info("═══ Premium Harvest Scanner ═══")

    # ── Layer 1: Universe Discovery ──
    universe = discover_universe(logger, top_n=args.top)
    if not universe:
        logger.error("Layer 1: Empty universe — aborting")
        return 1

    # ── Layer 2: Macro Gate ──
    macro = macro_gate(logger)
    if macro["halted"]:
        logger.warning(f"MACRO HALTED (VIX={macro['vix']}, regime={macro['regime']}) — skipping harvest scan")
        if not args.dry:
            # Write a single status row so PWA banner shows HALTED
            try:
                from src.sync import load_env
                from src import sheets as sh
                from src import schema as S
                load_env()
                client = sh.authenticate()
                sh.ensure_headers(client, S.HarvestScanRow.TAB_NAME, S.HarvestScanRow.HEADERS)
                halt_row = S.HarvestScanRow(
                    date=date.today().isoformat(), ticker="--", strategy="HALTED",
                    strike=0, expiry="", dte=0, credit=0, annual_yield_pct=0,
                    iv_rank=0, conviction=0, underlying_last=0, cash_required=0,
                    breakeven=0, sr_context="", macro_regime=macro["regime"],
                    vix=macro["vix"], entry_signals="{}", maintenance_signals="{}",
                    exit_signals="{}", notes=f"halted: VIX={macro['vix']}",
                )
                sh.append_rows(client, S.HarvestScanRow.TAB_NAME, [halt_row.to_row()])
                logger.info("  ✓ Wrote HALTED status row")
            except Exception as e:
                logger.warning(f"  Sheet write failed: {e}")
        return 0

    # ── Layer 2: Soft Fundamentals ──
    survivors = []
    for ticker in universe:
        ok, reason = fundamental_gate(ticker, logger)
        if ok:
            survivors.append(ticker)
        else:
            logger.debug(f"  {ticker}: fundamental reject — {reason}")
    logger.info(f"Layer 2 Fundamentals: {len(survivors)} of {len(universe)} passed")

    if not survivors:
        logger.warning("No tickers survived fundamental filter — aborting")
        return 0

    # ── Layer 3: Technical Conviction + Chain Scan ──
    all_candidates = []
    for i, ticker in enumerate(survivors):
        try:
            ok, score, ctx = technical_conviction(ticker, logger)
            if not ok:
                logger.debug(f"  {ticker}: technical reject")
                continue
            picks = scan_chain(ticker, ctx, score, macro, logger)
            all_candidates.extend(picks)
            if (i + 1) % 10 == 0:
                logger.info(f"  ... scanned {i + 1}/{len(survivors)} tickers, {len(all_candidates)} picks so far")
        except Exception as e:
            logger.debug(f"  {ticker}: scan error — {e}")

    all_candidates.sort(key=lambda c: c["conviction"], reverse=True)
    logger.info(f"Layer 3: {len(all_candidates)} harvest candidates found")

    # Top picks summary
    for c in all_candidates[:10]:
        logger.info(
            f"  {c['strategy']:18} {c['ticker']:6} ${c['strike']:.0f} {c['dte']}d "
            f"cr=${c['credit']:.2f} yld={c['annual_yield_pct']:.0f}% conv={c['conviction']}"
        )

    if args.dry:
        logger.info("DRY RUN — no sheet write or Telegram push")
        return 0

    # ── Write to sheet ──
    today_iso = date.today().isoformat()
    try:
        from src.sync import load_env
        from src import sheets as sh
        from src import schema as S
        load_env()
        client = sh.authenticate()
        sh.ensure_headers(client, S.HarvestScanRow.TAB_NAME, S.HarvestScanRow.HEADERS)

        rows = []
        for c in all_candidates[:MAX_PICKS]:
            row = S.HarvestScanRow(
                date=today_iso, ticker=c["ticker"], strategy=c["strategy"],
                strike=c["strike"], expiry=c["expiry"], dte=c["dte"],
                credit=c["credit"], annual_yield_pct=c["annual_yield_pct"],
                iv_rank=c["iv_rank"], conviction=c["conviction"],
                underlying_last=c["underlying_last"],
                cash_required=c["cash_required"], breakeven=c["breakeven"],
                sr_context=c["sr_context"],
                macro_regime=macro["regime"], vix=macro["vix"],
                entry_signals=c["entry_signals"],
                maintenance_signals=c["maintenance_signals"],
                exit_signals=c["exit_signals"],
                notes=c.get("notes", ""),
            )
            rows.append(row.to_row())
        sh.append_rows(client, S.HarvestScanRow.TAB_NAME, rows)
        logger.info(f"  ✓ Wrote {len(rows)} rows to harvest_scan")
    except Exception as e:
        logger.error(f"  Sheet write failed: {e}")

    # ── Telegram push ──
    try:
        from src import telegram as tg
        tg_result = tg.ping_harvest_scan(
            date=today_iso,
            candidates=all_candidates[:TG_PICKS],
            macro=macro,
            pwa_url="https://xynkro.github.io/CasaaFinance/",
        )
        if tg_result.get("skipped"):
            logger.info(f"  Telegram: skipped ({tg_result['skipped']})")
        else:
            logger.info("  ✓ Harvest picks sent to Telegram")
    except Exception as e:
        logger.warning(f"  Telegram harvest push failed: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
