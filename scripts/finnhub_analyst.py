"""
finnhub_analyst.py — weekly Wall Street consensus pull per ticker.

Finnhub free tier exposes `stock/recommendation` (monthly snapshots of
buy/hold/sell counts) but NOT `stock/price-target` (premium). We pull
the recommendation distribution for portfolio + watchlist tickers and
compute a weighted consensus score:

  strong_buy:  +2
  buy:         +1
  hold:         0
  sell:        -1
  strong_sell: -2

Then label:
  avg ≥ +1.5 → STRONG_BUY
  avg ≥ +0.5 → BUY
  avg ≥ -0.5 → HOLD
  avg ≥ -1.5 → SELL
  else       → STRONG_SELL

Brain reads this for:
  - WSR Full: per-position consensus + week-over-week shift detection
  - Decision card thesis anchor ("Wall St 42-buy / 4-hold / 1-sell")

Schedule: weekly Sunday 12:00 UTC (20:00 SGT) — analyst recs barely
shift week-to-week so daily refresh is wasteful.

Universe: portfolio + watchlist (~84 tickers).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.logging_util import setup_logging  # noqa: E402

from src.sync import load_env  # noqa: E402
from src import sheets as sh   # noqa: E402
from src import schema as S    # noqa: E402

FH_BASE = "https://finnhub.io/api/v1"

# Score weights (matches header docstring)
WEIGHTS = {"strongBuy": 2, "buy": 1, "hold": 0, "sell": -1, "strongSell": -2}


def _fh_get(path: str, params: dict, logger: logging.Logger,
            retries: int = 1) -> dict | list | None:
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY not set")
    for attempt in range(retries + 1):
        try:
            r = requests.get(
                f"{FH_BASE}/{path}",
                params={**params, "token": api_key},
                timeout=15,
            )
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
            return None
        try:
            return r.json()
        except Exception as e:
            logger.warning(f"  {path} json: {e}")
            return None
    return None


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


def label_for_score(score: float) -> str:
    if score >= 1.5:
        return "STRONG_BUY"
    if score >= 0.5:
        return "BUY"
    if score >= -0.5:
        return "HOLD"
    if score >= -1.5:
        return "SELL"
    return "STRONG_SELL"


def pull_consensus(tickers: set[str], logger: logging.Logger) -> list[S.AnalystConsensusRow]:
    rows: list[S.AnalystConsensusRow] = []
    now_sgt = S.now_sgt_iso()
    for i, t in enumerate(sorted(tickers)):
        time.sleep(0.5)  # 60 req/min cap
        payload = _fh_get("stock/recommendation", {"symbol": t}, logger)
        if not isinstance(payload, list) or not payload:
            continue
        # Use the LATEST period (Finnhub returns most-recent first)
        latest = payload[0]
        sb = int(latest.get("strongBuy", 0) or 0)
        b  = int(latest.get("buy", 0) or 0)
        h  = int(latest.get("hold", 0) or 0)
        s  = int(latest.get("sell", 0) or 0)
        ss_ = int(latest.get("strongSell", 0) or 0)
        total = sb + b + h + s + ss_
        if total == 0:
            continue
        score = (sb * WEIGHTS["strongBuy"] + b * WEIGHTS["buy"] + h * WEIGHTS["hold"] +
                 s * WEIGHTS["sell"] + ss_ * WEIGHTS["strongSell"]) / total
        rows.append(S.AnalystConsensusRow(
            ticker=t,
            period=str(latest.get("period") or ""),
            strong_buy_count=sb, buy_count=b, hold_count=h,
            sell_count=s, strong_sell_count=ss_,
            total_count=total,
            consensus_score=round(score, 2),
            consensus_label=label_for_score(score),
            updated_at=now_sgt,
        ))
        if (i + 1) % 20 == 0:
            logger.info(f"  progress: {i+1}/{len(tickers)} tickers, {len(rows)} rows")
    logger.info(f"  consensus: {len(rows)} tickers with analyst coverage")
    return rows


def upsert_consensus(client, rows: list[S.AnalystConsensusRow], logger: logging.Logger) -> int:
    """UPSERT keyed by ticker (latest period replaces prior)."""
    sh.ensure_headers(client, S.AnalystConsensusRow.TAB_NAME, S.AnalystConsensusRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.AnalystConsensusRow.TAB_NAME)
    existing = ws.get_all_values()
    hdr = existing[0] if existing else list(S.AnalystConsensusRow.HEADERS)

    new_keys = {r.ticker for r in rows}
    keep: list[list[str]] = [hdr]
    dropped = 0
    for r in existing[1:]:
        if not r:
            continue
        if r[0] in new_keys:
            dropped += 1
            continue
        keep.append(r)
    keep.extend(r.to_row() for r in rows)

    ws.clear()
    ws.update(values=keep, range_name="A1", value_input_option="USER_ENTERED")
    logger.info(f"✓ analyst consensus upserted: {len(rows)} (dropped {dropped} stale)")
    return len(rows)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    logger = setup_logging("finnhub-analyst")
    logger.info(f"finnhub_analyst start (dry={args.dry})")

    load_env()
    client = sh.authenticate()
    universe = read_universe(client, logger)
    if args.limit > 0:
        universe = set(sorted(universe)[: args.limit])
    logger.info(f"  Universe: {len(universe)} tickers")

    rows = pull_consensus(universe, logger)

    if args.dry:
        logger.info("--- preview ---")
        # Sort by consensus_score desc to surface most-bullish names
        rows_sorted = sorted(rows, key=lambda r: r.consensus_score, reverse=True)
        for r in rows_sorted[:10]:
            logger.info(
                f"  {r.ticker:6} {r.consensus_label:11} score={r.consensus_score:+.2f}  "
                f"SB={r.strong_buy_count} B={r.buy_count} H={r.hold_count} "
                f"S={r.sell_count} SS={r.strong_sell_count}  ({r.total_count} analysts)"
            )
        if len(rows) > 10:
            logger.info(f"  ... and {len(rows)-10} more")
        return 0

    if rows:
        upsert_consensus(client, rows, logger)
    logger.info("finnhub_analyst done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
