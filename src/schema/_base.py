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


SGT = timezone(timedelta(hours=8), name="SGT")


def now_sgt_iso() -> str:
    """Current SGT instant as 'YYYY-MM-DDTHHMMSS' for sheet audit suffixes."""
    return datetime.now(SGT).strftime("%Y-%m-%dT%H%M%S")


def now_sgt_date() -> str:
    """Current SGT calendar date as 'YYYY-MM-DD'."""
    return datetime.now(SGT).strftime("%Y-%m-%d")


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
