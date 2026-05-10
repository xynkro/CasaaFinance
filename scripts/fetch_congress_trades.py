"""fetch_congress_trades.py — daily CapitolTrades scrape → congress_trades sheet.

Pulls new Congressional trade filings from CapitolTrades.com, dedupes
against existing rows by `filing_id`, and appends the new ones.

Schedule: daily 06:30 SGT (= 22:30 UTC) Mon-Fri via
  .github/workflows/fetch-congress-trades.yml

STOCK Act mandates filings within 45 days of trade execution. Daily
polling is more than enough — there's no benefit to going faster.

Usage:
  python scripts/fetch_congress_trades.py            # write
  python scripts/fetch_congress_trades.py --dry      # print, no sheet write
  python scripts/fetch_congress_trades.py --days 30  # widen lookback for backfill
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sync import load_env  # noqa: E402
from src import sheets as sh   # noqa: E402
from src import schema as S    # noqa: E402
from src import capitoltrades as ct  # noqa: E402

log = logging.getLogger(__name__)

# Default lookback: last 14 days. The screener only uses trades from the
# last 60 days, so even on a fresh deployment 14d catches new filings;
# subsequent runs only need a 7d window since we dedupe by filing_id.
DEFAULT_LOOKBACK_DAYS = 14


def _setup_logging() -> logging.Logger:
    log_path = ROOT / ".state" / "fetch-congress-trades.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("fetch-congress-trades")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(log_path)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
        sh_ = logging.StreamHandler()
        sh_.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(sh_)
    return logger


def _load_existing_filing_ids(client) -> set[str]:
    """Read existing filing_ids from congress_trades sheet for dedup."""
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.CongressTradeRow.TAB_NAME)
    except Exception:
        return set()
    rows = ws.get_all_values()
    if len(rows) < 2:
        return set()
    hdr = rows[0]
    try:
        c = hdr.index("filing_id")
    except ValueError:
        return set()
    return {r[c] for r in rows[1:] if len(r) > c and r[c]}


def _row_from_trade(t: dict) -> S.CongressTradeRow:
    """Convert raw scraper dict → typed CongressTradeRow.

    `committees` is left as an empty JSON array for v1 — populating it
    requires per-politician page scrapes which we'll add in v1.5 once
    we know the screener uses committee weighting effectively.
    """
    return S.CongressTradeRow(
        audit_ts=S.now_sgt_iso(),
        filing_id=t.get("filing_id", ""),
        politician_id=t.get("politician_id", ""),
        politician_name=t.get("politician_name", ""),
        party=t.get("party", ""),
        chamber=t.get("chamber", ""),
        committees="[]",  # JSON empty — populated in v1.5
        ticker=t.get("ticker", ""),
        issuer_name=t.get("issuer_name", ""),
        transaction_date=t.get("transaction_date", ""),
        filing_date=t.get("filing_date", ""),
        transaction_type=t.get("transaction_type", ""),
        amount_min=float(t.get("amount_min", 0) or 0),
        amount_max=float(t.get("amount_max", 0) or 0),
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry", action="store_true", help="Print plan, no sheet write")
    p.add_argument("--days", type=int, default=DEFAULT_LOOKBACK_DAYS,
                   help=f"Lookback window in days (default {DEFAULT_LOOKBACK_DAYS})")
    p.add_argument("--max-pages", type=int, default=30,
                   help="Max pages to scrape (default 30, ~12 rows each)")
    args = p.parse_args()

    logger = _setup_logging()
    logger.info(f"fetch_congress_trades start (dry={args.dry}, days={args.days})")

    since = (date.today() - timedelta(days=args.days)).isoformat()
    logger.info(f"Scraping CapitolTrades since {since} (max {args.max_pages} pages)")

    trades = ct.fetch_recent_trades(since, max_pages=args.max_pages)
    logger.info(f"  · scraped {len(trades)} trades")

    if not trades:
        logger.info("Nothing scraped — exiting")
        return 0

    # Build typed rows
    rows = [_row_from_trade(t) for t in trades]

    if args.dry:
        logger.info("Top 15 most-recent trades scraped:")
        for r in rows[:15]:
            logger.info(
                f"  {r.filing_date}  {r.politician_name[:20]:20s} "
                f"{r.party[:1]}-{r.chamber[:5]:5s}  "
                f"{r.ticker:6s} {r.issuer_name[:30]:30s}  "
                f"{r.transaction_type:5s}  ${r.amount_min:>10,.0f}-${r.amount_max:>11,.0f}"
            )
        logger.info("[DRY] no writes performed")
        return 0

    load_env()
    client = sh.authenticate()
    sh.ensure_headers(client, S.CongressTradeRow.TAB_NAME, S.CongressTradeRow.HEADERS)

    # Dedup against existing filing_ids
    existing = _load_existing_filing_ids(client)
    new_rows = [r for r in rows if r.filing_id not in existing]
    skipped = len(rows) - len(new_rows)
    logger.info(f"  · {len(new_rows)} new, {skipped} already in sheet (deduped)")

    if not new_rows:
        logger.info("No new filings to write")
        return 0

    sh.append_rows(client, S.CongressTradeRow.TAB_NAME, [r.to_row() for r in new_rows])
    logger.info(f"  ✓ wrote {len(new_rows)} rows to {S.CongressTradeRow.TAB_NAME}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
