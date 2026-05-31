#!/usr/bin/env python3
"""
growth_scan.py — the GROWTH-DISCOVERY leg of the all-rounded book.

The audit found the stock side was an afterthought: vcp/canslim only RATE the
~80-name watchlist (survivorship), so fresh momentum/growth names could never
surface — which is why the defensive rebalancer filled the vacuum with bonds.

This scanner discovers growth from a BROAD universe and ranks it on real
momentum (trend + relative strength + the technical BUY score), writing the
top names to the existing `screen_candidates` tab (source="momentum") so they
flow through the PWA + Decisions with no new plumbing. Top picks also seed
decision_queue as BUY ideas.

Universe: a FinViz momentum/growth screen (best-effort) → broad curated fallback.
Scoring: yfinance history → src.technical_score (uptrend gate + BUY score).
Recommendation only — the user executes.

Usage:
  python scripts/growth_scan.py --dry     # print ranked candidates
  python scripts/growth_scan.py           # write to sheet
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TOP_N = 10              # candidates written to screen_candidates
TOP_DECISIONS = 3       # top growth ideas seeded into decision_queue
MIN_GROWTH_SCORE = 45.0 # 0-100 floor to be surfaced

# Broad growth/momentum field — used when the FinViz screen is unavailable.
# Deliberately WIDER than the wheel watchlist: this is discovery, not rating.
GROWTH_FALLBACK_UNIVERSE: list[str] = [
    # mega-cap + semis
    "NVDA", "AMD", "AVGO", "MU", "LRCX", "KLAC", "ARM", "SMCI", "MRVL", "ON",
    "TXN", "ASML", "TSM", "QCOM", "AMAT",
    # software / cloud / security
    "MSFT", "CRM", "NOW", "PANW", "CRWD", "SNOW", "DDOG", "NET", "MDB", "ZS",
    "FTNT", "ORCL", "ADBE", "INTU",
    # internet / platforms
    "GOOGL", "META", "AMZN", "NFLX", "SHOP", "UBER", "ABNB", "SPOT", "RDDT",
    # AI / momentum / spec growth
    "PLTR", "APP", "IONQ", "RKLB", "ASTS", "TSLA", "COIN", "HOOD", "SOFI",
    "DKNG", "RBLX", "U", "NBIS", "RKLB",
    # power / energy / industrials momentum
    "GEV", "VRT", "CEG", "NEE", "FSLR", "ENPH", "NVO", "VST", "ETN",
    # healthcare / consumer growth
    "LLY", "VRTX", "REGN", "ISRG", "HIMS", "NVAX", "DECK", "CMG", "COST",
]


# ──────────────────── Pure scoring/ranking (tested) ─────────────────────────

def is_uptrend(close: float, sma50: float, sma200: float) -> bool:
    """Stage-2 uptrend: price above a rising 50 which is above the 200."""
    return close > 0 and sma50 > 0 and sma200 > 0 and close > sma50 and sma50 > sma200


def growth_score(buy_score: float, mom_3m_pct: float, rsi: float) -> float:
    """0-100 growth conviction: technical BUY score + 3-month momentum, lightly
    penalised for blow-off-overbought (RSI > 80 = chasing)."""
    base = max(0.0, min(100.0, (buy_score + 100) / 2))   # BUY score is [-100,100]
    mom = max(-15.0, min(25.0, mom_3m_pct * 0.5))         # +25% 3mo → +12.5
    overbought_pen = -8.0 if rsi >= 80 else 0.0
    return round(max(0.0, min(100.0, base + mom + overbought_pen)), 1)


def rank_candidates(cands: list[dict]) -> list[dict]:
    """Sort by growth_score desc; keep only uptrends above the floor."""
    keep = [c for c in cands if c.get("uptrend") and c.get("score", 0) >= MIN_GROWTH_SCORE]
    return sorted(keep, key=lambda c: c["score"], reverse=True)


# ──────────────────── Universe + scoring I/O ────────────────────────────────

def discover_universe(logger: logging.Logger, top_n: int = 150) -> list[str]:
    """FinViz momentum/growth screen; broad curated fallback on any failure."""
    try:
        from finvizfinance.screener.overview import Overview
        fo = Overview()
        fo.set_filter(filters_dict={
            "Option/Short": "Optionable",
            "Average Volume": "Over 500K",
            "Market Cap": "+Mid (over $2bln)",
            "200-Day Simple Moving Average": "Price above SMA200",
            "50-Day Simple Moving Average": "Price above SMA50",
            "Performance": "Quarter Up",
            "EPS growththis year": "Positive (>0%)",
        })
        df = fo.screener_view()
        if df is not None and not df.empty:
            tickers = df["Ticker"].tolist()[:top_n]
            logger.info(f"  FinViz growth screen → {len(tickers)} names")
            return tickers
        logger.warning("  FinViz returned empty — using fallback universe")
    except Exception as e:
        logger.warning(f"  FinViz unavailable ({e}) — using fallback universe")
    # de-dup the fallback, preserve order
    seen: set[str] = set()
    return [t for t in GROWTH_FALLBACK_UNIVERSE if not (t in seen or seen.add(t))]


def score_ticker(ticker: str, logger: logging.Logger) -> dict | None:
    """Fetch history, compute uptrend + growth score for one ticker."""
    import yfinance as yf
    from src.indicators import compute_indicators
    from src.technical_score import compute_scores
    try:
        hist = yf.Ticker(ticker).history(period="250d", interval="1d", auto_adjust=True)
        if hist.empty or len(hist) < 60:
            return None
        ind = compute_indicators(hist)
        if not ind:
            return None
        close = float(ind.get("close", 0) or 0)
        sma50 = float(ind.get("sma_50", 0) or 0)
        sma200 = float(ind.get("sma_200", 0) or 0)
        rsi = float(ind.get("rsi_14", 50) or 50)
        closes = hist["Close"].dropna()
        mom_3m = ((close / float(closes.iloc[-63])) - 1) * 100 if len(closes) >= 63 and close > 0 else 0.0
        buy = float(compute_scores(ind).get("BUY", 0) or 0)
        score = growth_score(buy, mom_3m, rsi)
        return {
            "ticker": ticker, "score": score, "close": round(close, 2),
            "uptrend": is_uptrend(close, sma50, sma200), "mom_3m": round(mom_3m, 1),
            "rsi": round(rsi, 0), "sma50": round(sma50, 2),
            "sector": ind.get("sector", ""),
        }
    except Exception as e:
        logger.debug(f"  {ticker}: score error — {e}")
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry", action="store_true", help="print only, no sheet write")
    ap.add_argument("--limit", type=int, default=80, help="max tickers to score")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger("growth_scan")
    logger.info("═══ Growth Discovery Scanner ═══")

    universe = discover_universe(logger)[: args.limit]
    logger.info(f"Scoring {len(universe)} names…")
    scored = []
    for i, tk in enumerate(universe):
        r = score_ticker(tk, logger)
        if r:
            scored.append(r)
        if (i + 1) % 20 == 0:
            logger.info(f"  …{i + 1}/{len(universe)}")

    ranked = rank_candidates(scored)[:TOP_N]
    logger.info(f"\nTop {len(ranked)} growth candidates:")
    for r in ranked:
        logger.info(f"  {r['ticker']:6} score {r['score']:5.1f}  3mo {r['mom_3m']:+6.1f}%  "
                    f"RSI {r['rsi']:.0f}  ${r['close']:.2f}")

    if args.dry or not ranked:
        logger.info(f"\n[{'DRY' if args.dry else 'NO-OP'}] {len(ranked)} candidates.")
        return 0

    from src.sync import load_env
    from src import sheets as sh
    from src import schema as S
    load_env()
    client = sh.authenticate()
    today = date.today().isoformat()

    sc_rows = [
        S.ScreenCandidateRow(
            date=today, source="momentum", ticker=r["ticker"], sector=r.get("sector", ""),
            score=r["score"], trigger_price=r["close"], stop_price=round(r["sma50"], 2),
            rationale=f"Momentum: 3mo {r['mom_3m']:+.0f}%, RSI {r['rsi']:.0f}, Stage-2 uptrend "
                      f"(>50>200dma). Stop ~50dma ${r['sma50']:.2f}.",
        )
        for r in ranked
    ]
    sh.ensure_headers(client, S.ScreenCandidateRow.TAB_NAME, S.ScreenCandidateRow.HEADERS)
    sh.append_rows(client, S.ScreenCandidateRow.TAB_NAME, [r.to_row() for r in sc_rows])
    logger.info(f"✓ Wrote {len(sc_rows)} momentum candidates to screen_candidates")

    # Seed the top few as BUY ideas in decision_queue.
    dq_rows = []
    for r in ranked[:TOP_DECISIONS]:
        dq_rows.append(S.DecisionRow(
            date=today, account="caspar", ticker=r["ticker"], bucket="quality_growth",
            thesis_1liner=f"Momentum growth: 3mo {r['mom_3m']:+.0f}%, Stage-2 uptrend",
            conv=3 if r["score"] < 65 else 4, entry=r["close"], target=0.0, status="watching",
            strategy="BUY_DIP", right="", strike=0.0, expiry="", premium_per_share=0.0,
            delta=0.0, annual_yield_pct=0.0, breakeven=round(r["sma50"], 2),
            cash_required=0.0, iv_rank=0.0, thesis_confidence=r["score"] / 100.0,
            thesis=f"Broad-universe momentum discovery (not the watchlist). 3-month return "
                   f"{r['mom_3m']:+.0f}%, RSI {r['rsi']:.0f}, price above a rising 50/200 dma. "
                   f"Growth offense for the all-rounded book; manage with the 50dma as the stop.",
            source="growth_scan", qty=0,
            accumulation_plan=f"Buy {r['ticker']} on a pullback toward the 50dma "
                              f"(~${r['sma50']:.2f}); cut below it.",
            gates="",
        ))
    if dq_rows:
        sh.append_rows(client, S.DecisionRow.TAB_NAME, [r.to_row() for r in dq_rows])
        logger.info(f"✓ Seeded {len(dq_rows)} growth ideas into decision_queue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
