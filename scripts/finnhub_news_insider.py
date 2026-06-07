"""
finnhub_news_insider.py — per-ticker news + insider transactions pull.

Two outputs in one script (single auth, single sheet client):

1. news_sentiment — last 3 days of company news per portfolio + watchlist
   ticker. Free tier doesn't have Finnhub's premium ML sentiment, so we
   run a cheap keyword heuristic at write time. Brain (Opus) does the
   actual semantic understanding when reading rows.

2. insider_transactions — SEC Form 4 filings via Finnhub. Default range
   is last ~90 days. UPSERT by SEC filing id so re-pulls dedupe.

Schedule: 4× daily (pre-mkt 13:30 UTC, mid-day 17:00, close 21:00, post-
close 02:00 UTC). News is the most time-sensitive — sentiment changes
intra-day matter for the next Daily Brief.

Universe: portfolio (positions_*) + watchlist.yaml. ~84 unique tickers.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.logging_util import setup_logging  # noqa: E402

from src.sync import load_env  # noqa: E402
from src import sheets as sh   # noqa: E402
from src import schema as S    # noqa: E402

FH_BASE = "https://finnhub.io/api/v1"
NEWS_LOOKBACK_DAYS = 3
INSIDER_LOOKBACK_DAYS = 90  # ~Finnhub default

# Heuristic sentiment classifier. Each keyword carries a score; sum &
# clamp to [-1, +1]. The brain reads the raw text + this score and does
# real reasoning — heuristic just prioritises what to surface in the
# brief. Skewed slightly negative because financial news tends to overuse
# "could", "may", "uncertainty" — we want a row to mostly stay neutral
# unless explicitly positive/negative wording.
POSITIVE_KEYWORDS = {
    # earnings beat language
    "beat": 0.4, "beats": 0.4, "exceeds": 0.4, "topped": 0.3, "outperform": 0.4,
    "raised guidance": 0.6, "raises guidance": 0.6, "guides higher": 0.5,
    "record high": 0.5, "all-time high": 0.5,
    # ratings
    "upgrade": 0.4, "upgrades": 0.4, "buy rating": 0.3, "outperform rating": 0.3,
    "price target raised": 0.4, "target raised": 0.3,
    # corporate actions
    "buyback": 0.3, "share repurchase": 0.3, "dividend increase": 0.4,
    "approved": 0.2, "fda approval": 0.7,
    # general up
    "surge": 0.3, "soar": 0.4, "rally": 0.2, "jump": 0.2, "gains": 0.1,
    "profit jumps": 0.4, "revenue beat": 0.5,
}
NEGATIVE_KEYWORDS = {
    # earnings miss
    "miss": -0.4, "misses": -0.4, "missed": -0.4, "shortfall": -0.4,
    "lowered guidance": -0.6, "lowers guidance": -0.6, "guides lower": -0.5,
    "cuts forecast": -0.5, "cut forecast": -0.5,
    # ratings
    "downgrade": -0.4, "downgrades": -0.4, "sell rating": -0.4,
    "price target cut": -0.4, "target lowered": -0.3, "target cut": -0.3,
    # corporate stress
    "layoffs": -0.4, "layoff": -0.4, "restructuring": -0.3, "bankruptcy": -0.9,
    "lawsuit": -0.3, "investigation": -0.4, "subpoena": -0.5, "fraud": -0.7,
    "recall": -0.4, "fda rejection": -0.7,
    # general down
    "plunge": -0.4, "tumble": -0.4, "slump": -0.3, "crash": -0.5,
    "warning": -0.3, "cuts jobs": -0.3, "fired": -0.2, "resigns": -0.3,
    "weak": -0.2, "concern": -0.2,
}

NEUTRAL_THRESHOLD = 0.15  # |score| < this → neutral label


def _fh_get(path: str, params: dict, logger: logging.Logger,
            retries: int = 1) -> dict | list | None:
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY not set")
    url = f"{FH_BASE}/{path}"
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params={**params, "token": api_key}, timeout=15)
        except Exception as e:
            logger.warning(f"  {path} network: {e}")
            time.sleep(2)
            continue
        if r.status_code == 429:
            logger.warning(f"  {path} rate-limited; sleeping 30s")
            time.sleep(30)
            continue
        if r.status_code != 200:
            logger.warning(f"  {path} http {r.status_code}: {r.text[:120]}")
            time.sleep(2)
            continue
        try:
            return r.json()
        except Exception as e:
            logger.warning(f"  {path} json: {e}")
            return None
    return None


# --- universe ---------------------------------------------------------------

def read_universe(client, logger: logging.Logger) -> set[str]:
    out: set[str] = set()
    for tab in ("positions_caspar", "positions_sarah"):
        try:
            ss = sh._open_sheet(client)
            rows = ss.worksheet(tab).get_all_values()
        except Exception as e:
            logger.warning(f"  {tab}: {e}")
            continue
        if len(rows) <= 1:
            continue
        last_date = max(((r[0] or "")[:10] for r in rows[1:]), default="")
        for r in rows[1:]:
            if r and (r[0] or "")[:10] == last_date:
                t = (r[1] or "").strip().upper()
                if t and t.replace(".", "").isalnum():
                    out.add(t)
    try:
        from src.watchlist import get_universe
        u = get_universe(client)
        for ts in u.values():
            out.update(ts)
    except Exception as e:
        logger.warning(f"  watchlist: {e}")
    return out


# --- sentiment heuristic ----------------------------------------------------

def score_sentiment(text: str) -> tuple[float, str]:
    """Return (score in [-1, +1], label). Sums positive/negative keyword hits."""
    if not text:
        return 0.0, "neutral"
    t = text.lower()
    score = 0.0
    # Use word-boundary matching to avoid spurious sub-string hits
    # ("buyback" shouldn't trigger on "buyer side"). Quick & cheap.
    for kw, weight in POSITIVE_KEYWORDS.items():
        if re.search(rf"\b{re.escape(kw)}\b", t):
            score += weight
    for kw, weight in NEGATIVE_KEYWORDS.items():
        if re.search(rf"\b{re.escape(kw)}\b", t):
            score += weight  # weights already negative
    score = max(-1.0, min(1.0, score))
    if score >= NEUTRAL_THRESHOLD:
        label = "positive"
    elif score <= -NEUTRAL_THRESHOLD:
        label = "negative"
    else:
        label = "neutral"
    return round(score, 3), label


# --- news -------------------------------------------------------------------

def pull_news(tickers: set[str], logger: logging.Logger) -> list[S.NewsSentimentRow]:
    """Pull last NEWS_LOOKBACK_DAYS of company news per ticker."""
    end = datetime.utcnow().date()
    start = end - timedelta(days=NEWS_LOOKBACK_DAYS)
    rows: list[S.NewsSentimentRow] = []
    now_sgt = S.now_sgt_iso()
    sgt_offset = timezone(timedelta(hours=8))
    for i, t in enumerate(sorted(tickers)):
        # Light pacing — Finnhub free tier = 60 req/min. 84 tickers * 1 call
        # = 84 calls in ~84 seconds at 1/sec. Safe.
        time.sleep(0.5)
        payload = _fh_get(
            "company-news",
            {"symbol": t, "from": start.isoformat(), "to": end.isoformat()},
            logger,
        )
        if not isinstance(payload, list):
            continue
        for art in payload:
            try:
                dt_unix = int(art.get("datetime") or 0)
                if dt_unix == 0:
                    continue
                dt = datetime.fromtimestamp(dt_unix, tz=sgt_offset).strftime("%Y-%m-%dT%H%M%S")
                headline = str(art.get("headline") or "")
                summary = str(art.get("summary") or "")
                score, label = score_sentiment(f"{headline} {summary}")
                rows.append(S.NewsSentimentRow(
                    id=str(art.get("id") or ""),
                    datetime=dt,
                    ticker=t,
                    headline=headline,
                    summary=summary,
                    source=str(art.get("source") or ""),
                    url=str(art.get("url") or ""),
                    sentiment_score=score,
                    sentiment_label=label,
                    category=str(art.get("category") or ""),
                    updated_at=now_sgt,
                ))
            except (ValueError, TypeError):
                continue
        if (i + 1) % 20 == 0:
            logger.info(f"  news progress: {i+1}/{len(tickers)} tickers, {len(rows)} rows")
    logger.info(f"  news: {len(rows)} articles across {len(tickers)} tickers")
    return rows


def upsert_news(client, rows: list[S.NewsSentimentRow], logger: logging.Logger) -> int:
    """UPSERT by article id. Cap retained history at last 14 days to keep
    the tab from growing unbounded."""
    sh.ensure_headers(client, S.NewsSentimentRow.TAB_NAME, S.NewsSentimentRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.NewsSentimentRow.TAB_NAME)
    existing = ws.get_all_values()
    hdr = existing[0] if existing else list(S.NewsSentimentRow.HEADERS)

    new_keys = {r.id for r in rows if r.id}
    cutoff_dt = (datetime.utcnow() - timedelta(days=14)).strftime("%Y-%m-%dT")
    keep: list[list[str]] = [hdr]
    dropped_dupe = 0
    dropped_old = 0
    for r in existing[1:]:
        if not r:
            continue
        rid = r[0] if r else ""
        rdt = r[1] if len(r) > 1 else ""
        if rid in new_keys:
            dropped_dupe += 1
            continue
        if rdt and rdt < cutoff_dt:
            dropped_old += 1
            continue
        keep.append(r)
    keep.extend(r.to_row() for r in rows)

    ws.clear()
    ws.update(values=keep, range_name="A1", value_input_option="USER_ENTERED")
    logger.info(
        f"✓ news upserted: {len(rows)} new (dropped {dropped_dupe} dupe, "
        f"{dropped_old} >14d)"
    )
    return len(rows)


# --- insider ----------------------------------------------------------------

# Map Finnhub's transactionCode → our "side" label. Codes per SEC Form 4.
TRANSACTION_CODE_SIDE = {
    "P": "buy",        # Open market purchase
    "S": "sell",       # Open market sale
    "A": "grant",      # Award/grant
    "M": "exercise",   # Exercise of options
    "G": "gift",
    "D": "issuer_sale",
    "F": "tax_payment",
    "I": "discretionary",
    "J": "other",
    "X": "exercise_in_money",
}


def pull_insider(tickers: set[str], logger: logging.Logger) -> list[S.InsiderTransactionRow]:
    rows: list[S.InsiderTransactionRow] = []
    now_sgt = S.now_sgt_iso()
    end = datetime.utcnow().date()
    start = end - timedelta(days=INSIDER_LOOKBACK_DAYS)
    for i, t in enumerate(sorted(tickers)):
        time.sleep(0.5)
        payload = _fh_get(
            "stock/insider-transactions",
            {"symbol": t, "from": start.isoformat(), "to": end.isoformat()},
            logger,
        )
        if not isinstance(payload, dict):
            continue
        data = payload.get("data") or []
        for tx in data:
            try:
                code = str(tx.get("transactionCode") or "").upper()
                side = TRANSACTION_CODE_SIDE.get(code, "other")
                shares_signed = float(tx.get("change") or 0)  # +ve acquired, -ve disposed
                price = float(tx.get("transactionPrice") or 0)
                value = abs(shares_signed) * price
                rows.append(S.InsiderTransactionRow(
                    id=str(tx.get("id") or "") + f"_{tx.get('name','')}_{tx.get('change',0)}",
                    transaction_date=str(tx.get("transactionDate") or ""),
                    filing_date=str(tx.get("filingDate") or ""),
                    ticker=t,
                    name=str(tx.get("name") or ""),
                    shares=shares_signed,
                    transaction_code=code,
                    side=side,
                    transaction_price=price,
                    value_usd=value,
                    is_derivative=bool(tx.get("isDerivative")),
                    shares_after=float(tx.get("share") or 0),
                    updated_at=now_sgt,
                ))
            except (ValueError, TypeError):
                continue
        if (i + 1) % 20 == 0:
            logger.info(f"  insider progress: {i+1}/{len(tickers)} tickers, {len(rows)} rows")
    logger.info(f"  insider: {len(rows)} filings across {len(tickers)} tickers")
    return rows


def upsert_insider(client, rows: list[S.InsiderTransactionRow], logger: logging.Logger) -> int:
    """UPSERT by composite id. Cap history at 90 days (matches lookback)."""
    sh.ensure_headers(client, S.InsiderTransactionRow.TAB_NAME, S.InsiderTransactionRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.InsiderTransactionRow.TAB_NAME)
    existing = ws.get_all_values()
    hdr = existing[0] if existing else list(S.InsiderTransactionRow.HEADERS)

    new_keys = {r.id for r in rows}
    cutoff = (datetime.utcnow() - timedelta(days=INSIDER_LOOKBACK_DAYS + 7)).date().isoformat()
    keep: list[list[str]] = [hdr]
    dropped_dupe = 0
    dropped_old = 0
    for r in existing[1:]:
        if not r:
            continue
        rid = r[0] if r else ""
        rdate = r[1] if len(r) > 1 else ""  # transaction_date
        if rid in new_keys:
            dropped_dupe += 1
            continue
        if rdate and rdate < cutoff:
            dropped_old += 1
            continue
        keep.append(r)
    keep.extend(r.to_row() for r in rows)

    ws.clear()
    ws.update(values=keep, range_name="A1", value_input_option="USER_ENTERED")
    logger.info(
        f"✓ insider upserted: {len(rows)} new (dropped {dropped_dupe} dupe, "
        f"{dropped_old} >90d)"
    )
    return len(rows)


# --- main -------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry", action="store_true")
    p.add_argument("--news-only", action="store_true")
    p.add_argument("--insider-only", action="store_true")
    p.add_argument("--limit", type=int, default=0,
                   help="Cap universe size for quick testing (0 = no cap)")
    args = p.parse_args()

    logger = setup_logging("finnhub-news-insider")
    logger.info(f"finnhub_news_insider start (dry={args.dry})")

    load_env()
    client = sh.authenticate()
    universe = read_universe(client, logger)
    if args.limit > 0:
        universe = set(sorted(universe)[: args.limit])
    logger.info(f"  Universe: {len(universe)} tickers")

    news_rows: list[S.NewsSentimentRow] = []
    insider_rows: list[S.InsiderTransactionRow] = []

    if not args.insider_only:
        news_rows = pull_news(universe, logger)
    if not args.news_only:
        insider_rows = pull_insider(universe, logger)

    if args.dry:
        logger.info("--- news preview ---")
        for r in news_rows[:5]:
            logger.info(
                f"  {r.datetime} {r.ticker:6} {r.sentiment_label:8} {r.sentiment_score:+.2f} "
                f"{r.headline[:80]}"
            )
        logger.info("--- insider preview ---")
        for r in insider_rows[:5]:
            logger.info(
                f"  {r.transaction_date} {r.ticker:6} {r.side:9} "
                f"{r.shares:+.0f} sh @ ${r.transaction_price:.2f}  ({r.name[:30]})"
            )
        return 0

    if news_rows:
        upsert_news(client, news_rows, logger)
    if insider_rows:
        upsert_insider(client, insider_rows, logger)

    logger.info("finnhub_news_insider done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
