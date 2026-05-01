"""
Telegram push — raw requests POST to api.telegram.org. No library dependency.

Uses the same bot (@Tron_shaft_bot, chat_id "922547929") that the Daily News
Brief pipeline already writes to. parse_mode MUST be one of "none", "MarkdownV2",
"HTML" — there is no plain "Markdown" (per auto-memory, past footgun).
"""
from __future__ import annotations

import os
from typing import Literal

import requests

ParseMode = Literal["none", "MarkdownV2", "HTML"]


def send(text: str, parse_mode: ParseMode = "none") -> dict:
    """
    Send a message. Returns Telegram API response dict.
    Raises on HTTP error or API-level failure.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "922547929")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in environment")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": str(chat_id),  # MUST be string per auto-memory rule
        "text": text,
    }
    # Telegram API treats "none" specially — we simply omit parse_mode in that case
    if parse_mode != "none":
        payload["parse_mode"] = parse_mode

    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram API error: {body}")
    return body


def ping_daily_ready(date: str, pwa_url: str | None = None) -> dict:
    """Short 'Daily Brief ready' ping with optional PWA URL line."""
    lines = [f"📰 Daily Brief {date} ready"]
    if pwa_url:
        lines.append(f"📱 PWA: {pwa_url}")
    return send("\n".join(lines), parse_mode="none")


def ping_wsr_ready(date: str, pwa_url: str | None = None) -> dict:
    """Short 'Weekly Strategy ready' ping with optional PWA URL line."""
    lines = [f"📊 Weekly Strategy {date} ready"]
    if pwa_url:
        lines.append(f"📱 PWA: {pwa_url}")
    return send("\n".join(lines), parse_mode="none")


def ping_grab_ready(
    date: str,
    caspar_positions: int,
    sarah_positions: int,
    caspar_options: int,
    sarah_options: int,
    pwa_url: str | None = None,
) -> dict:
    """Ping after IBKR portfolio grab sync."""
    def _line(name: str, stk: int, opt: int) -> str:
        if stk == 0 and opt == 0:
            return f"  {name}: nothing"
        parts = []
        if stk:
            parts.append(f"{stk} stock{'s' if stk != 1 else ''}")
        if opt:
            parts.append(f"{opt} option{'s' if opt != 1 else ''}")
        return f"  {name}: {', '.join(parts)}"
    lines = [
        f"📸 Portfolio grab {date} synced",
        _line("Caspar", caspar_positions, caspar_options),
        _line("Sarah", sarah_positions, sarah_options),
    ]
    if pwa_url:
        lines.append(f"📱 PWA: {pwa_url}")
    return send("\n".join(lines), parse_mode="none")
