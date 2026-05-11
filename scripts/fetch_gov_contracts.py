"""fetch_gov_contracts.py — daily USAspending pull → gov_contracts sheet.

Pulls yesterday's federal contract + IDV awards from USAspending.gov,
resolves recipient names to publicly-traded tickers via the manual seed
map, and appends to the gov_contracts sheet. Auto-flags unmapped
recipients above $5M to gov_unmapped_recipients for weekly review.

Schedule: daily 06:00 SGT (= 22:00 UTC) Mon-Fri via
  .github/workflows/fetch-gov-contracts.yml

Usage:
  python scripts/fetch_gov_contracts.py            # write
  python scripts/fetch_gov_contracts.py --dry      # print, no sheet write
  python scripts/fetch_gov_contracts.py --days 7   # backfill last 7 days
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sync import load_env  # noqa: E402
from src import sheets as sh   # noqa: E402
from src import schema as S    # noqa: E402
from src import usaspending as us  # noqa: E402
from src.recipient_ticker import normalize, resolve  # noqa: E402

log = logging.getLogger(__name__)

UNMAPPED_FLAG_THRESHOLD = 5_000_000  # $5M+


def _setup_logging() -> logging.Logger:
    log_path = ROOT / ".state" / "fetch-gov-contracts.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("fetch-gov-contracts")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(log_path)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
        sh_ = logging.StreamHandler()
        sh_.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(sh_)
    return logger


def _row_from_award(award: dict, ticker: str) -> S.GovContractRow:
    """Convert a raw USAspending award dict to a typed GovContractRow."""
    raw_name = us.get_recipient_name(award)
    return S.GovContractRow(
        audit_ts=S.now_sgt_iso(),
        award_id=us.get_award_id(award),
        action_date=us.get_action_date(award),
        recipient_name=raw_name,
        # We don't have a parent_recipient field directly — for now, store
        # the same as recipient_name. A future enhancement could query the
        # /recipient/{id} endpoint to walk parent relationships.
        parent_recipient_name=raw_name,
        ticker=ticker,
        award_amount=us.get_award_amount(award),
        tcv=us.get_total_outlays(award),
        agency=us.get_agency(award),
        naics_code=us.get_naics_code(award),
        naics_description=us.get_naics_description(award),
        period_start=us.get_period_start(award),
        period_end=us.get_period_end(award),
        place_of_performance_state=us.get_place_state(award),
        description=us.get_description(award),
    )


def _aggregate_unmapped(awards: list[dict]) -> list[S.GovUnmappedRecipientRow]:
    """Group unmapped awards by recipient + flag those crossing $5M total."""
    bucket: dict[str, dict] = defaultdict(lambda: {
        "total": 0.0, "count": 0, "biggest_id": "", "biggest_amount": 0.0,
        "raw_name": "", "agency": "",
    })
    for a in awards:
        raw_name = us.get_recipient_name(a)
        if not raw_name:
            continue
        norm = normalize(raw_name)
        if not norm:
            continue
        if resolve(raw_name):
            continue  # already mapped, skip
        amount = us.get_award_amount(a)
        b = bucket[norm]
        b["raw_name"] = b["raw_name"] or raw_name
        b["agency"] = b["agency"] or us.get_agency(a)
        b["total"] += amount
        b["count"] += 1
        if amount > b["biggest_amount"]:
            b["biggest_amount"] = amount
            b["biggest_id"] = us.get_award_id(a)

    now_iso = S.now_sgt_iso()
    out: list[S.GovUnmappedRecipientRow] = []
    for norm_name, b in bucket.items():
        if b["total"] < UNMAPPED_FLAG_THRESHOLD:
            continue
        out.append(S.GovUnmappedRecipientRow(
            first_seen_ts=now_iso,
            recipient_name=b["raw_name"],
            recipient_name_normalized=norm_name,
            total_award_amount=b["total"],
            contract_count=b["count"],
            biggest_award_id=b["biggest_id"],
            agency=b["agency"],
            last_seen_ts=now_iso,
        ))
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry", action="store_true", help="Print plan, no sheet write")
    p.add_argument("--days", type=int, default=7,
                   help="Number of trailing days to fetch (default 7 = handles weekends + "
                        "1-2 day outages safely thanks to award_id dedup; bump to 14+ for backfill)")
    p.add_argument("--end", type=str, default=None,
                   help="ISO end date (YYYY-MM-DD); default = yesterday SGT")
    args = p.parse_args()

    logger = _setup_logging()
    logger.info(f"fetch_gov_contracts start (dry={args.dry}, days={args.days})")

    end_dt = (
        datetime.strptime(args.end, "%Y-%m-%d").date()
        if args.end else
        date.today() - timedelta(days=1)
    )
    start_dt = end_dt - timedelta(days=args.days - 1)
    start_iso = start_dt.isoformat()
    end_iso = end_dt.isoformat()

    logger.info(f"Fetching {start_iso}..{end_iso}")
    awards = us.fetch_awards(start_iso, end_iso)
    logger.info(f"  · pulled {len(awards)} awards")

    load_env()  # only matters if we'll touch sheets; harmless in --dry mode

    # Always ensure the sheet exists with headers, even on 0-award days.
    # Otherwise downstream readers (screen_gov_confluence) error out and
    # silent gaps look like the strategy is broken when really it's just
    # quiet (e.g. weekend day with no contract awards).
    if not args.dry:
        client = sh.authenticate()
        sh.ensure_headers(client, S.GovContractRow.TAB_NAME, S.GovContractRow.HEADERS)
        sh.ensure_headers(client, S.GovUnmappedRecipientRow.TAB_NAME, S.GovUnmappedRecipientRow.HEADERS)

    if not awards:
        logger.info("No awards returned — sheet headers ensured but no rows written")
        return 0

    # Resolve tickers and build rows
    rows: list[S.GovContractRow] = []
    mapped = 0
    for a in awards:
        ticker = resolve(us.get_recipient_name(a))
        if ticker:
            mapped += 1
        rows.append(_row_from_award(a, ticker))
    logger.info(f"  · {mapped}/{len(rows)} awards resolved to tickers ({100*mapped/len(rows):.1f}%)")

    # Build unmapped review queue
    unmapped_rows = _aggregate_unmapped(awards)
    logger.info(f"  · {len(unmapped_rows)} unmapped recipients above ${UNMAPPED_FLAG_THRESHOLD/1e6:.0f}M flagged for review")

    if args.dry:
        # Show top 10 mapped + top 5 unmapped flags
        mapped_rows = sorted(
            [r for r in rows if r.ticker],
            key=lambda r: r.award_amount, reverse=True,
        )[:10]
        logger.info("Top 10 mapped awards (by amount):")
        for r in mapped_rows:
            logger.info(
                f"  ${r.award_amount:>15,.0f}  {r.ticker:6s}  {r.recipient_name[:40]:40s}  {r.naics_description[:30]}"
            )
        if unmapped_rows:
            logger.info("Top unmapped (review for inclusion):")
            for u in sorted(unmapped_rows, key=lambda u: u.total_award_amount, reverse=True)[:5]:
                logger.info(
                    f"  ${u.total_award_amount:>15,.0f}  {u.recipient_name[:50]:50s}  ({u.contract_count} contracts)"
                )
        logger.info("[DRY] no writes performed")
        return 0

    # Dedup against existing award_id rows so overlapping 7-day windows
    # don't duplicate. Read existing sheet once, skip rows whose award_id
    # we've already written.
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.GovContractRow.TAB_NAME)
    existing = ws.get_all_values()
    existing_ids: set[str] = set()
    if len(existing) > 1:
        hdr = existing[0]
        try:
            c_aid = hdr.index("award_id")
            for r in existing[1:]:
                if len(r) > c_aid and r[c_aid]:
                    existing_ids.add(r[c_aid])
        except ValueError:
            pass  # legacy sheet without award_id col — fall through to no-dedup

    new_rows = [r for r in rows if r.award_id not in existing_ids]
    skipped = len(rows) - len(new_rows)
    if skipped:
        logger.info(f"  · {skipped} awards already in sheet, skipping (dedup by award_id)")

    if new_rows:
        sh.append_rows(client, S.GovContractRow.TAB_NAME, [r.to_row() for r in new_rows])
        logger.info(f"  ✓ wrote {len(new_rows)} new rows to {S.GovContractRow.TAB_NAME}")
    else:
        logger.info(f"  · all {len(rows)} awards already present — nothing new to write")

    if unmapped_rows:
        # Unmapped recipients are aggregated per-recipient per-run, not
        # per-award, so dedup by recipient_name (latest run wins for amounts).
        ws_u = ss.worksheet(S.GovUnmappedRecipientRow.TAB_NAME)
        existing_u = ws_u.get_all_values()
        existing_unmapped: set[str] = set()
        if len(existing_u) > 1:
            hdr_u = existing_u[0]
            try:
                c_name = hdr_u.index("recipient_name")
                for r in existing_u[1:]:
                    if len(r) > c_name and r[c_name]:
                        existing_unmapped.add(r[c_name])
            except ValueError:
                pass
        new_unmapped = [u for u in unmapped_rows if u.recipient_name not in existing_unmapped]
        if new_unmapped:
            sh.append_rows(client, S.GovUnmappedRecipientRow.TAB_NAME, [u.to_row() for u in new_unmapped])
            logger.info(f"  ✓ wrote {len(new_unmapped)} new unmapped rows for review")

    return 0


if __name__ == "__main__":
    sys.exit(main())
