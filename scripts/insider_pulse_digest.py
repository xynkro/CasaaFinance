"""insider_pulse_digest.py — daily Telegram digest for the Insider Trading topic.

Reads the day's confluence signals + recent CapitolTrades filings + flagged
unmapped recipients, and sends one consolidated digest message to the
"Insider Trading" topic in the Finance & Trading supergroup.

Schedule: 23:15 UTC = 07:15 SGT, Mon-Fri (after the screener at 07:00,
before the daily brief at 07:43).

If TELEGRAM_INSIDER_TRADING_TOPIC is unset (topic not yet created /
secret not yet added), this gracefully no-ops.

Usage:
  python scripts/insider_pulse_digest.py            # send
  python scripts/insider_pulse_digest.py --dry      # print, no send
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sync import load_env  # noqa: E402
from src import sheets as sh   # noqa: E402
from src import schema as S    # noqa: E402
from src import telegram as tg  # noqa: E402

log = logging.getLogger(__name__)

PWA_URL = "https://xynkro.github.io/CasaaFinance/"
TOP_PICKS = 3
TOP_FILINGS = 5
TOP_UNMAPPED = 3

# Filings older than this don't appear in the digest — kept fresh.
FILING_LOOKBACK_DAYS = 3
# Unmapped review entries flagged in the last N days
UNMAPPED_LOOKBACK_DAYS = 7


def _setup_logging() -> logging.Logger:
    log_path = ROOT / ".state" / "insider-pulse-digest.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("insider-pulse-digest")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(log_path)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
        sh_ = logging.StreamHandler()
        sh_.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(sh_)
    return logger


def _read_today_signals(client, today_iso: str) -> list[dict]:
    """Read top-N gov_confluence_signals rows for today, sorted by score."""
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.GovConfluenceSignalRow.TAB_NAME)
    except Exception:
        return []
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []
    hdr = rows[0]
    cols = {h: i for i, h in enumerate(hdr)}
    needed = ["date", "ticker", "confluence_score", "tier", "recommended_strategy",
              "recommended_action", "thesis_oneliner"]
    if not all(c in cols for c in needed):
        log.warning("gov_confluence_signals schema mismatch")
        return []

    today_rows = []
    for r in rows[1:]:
        if len(r) <= cols["date"]:
            continue
        if r[cols["date"]] != today_iso:
            continue
        try:
            score = float(r[cols["confluence_score"]] or 0)
        except (TypeError, ValueError):
            continue
        today_rows.append({
            "ticker": r[cols["ticker"]],
            "score": score,
            "tier": r[cols["tier"]],
            "strategy": r[cols["recommended_strategy"]],
            "action": r[cols["recommended_action"]],
            "thesis": r[cols["thesis_oneliner"]],
        })
    today_rows.sort(key=lambda d: d["score"], reverse=True)
    return today_rows[:TOP_PICKS]


def _read_recent_filings(client, today: date) -> list[dict]:
    """Top recent CapitolTrades filings sorted by amount_max descending."""
    cutoff = (today - timedelta(days=FILING_LOOKBACK_DAYS)).isoformat()
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.CongressTradeRow.TAB_NAME)
    except Exception:
        return []
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []
    hdr = rows[0]
    cols = {h: i for i, h in enumerate(hdr)}
    needed = ["filing_date", "politician_name", "party", "chamber",
              "ticker", "transaction_type", "amount_min", "amount_max"]
    if not all(c in cols for c in needed):
        return []

    out = []
    for r in rows[1:]:
        if len(r) <= cols["filing_date"]:
            continue
        if r[cols["filing_date"]][:10] < cutoff:
            continue
        try:
            amt_max = float(r[cols["amount_max"]] or 0)
            amt_min = float(r[cols["amount_min"]] or 0)
        except (TypeError, ValueError):
            continue
        out.append({
            "filing_date": r[cols["filing_date"]],
            "politician_name": r[cols["politician_name"]],
            "party": r[cols["party"]],
            "chamber": r[cols["chamber"]],
            "ticker": r[cols["ticker"]],
            "transaction_type": r[cols["transaction_type"]],
            "amount_min": amt_min,
            "amount_max": amt_max,
        })
    out.sort(key=lambda d: d["amount_max"], reverse=True)
    return out[:TOP_FILINGS]


def _read_recent_unmapped(client, today: date) -> list[dict]:
    """Recent unmapped recipients (flagged in last 7d) above review threshold."""
    cutoff = (today - timedelta(days=UNMAPPED_LOOKBACK_DAYS)).isoformat()
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.GovUnmappedRecipientRow.TAB_NAME)
    except Exception:
        return []
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []
    hdr = rows[0]
    cols = {h: i for i, h in enumerate(hdr)}
    needed = ["last_seen_ts", "recipient_name", "total_award_amount"]
    if not all(c in cols for c in needed):
        return []

    out = []
    for r in rows[1:]:
        if len(r) <= cols["last_seen_ts"]:
            continue
        ts = (r[cols["last_seen_ts"]] or "")[:10]
        if ts < cutoff:
            continue
        try:
            amt = float(r[cols["total_award_amount"]] or 0)
        except (TypeError, ValueError):
            continue
        out.append({
            "recipient_name": r[cols["recipient_name"]],
            "total_amount": amt,
        })
    out.sort(key=lambda d: d["total_amount"], reverse=True)
    return out[:TOP_UNMAPPED]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry", action="store_true", help="Print plan, no Telegram send")
    args = p.parse_args()

    logger = _setup_logging()
    logger.info(f"insider_pulse_digest start (dry={args.dry})")

    # Fallback: when Insider Trading topic isn't configured yet, route
    # the digest to Multi Day Swing so it still reaches Telegram.
    use_fallback = tg.INSIDER_TRADING_TOPIC is None
    if use_fallback and not args.dry:
        logger.info(
            "TELEGRAM_INSIDER_TRADING_TOPIC not configured — "
            "falling back to Multi Day Swing topic"
        )

    load_env()
    client = sh.authenticate()
    today = date.today()
    today_iso = today.isoformat()

    picks = _read_today_signals(client, today_iso)
    filings = _read_recent_filings(client, today)
    unmapped = _read_recent_unmapped(client, today)

    logger.info(
        f"  picks={len(picks)} filings={len(filings)} unmapped_flagged={len(unmapped)}"
    )

    if args.dry:
        logger.info("[DRY] would send digest:")
        logger.info(f"  picks: {picks[:3]}")
        logger.info(f"  filings: {filings[:5]}")
        logger.info(f"  unmapped: {unmapped[:3]}")
        return 0

    try:
        if use_fallback:
            # Route to Multi Day Swing topic as fallback
            result = tg.ping_insider_pulse(
                date=today_iso,
                confluence_picks=picks,
                capitol_filings=filings,
                unmapped=unmapped,
                pwa_url=PWA_URL,
                fallback_topic=tg.MULTI_DAY_SWING_TOPIC,
            )
        else:
            result = tg.ping_insider_pulse(
                date=today_iso,
                confluence_picks=picks,
                capitol_filings=filings,
                unmapped=unmapped,
                pwa_url=PWA_URL,
            )
        if result.get("skipped"):
            logger.info(f"  · {result['skipped']}")
        else:
            topic = "Multi Day Swing (fallback)" if use_fallback else "Insider Trading"
            logger.info(f"  ✓ digest sent to {topic} topic")
    except Exception as e:
        logger.error(f"  ✗ digest send failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
