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

    # Filter SGX-only tickers (yfinance needs .SI suffix and we don't write those to scan_results)
    SGX = {"C6L", "G3B", "D05", "O39", "U11", "Z74", "V03"}
    tickers = {t for t in tickers if t not in SGX and len(t) <= 5 and t.isalpha()}

    return sorted(tickers)


def _hv30(yt) -> float:
    try:
        hist = yt.history(period="60d", interval="1d", auto_adjust=True)
        if hist.empty or len(hist) < 20:
            return 0.0
        closes = hist["Close"].dropna()
        log_rets = closes.pct_change().dropna().apply(lambda x: math.log(1 + x))
        return float(log_rets.std() * math.sqrt(252) * 100)
    except Exception:
        return 0.0


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


def scan_ticker(ticker: str, logger: logging.Logger, gov_info: dict | None = None) -> list[dict[str, Any]]:
    """Return CSP + CC + LONG_CALL candidates for a single ticker.

    gov_info: optional dict from gov_confluence_signals with keys
    {score, tier, strategy, contract_score, congress_score, insider_score,
    analyst_score}. When present with bullish signals + sufficient quality,
    triggers LONG_CALL scanning alongside CSP/CC.
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

    hv30 = _hv30(yt)
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
            out.append({
                "ticker": ticker,
                "strategy": "CSP",
                "right": "P",
                "strike": float(r["strike"]),
                "expiry": expiry_iso,
                "dte": dte,
                "delta": float(r.get("delta", 0) or 0),
                "premium": round(mid, 2),
                "bid": round(bid, 2),
                "ask": round(ask, 2),
                "annual_yield_pct": round(float(r["ann_yield"]), 2),
                "cash_required": round(float(r["strike"]) * 100, 2),
                "breakeven": round(float(r["strike"]) - mid, 2),
                "iv": round(float(r.get("impliedVolatility", 0) or 0) * 100, 1),
                "iv_rank": 0.0,  # yfinance doesn't expose IV rank — leave for IBKR scan
                "spread_pct": round(spread_pct, 2),
                "underlying_last": round(price, 2),
                "technical_score": 0.0,
                "composite_score": round(float(r["ann_yield"]), 2),
                "catalyst_flag": False,
                "hv30": round(hv30, 1),
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
            out.append({
                "ticker": ticker,
                "strategy": "CC",
                "right": "C",
                "strike": float(r["strike"]),
                "expiry": expiry_iso,
                "dte": dte,
                "delta": float(r.get("delta", 0) or 0),
                "premium": round(mid, 2),
                "bid": round(bid, 2),
                "ask": round(ask, 2),
                "annual_yield_pct": round(float(r["ann_yield"]), 2),
                "cash_required": round(price * 100, 2),
                "breakeven": round(price - mid, 2),
                "iv": round(float(r.get("impliedVolatility", 0) or 0) * 100, 1),
                "iv_rank": 0.0,
                "spread_pct": round(spread_pct, 2),
                "underlying_last": round(price, 2),
                "technical_score": 0.0,
                "composite_score": round(float(r["ann_yield"]), 2),
                "catalyst_flag": False,
                "hv30": round(hv30, 1),
            })
    except Exception as e:
        logger.debug(f"  {ticker}: CC error — {e}")

    # ── LONG_CALL — quality-gated directional plays ─────────────────
    # NOT just "gov contract exists → buy call."  Quality scoring checks:
    #   1. Contract materiality vs market cap (is it meaningful?)
    #   2. Trend health: SMA50/SMA200 (don't buy calls into downtrends)
    #   3. Multi-signal: congress cluster + insider + analyst confirming
    # Minimum quality LC_MIN_QUALITY (40) to emit a candidate.
    gov_bullish = (
        gov_info is not None
        and gov_info.get("score", 0) >= 30
        and gov_info.get("strategy", "") != "TRIM"
    )
    if gov_bullish:
        # Quality gate BEFORE option chain fetch (saves API calls)
        lc_quality, lc_reasons = _long_call_quality(fi, price, gov_info, logger, ticker)
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

                    out.append({
                        "ticker": ticker,
                        "strategy": "LONG_CALL",
                        "right": "C",
                        "strike": float(r["strike"]),
                        "expiry": lc_expiry_iso,
                        "dte": lc_dte,
                        "delta": float(r.get("delta", 0) or 0),
                        "premium": round(mid, 2),
                        "bid": round(bid, 2),
                        "ask": round(ask, 2),
                        "annual_yield_pct": 0.0,  # N/A for directional
                        "cash_required": round(mid * 100, 2),  # premium × 100
                        "breakeven": round(float(r["strike"]) + mid, 2),
                        "iv": round(float(r.get("impliedVolatility", 0) or 0) * 100, 1),
                        "iv_rank": 0.0,
                        "spread_pct": round(spread_pct, 2),
                        "underlying_last": round(price, 2),
                        "technical_score": round(trend_score, 1),
                        "composite_score": round(lc_quality, 1),
                        "catalyst_flag": True,
                        "hv30": round(hv30, 1),
                    })
                    logger.info(
                        f"  {ticker}: LONG_CALL quality={lc_quality:.0f} "
                        f"${r['strike']}C exp {lc_expiry_iso} "
                        f"trend={trend_score:+.0f} — {'; '.join(lc_reasons)}"
                    )
            except Exception as e:
                logger.debug(f"  {ticker}: LONG_CALL error — {e}")

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

    all_candidates: list[dict] = []
    for ticker in watchlist:
        try:
            gov_info = gov_data.get(ticker) or None
            cands = scan_ticker(ticker, logger, gov_info=gov_info)
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
        )
        rows_to_write.append(row.to_row())

    sh.append_rows(client, S.ScanResultRow.TAB_NAME, rows_to_write)
    logger.info(f"✓ Wrote {len(rows_to_write)} rows to scan_results")
    logger.info("=== daily-options-scan done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
