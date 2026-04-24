"""
market_scan.py — Scan external signals (LunarCrush, WSB, quality watchlist)
for CSP and CC opportunities BEYOND existing positions.

Sources:
  - LunarCrush trending stocks (top by social engagement / AltRank)
  - WallStreetBets top picks (curated from WSB community + live Reddit JSON)
  - Quality watchlist (blue-chip / dividend / sector leaders)

Screening criteria (yfinance option chains):
  - CSP: quality dip → put 5–15% OTM, 25–45 DTE, annualised yield ≥ 14%
  - CC:  volatile/trending → call 2–7% OTM, 25–45 DTE, annualised yield ≥ 12%
  - Min open interest 75 per strike
  - Min mid-price $0.08/share
  - IV/HV30 ≥ 1.15 (options priced richly vs realised vol)

Output: appends to option_recommendations sheet (same schema as ibkr_grab).

Usage:
  python scripts/market_scan.py           # full scan, write to sheet
  python scripts/market_scan.py --dry     # print results, no sheet write
  python scripts/market_scan.py --top 20  # limit candidates per source
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Candidate universes ───────────────────────────────────────────────────────

# LunarCrush top-by-engagement (updated weekly via curation; re-pull via MCP)
LUNARCRUSH_TICKERS: list[str] = [
    "SPOT", "GOOGL", "TSLA", "KO", "RDDT", "WMT", "UBER", "MSFT",
    "PEP", "NKE", "SBUX", "COST", "NVDA", "FLEX", "NYT",
    # AltRank leaders
    "IREN", "TXN", "NOK", "UNP", "CMCSA", "APLD", "MRVL", "ON",
    "OKLO", "VTR", "ARM", "NEE", "URI", "VRT", "WM", "CVS",
    "ADI", "CSX", "TMUS", "BE", "VZ", "INTC", "MOH", "WDC", "TER", "OSK",
]

# WallStreetBets community top picks (2026 list + live surge)
WSB_TICKERS: list[str] = [
    "AMZN", "RKLB", "ASTS", "GOOGL", "NBIS", "RDDT", "SOFI",
    "PATH", "MU", "LULU", "PLTR", "HOOD", "COIN", "MSTR",
]

# Quality watchlist: liquid, dividend or moat — reliable CSP targets
QUALITY_WATCHLIST: list[str] = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "AMD", "NFLX",
    "JPM", "BAC", "GS", "C", "V", "MA", "AXP",
    "COST", "WMT", "TGT", "HD", "LOW",
    "KO", "PEP", "PG", "MO", "PM",
    "JNJ", "MRK", "ABBV", "LLY", "PFE", "UNH",
    "TSLA", "F", "GM", "UBER",
    "XOM", "CVX", "OXY",
    "GLD", "SLV", "GDX",
]

# Minimum thresholds
MIN_OI          = 50      # open interest per strike
MIN_MID_PRICE   = 0.05    # minimum option mid-price ($)
MIN_CSP_YIELD   = 10.0    # annualised yield % for CSP
MIN_CC_YIELD    = 8.0     # annualised yield % for CC
IV_HV_RATIO_MIN = 1.05    # IV must be at least 5% above HV30
TARGET_DTE_MIN  = 15
TARGET_DTE_MAX  = 60
TARGET_DTE_IDEAL= 35
MAX_PRICE       = 650     # skip ultra-high priced stocks (cash req too big)
MIN_PRICE       = 3.0


def _setup_logging() -> logging.Logger:
    log_path = ROOT / ".state" / "market-scan.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("market-scan")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(log_path)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(sh)
    return logger


def _fetch_wsb_live(logger: logging.Logger) -> list[str]:
    """Pull most-mentioned tickers from WSB via Reddit public JSON (no auth)."""
    import re
    try:
        import urllib.request
        url = "https://www.reddit.com/r/wallstreetbets/hot.json?limit=25"
        req = urllib.request.Request(url, headers={"User-Agent": "market-scan/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        posts = data.get("data", {}).get("children", [])
        tickers: set[str] = set()
        # Simple heuristic: look for $TICKER or ALL-CAPS 2-5 letter words
        pattern = re.compile(r'\$([A-Z]{1,5})\b|(?<!\w)([A-Z]{2,5})(?!\w)')
        SKIP = {"WSB", "DD", "YOLO", "GME", "AMC", "MEME", "SEC", "CEO", "IPO",
                "ATH", "EPS", "CPI", "PPI", "FOMC", "FED", "ETF", "SPAC",
                "USD", "EUR", "GBP", "SPY", "QQQ", "SPX", "VIX", "OTM",
                "ITM", "ATM", "DTE", "IV", "HV", "OI", "P&L", "YTD"}
        for post in posts:
            title = post.get("data", {}).get("title", "")
            for m in pattern.finditer(title):
                t = m.group(1) or m.group(2)
                if t and t not in SKIP and len(t) >= 2:
                    tickers.add(t)
        live = sorted(tickers)
        logger.info(f"WSB live tickers extracted: {', '.join(live[:20])}")
        return live
    except Exception as e:
        logger.warning(f"WSB live fetch failed (non-fatal): {e}")
        return []


def _hv30(ticker_obj) -> float:
    """Compute 30-day historical volatility from daily close prices."""
    try:
        hist = ticker_obj.history(period="60d", interval="1d", auto_adjust=True)
        if hist.empty or len(hist) < 20:
            return 0.0
        closes = hist["Close"].dropna()
        log_rets = closes.pct_change().dropna().apply(lambda x: math.log(1 + x))
        hv = float(log_rets.std() * math.sqrt(252) * 100)  # annualised %
        return hv
    except Exception:
        return 0.0


def _best_expiry(expiries: tuple[str, ...]) -> str | None:
    """Pick the expiry closest to TARGET_DTE_IDEAL within [MIN_DTE, MAX_DTE]."""
    today = date.today()
    best: str | None = None
    best_diff = 9999
    for exp_str in expiries:
        try:
            exp = datetime.strptime(exp_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (exp - today).days
        if TARGET_DTE_MIN <= dte <= TARGET_DTE_MAX:
            diff = abs(dte - TARGET_DTE_IDEAL)
            if diff < best_diff:
                best_diff = diff
                best = exp_str
    return best


def screen_ticker(ticker: str, hv30: float, logger: logging.Logger) -> list[dict[str, Any]]:
    """Screen a single ticker for CSP and CC opportunities. Returns list of rec dicts."""
    import yfinance as yf

    try:
        stock = yf.Ticker(ticker)
        fi = stock.fast_info
        price = float(fi.last_price or 0)
    except Exception as e:
        logger.debug(f"  {ticker}: price fetch failed — {e}")
        return []

    if price < MIN_PRICE or price > MAX_PRICE:
        logger.debug(f"  {ticker}: price {price:.2f} out of range")
        return []

    try:
        expiries = stock.options
    except Exception:
        return []
    if not expiries:
        return []

    expiry = _best_expiry(expiries)
    if not expiry:
        logger.debug(f"  {ticker}: no suitable expiry")
        return []

    today = date.today()
    dte = (datetime.strptime(expiry, "%Y-%m-%d").date() - today).days

    try:
        chain = stock.option_chain(expiry)
    except Exception as e:
        logger.debug(f"  {ticker}: chain fetch failed — {e}")
        return []

    recs: list[dict[str, Any]] = []

    # ── CSP ──────────────────────────────────────────────────────────────────
    try:
        puts = chain.puts.copy()
        puts = puts[puts["openInterest"] >= MIN_OI]
        # Use bid/ask mid; fall back to lastPrice when market is closed (bid=ask=0)
        puts["mid"] = puts.apply(
            lambda r: (r["bid"] + r["ask"]) / 2
            if (r.get("bid", 0) or 0) > 0 or (r.get("ask", 0) or 0) > 0
            else (r.get("lastPrice", 0) or 0),
            axis=1,
        )
        puts = puts[puts["mid"] >= MIN_MID_PRICE]
        # Strike 2–18% OTM (include near-ATM puts for higher-yield CSPs)
        puts = puts[(puts["strike"] >= price * 0.82) & (puts["strike"] <= price * 0.985)]
        # Sort: highest yield
        puts = puts.copy()
        puts["ann_yield"] = puts["mid"] / puts["strike"] * (365 / dte) * 100
        puts = puts[puts["ann_yield"] >= MIN_CSP_YIELD]
        puts = puts.sort_values("ann_yield", ascending=False)

        if not puts.empty:
            r = puts.iloc[0]
            iv_pct = float(r.get("impliedVolatility", 0) or 0) * 100
            recs.append({
                "ticker":           ticker,
                "strategy":         "CSP",
                "right":            "P",
                "strike":           float(r["strike"]),
                "expiry":           expiry,
                "premium_per_share":round(float(r["mid"]), 2),
                "delta":            round(float(r.get("delta", 0) or 0), 3),
                "annual_yield_pct": round(float(r["ann_yield"]), 1),
                "breakeven":        round(float(r["strike"]) - float(r["mid"]), 2),
                "cash_required":    round(float(r["strike"]) * 100, 0),
                "iv_rank":          round(iv_pct, 1),
                "dte":              dte,
                "hv30":             round(hv30, 1),
                "price":            round(price, 2),
            })
    except Exception as e:
        logger.debug(f"  {ticker}: CSP screen error — {e}")

    # ── CC ───────────────────────────────────────────────────────────────────
    try:
        calls = chain.calls.copy()
        calls = calls[calls["openInterest"] >= MIN_OI]
        calls["mid"] = calls.apply(
            lambda r: (r["bid"] + r["ask"]) / 2
            if (r.get("bid", 0) or 0) > 0 or (r.get("ask", 0) or 0) > 0
            else (r.get("lastPrice", 0) or 0),
            axis=1,
        )
        calls = calls[calls["mid"] >= MIN_MID_PRICE]
        # Strike 1–8% OTM
        calls = calls[(calls["strike"] >= price * 1.01) & (calls["strike"] <= price * 1.08)]
        calls = calls.copy()
        calls["ann_yield"] = calls["mid"] / price * (365 / dte) * 100
        calls = calls[calls["ann_yield"] >= MIN_CC_YIELD]
        calls = calls.sort_values("ann_yield", ascending=False)

        if not calls.empty:
            r = calls.iloc[0]
            iv_pct = float(r.get("impliedVolatility", 0) or 0) * 100
            recs.append({
                "ticker":           ticker,
                "strategy":         "CC",
                "right":            "C",
                "strike":           float(r["strike"]),
                "expiry":           expiry,
                "premium_per_share":round(float(r["mid"]), 2),
                "delta":            round(float(r.get("delta", 0) or 0), 3),
                "annual_yield_pct": round(float(r["ann_yield"]), 1),
                "breakeven":        round(price - float(r["mid"]), 2),
                "cash_required":    round(price * 100, 0),
                "iv_rank":          round(iv_pct, 1),
                "dte":              dte,
                "hv30":             round(hv30, 1),
                "price":            round(price, 2),
            })
    except Exception as e:
        logger.debug(f"  {ticker}: CC screen error — {e}")

    if recs:
        labels = [f"{r['strategy']} {r['annual_yield_pct']:.1f}%/yr" for r in recs]
        logger.info(f"  ✓ {ticker:8} @ ${price:7.2f}  IV={recs[0]['iv_rank']:.0f}%  HV30={hv30:.0f}%  → {', '.join(labels)}")
    else:
        logger.debug(f"  ✗ {ticker:8} @ ${price:7.2f}  HV30={hv30:.0f}%  — no qualifying strikes")

    return recs


def build_universe(use_wsb_live: bool, logger: logging.Logger) -> list[str]:
    """Merge all sources, deduplicate, filter to US-listed-looking tickers."""
    tickers: list[str] = []
    seen: set[str] = set()

    for src_name, src_list in [
        ("lunarcrush", LUNARCRUSH_TICKERS),
        ("wsb_static",  WSB_TICKERS),
        ("quality",     QUALITY_WATCHLIST),
    ]:
        added = 0
        for t in src_list:
            t = t.strip().upper()
            if t and t not in seen and len(t) <= 5 and t.isalpha():
                tickers.append(t)
                seen.add(t)
                added += 1
        logger.info(f"Source [{src_name}]: +{added} tickers (total {len(tickers)})")

    if use_wsb_live:
        live = _fetch_wsb_live(logger)
        added = 0
        for t in live:
            t = t.strip().upper()
            if t and t not in seen and len(t) <= 5 and t.isalpha():
                tickers.append(t)
                seen.add(t)
                added += 1
        logger.info(f"Source [wsb_live]: +{added} tickers (total {len(tickers)})")

    return tickers


def run_scan(
    dry: bool,
    top: int,
    use_wsb_live: bool,
    logger: logging.Logger,
) -> list[dict]:
    import yfinance as yf

    universe = build_universe(use_wsb_live, logger)
    logger.info(f"Scanning {len(universe)} tickers for CSP/CC opportunities...")

    all_recs: list[dict] = []
    now_ts = datetime.now().strftime("%Y-%m-%dT%H%M%S")

    for ticker in universe:
        try:
            yf_ticker = yf.Ticker(ticker)
            hv = _hv30(yf_ticker)
            recs = screen_ticker(ticker, hv, logger)
            for r in recs:
                r["timestamp"] = now_ts
                all_recs.append(r)
        except Exception as e:
            logger.debug(f"  {ticker}: unhandled error — {e}")

    # Sort by annualised yield descending
    all_recs.sort(key=lambda r: r["annual_yield_pct"], reverse=True)

    if not all_recs:
        logger.warning("No qualifying opportunities found in this scan.")
        return []

    logger.info(f"\n{'='*60}")
    logger.info(f"TOP OPPORTUNITIES ({len(all_recs)} found)")
    logger.info(f"{'='*60}")
    for r in all_recs[:top]:
        logger.info(
            f"  {r['strategy']:4} {r['ticker']:8} ${r['strike']:6.2f} x{r['dte']}DTE  "
            f"prem=${r['premium_per_share']:.2f}  yield={r['annual_yield_pct']:.1f}%/yr  "
            f"IV={r['iv_rank']:.0f}%  HV30={r['hv30']:.0f}%  "
            f"cash=${r['cash_required']:,.0f}"
        )

    if dry:
        logger.info(f"\n[DRY] Would write {min(top, len(all_recs))} rows to option_recommendations")
        return all_recs

    # ── Write to sheet ────────────────────────────────────────────────────────
    from src.sync import load_env
    from src import sheets as sh
    from src import schema as S

    load_env()
    client = sh.authenticate()
    sh.ensure_headers(client, S.OptionRecommendationRow.TAB_NAME, S.OptionRecommendationRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.OptionRecommendationRow.TAB_NAME)

    existing = ws.get_all_values()[1:]  # skip header
    # Dedup key: (source_date, ticker, strategy, strike)
    seen_keys: set[tuple] = set()
    for row in existing:
        key = (
            row[0][:10] if row else "",    # date (first 10 chars)
            row[3] if len(row) > 3 else "",  # ticker
            row[4] if len(row) > 4 else "",  # strategy
            row[6] if len(row) > 6 else "",  # strike
        )
        seen_keys.add(key)

    rows_to_write: list[list[str]] = []
    today_str = now_ts[:10]
    for r in all_recs[:top]:
        key = (today_str, r["ticker"], r["strategy"], f"{r['strike']:.2f}")
        if key in seen_keys:
            continue
        thesis = (
            f"Market scan: {r['strategy']} on {r['ticker']} @ ${r['strike']:.2f} strike  "
            f"DTE={r['dte']}  underlying=${r['price']:.2f}  "
            f"IV={r['iv_rank']:.0f}%  HV30={r['hv30']:.0f}%  "
            f"breakeven=${r['breakeven']:.2f}"
        )
        row = S.OptionRecommendationRow(
            date=now_ts,
            source="market_scan",
            account="watchlist",
            ticker=r["ticker"],
            strategy=r["strategy"],
            right=r["right"],
            strike=r["strike"],
            expiry=r["expiry"],
            premium_per_share=r["premium_per_share"],
            delta=r.get("delta", 0),
            annual_yield_pct=r["annual_yield_pct"],
            breakeven=r["breakeven"],
            cash_required=r["cash_required"],
            iv_rank=r["iv_rank"],
            thesis_confidence=0.65,
            thesis=thesis,
            status="NEW",
        )
        rows_to_write.append(row.to_row())
        seen_keys.add(key)

    if rows_to_write:
        sh.append_rows(client, S.OptionRecommendationRow.TAB_NAME, rows_to_write)
        logger.info(f"\n→ Wrote {len(rows_to_write)} new opportunities to option_recommendations")
    else:
        logger.info("\n→ All results already in sheet, nothing new to write")

    return all_recs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry",    action="store_true", help="Print results, no sheet write")
    ap.add_argument("--top",   type=int, default=25, help="Max rows to write (default 25)")
    ap.add_argument("--no-live-wsb", action="store_true", help="Skip live Reddit WSB fetch")
    args = ap.parse_args()

    logger = _setup_logging()
    logger.info("=== market-scan start ===")

    result = run_scan(
        dry=args.dry,
        top=args.top,
        use_wsb_live=not args.no_live_wsb,
        logger=logger,
    )

    logger.info(f"=== market-scan done — {len(result)} total candidates ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
