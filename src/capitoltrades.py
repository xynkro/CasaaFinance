"""CapitolTrades.com scraper — Congressional trade filings.

The site is server-rendered (Next.js with SSR), so plain `requests` +
`BeautifulSoup` parses cleanly. No JavaScript engine needed.

STOCK Act filings lag 7-30 days post-trade by law (45-day max), so
daily polling is plenty — we never need real-time. Each request is
rate-limited to 1/sec to be a polite citizen.

Page format: `https://www.capitoltrades.com/trades?page=N` shows ~12
data rows per page. Each row is a `<tr data-state="false">` containing
10 `<td>` cells:
  1. Politician (name + party + chamber + state, link to /politicians/<id>)
  2. Issuer (company + ticker like "AVGO:US", link to /issuers/<id>)
  3. Published date ("8 May 2026")
  4. Traded date
  5. Filed-after (days, e.g. "10")
  6. Owner ("Undisclosed", "Spouse", etc.)
  7. Type ("buy" / "sell" / "exchange")
  8. Size (range like "1K–15K", "1M–5M", "50M+")
  9. Price (single decimal)
  10. Trade-detail link (filing_id is the URL tail, e.g. /trades/20003797558)
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Iterator
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

log = logging.getLogger(__name__)

BASE = "https://www.capitoltrades.com"
TRADES_URL = f"{BASE}/trades"
USER_AGENT = "FinancePWA/1.0 (gov-confluence-strategy; research)"
RATE_LIMIT_SECONDS = 1.0
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_PAGES = 30  # ~30 × 12 rows = 360 trades — covers a busy week


# Size bucket strings → (min_usd, max_usd). 50M+ has no upper bound; we
# clamp to 100M for arithmetic (effectively "very large" for scoring).
_SIZE_BUCKETS = {
    "1K-15K":     (1_000,       15_000),
    "15K-50K":    (15_000,      50_000),
    "50K-100K":   (50_000,      100_000),
    "100K-250K":  (100_000,     250_000),
    "250K-500K":  (250_000,     500_000),
    "500K-1M":    (500_000,     1_000_000),
    "1M-5M":      (1_000_000,   5_000_000),
    "5M-25M":     (5_000_000,   25_000_000),
    "25M-50M":    (25_000_000,  50_000_000),
    "50M+":       (50_000_000,  100_000_000),
}


def _parse_size_range(s: str) -> tuple[float, float]:
    """Parse a CapitolTrades size bucket string to (min, max) USD floats.

    Site uses an em-dash (–) between bounds; we accept hyphen too.
    Returns (0, 0) on any unrecognised format.
    """
    if not s:
        return 0.0, 0.0
    # Normalise dash variants
    norm = s.replace("–", "-").replace("—", "-").replace(" ", "")
    return _SIZE_BUCKETS.get(norm, (0.0, 0.0))


def _parse_date(s: str) -> str:
    """Parse '8 May 2026' → '2026-05-08' ISO date string. Returns ''
    on parse failure."""
    if not s:
        return ""
    s = s.strip().replace("\xa0", " ")
    # Handle wrapped dates like "8 May\n2026" from the table cell
    s = re.sub(r"\s+", " ", s)
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _extract_text(node: Tag | None) -> str:
    """Get cell text with whitespace between block-level children.

    BeautifulSoup's `get_text(strip=True)` concatenates without separators,
    so "Broadcom Inc<br>AVGO:US" comes out as "Broadcom IncAVGO:US" (no
    space) and "8 May<br>2026" → "8 May2026" (unparseable as a date).
    Using ` ` as the separator preserves token boundaries.
    """
    if not node:
        return ""
    return re.sub(r"\s+", " ", node.get_text(separator=" ")).strip()


def _parse_row(tr: Tag) -> dict | None:
    """Parse a single trade row <tr> into a normalized dict.

    Returns None if the row doesn't look like a data row (e.g. parser
    drift from a layout change).
    """
    tds = tr.find_all("td", recursive=False)
    if len(tds) < 10:
        return None

    # ── td[0]: politician ───────────────────────────────────────────
    pol_link = tds[0].find("a", href=re.compile(r"^/politicians/"))
    if not pol_link:
        return None
    pol_href = pol_link.get("href", "")
    pol_id = pol_href.rsplit("/", 1)[-1]
    pol_name = _extract_text(pol_link)

    # Party / chamber / state come as separate <span class="q-field party party--X">
    party = ""
    chamber = ""
    state = ""
    for span in tds[0].find_all("span", class_="q-field"):
        cls = " ".join(span.get("class", []))
        text = _extract_text(span)
        if "party--" in cls:
            party = text
        elif "chamber--" in cls:
            chamber = text
        elif "us-state-compact--" in cls:
            state = text

    # ── td[1]: issuer + ticker ──────────────────────────────────────
    iss_link = tds[1].find("a", href=re.compile(r"^/issuers/"))
    issuer_name = _extract_text(iss_link) if iss_link else ""
    # Ticker is shown as "AVGO:US" — pull from text adjacent to the link
    ticker = ""
    cell_text = _extract_text(tds[1])
    m = re.search(r"\b([A-Z][A-Z0-9.\-]{0,5}):US\b", cell_text)
    if m:
        ticker = m.group(1)

    # ── td[2]: published date ──────────────────────────────────────
    published_iso = _parse_date(_extract_text(tds[2]))

    # ── td[3]: traded date ─────────────────────────────────────────
    traded_iso = _parse_date(_extract_text(tds[3]))

    # ── td[4]: filed_after (we recompute from dates as well, more robust)
    # Skip — we'll derive filed_after from the two dates upstream.

    # ── td[5]: owner — "Undisclosed", "Spouse", etc. (informational only)

    # ── td[6]: type
    txn_type = _extract_text(tds[6]).lower()
    if txn_type not in ("buy", "sell", "exchange", "purchase"):
        # tolerate other label variants
        if "buy" in txn_type or "purchase" in txn_type:
            txn_type = "buy"
        elif "sell" in txn_type:
            txn_type = "sell"
        elif "exchange" in txn_type:
            txn_type = "exchange"

    # ── td[7]: size range
    size_text = _extract_text(tds[7])
    amount_min, amount_max = _parse_size_range(size_text)

    # ── td[9] (last cell): trade detail link → filing_id
    filing_id = ""
    detail_link = tds[-1].find("a", href=re.compile(r"^/trades/"))
    if detail_link:
        filing_id = detail_link.get("href", "").rsplit("/", 1)[-1]

    if not filing_id:
        return None

    return {
        "filing_id": filing_id,
        "politician_id": pol_id,
        "politician_name": pol_name,
        "party": party,
        "chamber": chamber,
        "state": state,
        "ticker": ticker.upper(),
        "issuer_name": issuer_name,
        "transaction_date": traded_iso,
        "filing_date": published_iso,
        "transaction_type": txn_type,
        "amount_min": amount_min,
        "amount_max": amount_max,
    }


def _fetch_page(page: int, timeout: float = DEFAULT_TIMEOUT) -> list[dict]:
    """Fetch and parse a single trades page. Empty list on error."""
    url = TRADES_URL if page == 1 else f"{TRADES_URL}?page={page}"
    try:
        r = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            timeout=timeout,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("CapitolTrades page %d fetch failed: %s", page, e)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    rows = []
    for tr in soup.find_all("tr", attrs={"data-state": "false"}):
        parsed = _parse_row(tr)
        if parsed:
            rows.append(parsed)
    log.info("CapitolTrades page %d: %d rows parsed", page, len(rows))
    return rows


def fetch_recent_trades(
    since_date: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    rate_limit_seconds: float = RATE_LIMIT_SECONDS,
) -> list[dict]:
    """Fetch trades with `filing_date >= since_date`.

    Walks /trades pages newest-first (the site default sort) and stops
    when a page is empty or all rows are older than `since_date`.

    Args:
        since_date: ISO YYYY-MM-DD; lower bound on `filing_date`.
        max_pages: hard cap on pagination.
        rate_limit_seconds: sleep between page requests.

    Returns:
        Flat list of dicts ready to feed `CongressTradeRow`.
    """
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        rows = _fetch_page(page)
        if not rows:
            break

        # Keep rows >= since_date
        kept = [r for r in rows if (r.get("filing_date") or "9999-99-99") >= since_date]
        out.extend(kept)

        # If the OLDEST row on this page is already older than since_date,
        # we can stop — older pages are even older.
        oldest_on_page = min(
            (r.get("filing_date", "9999-99-99") for r in rows),
            default="9999-99-99",
        )
        if oldest_on_page < since_date:
            log.info(
                "CapitolTrades: oldest row on page %d (%s) older than since=%s — stopping",
                page, oldest_on_page, since_date,
            )
            break

        time.sleep(rate_limit_seconds)

    log.info("CapitolTrades fetch complete: %d trades since %s", len(out), since_date)
    return out
