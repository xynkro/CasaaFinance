"""
Compact portfolio summaries for Telegram replies.

Used by `scripts/telegram_portfolio_responder.py`. Reads the latest
snapshot + positions for an account and formats a message that fits
inside Telegram's mobile preview without scrolling.
"""
from __future__ import annotations

from typing import Optional


def _f(v: str | float | int | None, ndp: int = 0) -> str:
    """Format a number with thousands separator, fallback `—` on bad input."""
    if v is None or v == "":
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if ndp == 0:
        return f"{n:,.0f}"
    return f"{n:,.{ndp}f}"


def _pct_from_fraction(v: str | float | int | None) -> str:
    """
    Format a fraction (0.0566) as a percent string ("+5.7%").
    The yahoo-grab snapshot writes upl_pct as a fraction, so callers
    can pass the raw cell value here.
    """
    if v is None or v == "":
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    pct = n * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _abs_with_sign(v: str | float | int | None, prefix: str = "$") -> str:
    """Format an abs value with a leading sign."""
    if v is None or v == "":
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if n >= 0 else "−"
    return f"{sign}{prefix}{abs(n):,.0f}"


def build_portfolio_summary(
    account: str,
    snapshot: Optional[dict],
    positions: list[dict],
    options_count: int = 0,
    top_n: int = 6,
) -> str:
    """
    Compose a 6-10 line summary for the account's latest snapshot.

    Args:
        account: "caspar" or "sarah" (display-cased)
        snapshot: latest row of snapshot_<account>, or None when missing
        positions: latest day's positions_<account> rows
        options_count: options held (for the inline "+N options" badge)
        top_n: how many holdings to show in the table

    Returns: plain-text Telegram-safe string (no MarkdownV2 escaping
    needed — caller sends with parse_mode="none").
    """
    name = account.capitalize()
    ccy = "SGD" if account.lower() == "sarah" else "USD"

    lines: list[str] = []
    if not snapshot:
        lines.append(f"👤 {name} — no snapshot yet")
        return "\n".join(lines)

    date = (snapshot.get("date") or "")[:10] or "—"
    net_liq = _f(snapshot.get("net_liq"), 0)
    cash = _f(snapshot.get("cash"), 0)
    upl_abs = _abs_with_sign(snapshot.get("upl"), "$")
    upl_pct = _pct_from_fraction(snapshot.get("upl_pct"))

    # Cash %
    try:
        c_pct = (float(snapshot.get("cash") or 0) / float(snapshot.get("net_liq") or 1)) * 100
        cash_pct_str = f" ({c_pct:.0f}%)"
    except (TypeError, ValueError, ZeroDivisionError):
        cash_pct_str = ""

    lines.append(f"👤 {name} · {date}")
    lines.append(f"NLV {ccy} ${net_liq} · UPL {upl_abs} ({upl_pct})")
    lines.append(f"Cash ${cash}{cash_pct_str}")

    # Top holdings
    valid = [p for p in positions if p.get("ticker") and p.get("mkt_val")]
    valid.sort(key=lambda p: float(p.get("mkt_val") or 0), reverse=True)
    if valid:
        lines.append("")
        lines.append("Top holdings:")
        for p in valid[:top_n]:
            ticker = (p.get("ticker") or "")[:5]
            # weight column from yahoo-grab is a fraction (0.4282 = 42.82%)
            try:
                weight = float(p.get("weight") or 0) * 100
                weight_s = f"{weight:.1f}%"
            except (TypeError, ValueError):
                weight_s = "—"
            try:
                mv = float(p.get("mkt_val") or 0)
                mv_s = f"${mv:,.0f}"
            except (TypeError, ValueError):
                mv_s = "—"
            try:
                upl_p = float(p.get("upl") or 0)
                upl_emoji = "🟢" if upl_p >= 0 else "🔴"
            except (TypeError, ValueError):
                upl_emoji = "·"
            lines.append(f"  {upl_emoji} {ticker:<5} {weight_s:>6} · {mv_s}")
        rest = len(valid) - top_n
        if rest > 0:
            lines.append(f"  +{rest} more positions")

    if options_count:
        lines.append(f"\n📑 {options_count} option contract(s)")

    return "\n".join(lines)
