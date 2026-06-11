"""
Shared schema helpers and conventions.

All sheet-tab dataclasses depend on the formatting helpers and the
SGT-anchored timestamp utilities defined here. Split out of the original
monolithic ``src/schema.py`` so the per-domain submodules can share a
single source of truth without circular imports.

All sheet audit timestamps are SGT-anchored so Mac-written rows
(datetime.now() = local SGT) and cloud-written rows (GH Actions UTC)
sort lexicographically into a single chronological order. Without this,
UTC-13:54 cloud writes appear "before" SGT-21:53 Mac writes in string
sort, even though they happened ~minutes apart in real time.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo


SGT = timezone(timedelta(hours=8), name="SGT")

US_MARKET_TZ = ZoneInfo("America/New_York")


def now_sgt_iso() -> str:
    """Current SGT instant as 'YYYY-MM-DDTHHMMSS' for sheet audit suffixes."""
    return datetime.now(SGT).strftime("%Y-%m-%dT%H%M%S")


def now_sgt_date() -> str:
    """Current SGT calendar date as 'YYYY-MM-DD'."""
    return datetime.now(SGT).strftime("%Y-%m-%d")


def us_market_date(now: datetime | None = None) -> str:
    """US-Eastern calendar date 'YYYY-MM-DD' of `now` (tz-aware; default
    = current instant).

    The dedup day for alert lanes tied to the US cash session. The session
    runs ACROSS SGT midnight (21:30-04:00 SGT), so keying a once-per-day
    page to the SGT date re-arms it at 00:00 SGT mid-session — the
    2026-06-11 market-pressure incident: WARN paged 23:36 SGT, re-paged
    ~00:10 SGT on the date roll, then the deepening tape stayed silent
    because the "new day's" WARN was already spent."""
    return (now or datetime.now(US_MARKET_TZ)).astimezone(US_MARKET_TZ).strftime("%Y-%m-%d")


def _num(x, ndp: int = 2) -> str:
    """Format a number as fixed-decimal string, '' for None."""
    if x is None:
        return ""
    try:
        return f"{float(x):.{ndp}f}"
    except (TypeError, ValueError):
        return str(x)


def _ts_suffix(date: str) -> str:
    """Append HHMMSS (SGT) to a YYYY-MM-DD date for audit-trail uniqueness."""
    return f"{date}T{datetime.now(SGT).strftime('%H%M%S')}"
