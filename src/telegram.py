"""
Telegram push — raw requests POST to api.telegram.org. No library dependency.

Routing model
-------------
All FinancePWA pings now land in the **Finance & Trading** supergroup
(@-1003942004211, set up by Caspar with topic threads). The bot
(@Tron_shaft_bot) is a member there.

Per-helper routing:
  - Trigger / portfolio / WSR / IBKR pings → "Multi Day Swing" topic (3)
  - Macro blackout warnings + hot-news headlines → "Macro Financial News" topic (6)
  - "Zero DTE Signals" (topic 2) is ZeroDTE's lane — FinancePWA doesn't write there

The personal-chat default ("922547929") is preserved for explicit-override
test scenarios but no helper points there anymore.

Telegram parse_mode MUST be one of "none", "MarkdownV2", "HTML" — there
is no plain "Markdown" (per auto-memory, past footgun).
"""
from __future__ import annotations

import os
from typing import Literal

import requests

ParseMode = Literal["none", "MarkdownV2", "HTML"]

# ────────────────────────────────────────────────────────────────────
# Routing — overridable via env so tests / staging can fork to a
# different chat without code change.
# ────────────────────────────────────────────────────────────────────
FINANCE_CHAT_ID = os.environ.get("TELEGRAM_FINANCE_CHAT_ID", "-1003942004211")
MULTI_DAY_SWING_TOPIC = int(os.environ.get("TELEGRAM_MULTI_DAY_SWING_TOPIC", "3"))
MACRO_NEWS_TOPIC = int(os.environ.get("TELEGRAM_MACRO_NEWS_TOPIC", "6"))

# Personal-chat fallback — not used by the production helpers below
# but kept as a backstop for ad-hoc scripts that pre-date routing.
PERSONAL_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "922547929")


def send(
    text: str,
    parse_mode: ParseMode = "none",
    chat_id: str | None = None,
    message_thread_id: int | None = None,
) -> dict:
    """
    Send a message. Returns Telegram API response dict.
    Raises on HTTP error or API-level failure.

    Args:
        text: message body
        parse_mode: "none" / "MarkdownV2" / "HTML"
        chat_id: defaults to FINANCE_CHAT_ID (the supergroup). Pass
                 PERSONAL_CHAT_ID for direct messages, or any other
                 chat_id for ad-hoc routing.
        message_thread_id: topic thread within a forum-mode supergroup.
                 Required when chat_id is the Finance & Trading group.
                 Omit (or pass None) for non-forum chats.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in environment")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict = {
        "chat_id": str(chat_id or FINANCE_CHAT_ID),  # MUST be string
        "text": text,
    }
    if parse_mode != "none":
        payload["parse_mode"] = parse_mode
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id

    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram API error: {body}")
    return body


# ────────────────────────────────────────────────────────────────────
# Multi Day Swing topic — FinancePWA's lane
# ────────────────────────────────────────────────────────────────────

def ping_daily_ready(date: str, pwa_url: str | None = None) -> dict:
    """Short 'Daily Brief ready' ping with optional PWA URL line."""
    lines = [f"📰 Daily Brief {date} ready"]
    if pwa_url:
        lines.append(f"📱 PWA: {pwa_url}")
    return send(
        "\n".join(lines),
        parse_mode="none",
        message_thread_id=MULTI_DAY_SWING_TOPIC,
    )


def ping_wsr_ready(date: str, pwa_url: str | None = None) -> dict:
    """Short 'Weekly Strategy ready' ping with optional PWA URL line."""
    lines = [f"📊 Weekly Strategy {date} ready"]
    if pwa_url:
        lines.append(f"📱 PWA: {pwa_url}")
    return send(
        "\n".join(lines),
        parse_mode="none",
        message_thread_id=MULTI_DAY_SWING_TOPIC,
    )


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
    return send(
        "\n".join(lines),
        parse_mode="none",
        message_thread_id=MULTI_DAY_SWING_TOPIC,
    )


def ping_swing_summary(
    date: str,
    watching: int,
    act_now: int,
    blocked: int,
    top_close: list[dict] | None = None,
    cash_status: str = "",
    pwa_url: str | None = None,
) -> dict:
    """
    Once-a-day snapshot of the swing book. Fires on the first trigger_alerts
    cron run after 09:00 SGT each weekday so the Multi Day Swing topic
    has standing content even on quiet days when no ACT_NOW pings fire.

    Args:
        date: SGT date "YYYY-MM-DD"
        watching: count of decisions in WATCHING state
        act_now: count currently at ACT_NOW
        blocked: count blocked by gates (CASH_PRIORITY, etc.)
        top_close: up to 3 closest-to-trigger decisions, each with
            {ticker, account, pct_to_trigger}
        cash_status: short string like "Cash 5.0% — at floor"
    """
    lines = [f"📊 Swing Book · {date}"]

    # Counts row — keep it dense.
    bits = []
    if watching:
        bits.append(f"watching {watching}")
    if act_now:
        bits.append(f"⚡ ACT NOW {act_now}")
    if blocked:
        bits.append(f"blocked {blocked}")
    if not bits:
        bits.append("no live decisions")
    lines.append(" · ".join(bits))

    if cash_status:
        lines.append(cash_status)

    if top_close:
        lines.append("")
        lines.append("Closest to trigger:")
        for c in top_close[:3]:
            tk = c.get("ticker", "?")
            acct = (c.get("account") or "").upper()
            pct = c.get("pct_to_trigger", 0)
            try:
                pct_str = f"{abs(float(pct)) * 100:.1f}%"
            except (TypeError, ValueError):
                pct_str = "?"
            lines.append(f"  · {tk} {acct} — {pct_str} to trigger")

    if pwa_url:
        lines.append(f"📱 {pwa_url}")

    return send(
        "\n".join(lines),
        parse_mode="none",
        message_thread_id=MULTI_DAY_SWING_TOPIC,
    )


def ping_macro_news_to_swing(
    headline: str,
    matched_tickers: list[str],
    so_what: str = "",
    source: str = "",
    url: str = "",
) -> dict:
    """
    Mirror copy of a macro-news ping to the Multi Day Swing topic when
    the headline mentions one or more portfolio tickers. Lets the swing
    topic surface news that's directly relevant to held positions
    without forcing the user to flip to the Macro News topic.

    Distinct from `ping_macro_news` (Macro News topic) by the route AND
    by the leading line which calls out the matched tickers.
    """
    body = headline.strip()
    if len(body) > 200:
        body = body[:197] + "..."
    tickers_str = " ".join(f"${t}" for t in matched_tickers[:5])
    lines = [f"📍 NEWS · {tickers_str} · {body}"]
    if so_what:
        lines.append(f"💡 {so_what}")
    if source:
        lines.append(f"source: {source}")
    if url:
        lines.append(url)
    return send(
        "\n".join(lines),
        parse_mode="none",
        message_thread_id=MULTI_DAY_SWING_TOPIC,
    )


def ping_trigger_act_now(
    ticker: str,
    account: str,
    strategy: str,
    entry_price: float,
    current_price: float,
    direction: str,           # "buy" | "trim"
    pwa_url: str | None = None,
) -> dict:
    """
    Per-decision trigger alert. Fires when scripts/trigger_alerts.py
    detects a transition into act_now (price crossed entry threshold AND
    all gates clear).
    """
    arrow = "🟢⬇️" if direction == "buy" else "🔴⬆️"
    verb = "buy" if direction == "buy" else "trim"
    diff_pct = ((current_price - entry_price) / entry_price * 100) if entry_price else 0
    lines = [
        f"{arrow} ACT NOW · {ticker} · {account.upper()}",
        f"{verb} @ ${current_price:.2f} (entry ${entry_price:.2f}, {diff_pct:+.1f}%)",
        f"strategy: {strategy or 'BUY_DIP'}",
    ]
    if pwa_url:
        lines.append(f"📱 {pwa_url}")
    return send(
        "\n".join(lines),
        parse_mode="none",
        message_thread_id=MULTI_DAY_SWING_TOPIC,
    )


def ping_trigger_close(
    ticker: str,
    account: str,
    strategy: str,
    entry_price: float,
    current_price: float,
    direction: str,           # "buy" | "trim"
    pct_to_trigger: float,    # signed: negative = past, positive = approaching
    pwa_url: str | None = None,
) -> dict:
    """
    Soft alert — fires when a watching decision enters CLOSE state
    (within 3% of trigger). Less urgent than ping_trigger_act_now;
    designed for "heads up, this is heating up" rather than "act".

    Gated server-side by TRIGGER_ALERTS_INCLUDE_CLOSE env (default off).
    """
    arrow = "🟡⬇️" if direction == "buy" else "🟡⬆️"
    verb = "approaching buy" if direction == "buy" else "approaching trim"
    distance = abs(pct_to_trigger) * 100
    lines = [
        f"{arrow} CLOSE · {ticker} · {account.upper()}",
        f"{verb} — {distance:.1f}% to entry ${entry_price:.2f} (cur ${current_price:.2f})",
        f"strategy: {strategy or 'BUY_DIP'}",
    ]
    if pwa_url:
        lines.append(f"📱 {pwa_url}")
    return send(
        "\n".join(lines),
        parse_mode="none",
        message_thread_id=MULTI_DAY_SWING_TOPIC,
    )


# ────────────────────────────────────────────────────────────────────
# Macro Financial News topic — shared blackout / hot-news lane
# ────────────────────────────────────────────────────────────────────

def ping_macro_blackout(
    event_name: str,
    minutes_until: int,
    impact: str = "high",
    pwa_url: str | None = None,
) -> dict:
    """
    Edge-triggered "DON'T TRADE — XXX in N min" alert. Fired by
    scripts/trigger_alerts.py when the macro_blackouts module reports
    we're inside the ±15min window of a high-impact US event.

    Sent EXACTLY ONCE per event (dedup tracked in macro_alerts_state).
    """
    if minutes_until > 0:
        timing = f"in {minutes_until} min"
    elif minutes_until == 0:
        timing = "now"
    else:
        timing = f"{abs(minutes_until)} min ago"
    lines = [
        f"⏸️ DON'T TRADE · {event_name}",
        f"event {timing} — stand aside on new entries until window clears",
        f"impact: {impact.upper()}",
    ]
    if pwa_url:
        lines.append(f"📱 {pwa_url}")
    return send(
        "\n".join(lines),
        parse_mode="none",
        message_thread_id=MACRO_NEWS_TOPIC,
    )


def ping_macro_news(
    headline: str,
    source: str = "",
    url: str = "",
    so_what: str = "",
    category: str = "",
) -> dict:
    """
    Edge-triggered hot-news headline ping. Fired when the macro_blackouts
    poller catches a Finnhub headline matching HOT_KEYWORDS (fed/cpi/iran/
    tariff/etc.) across multiple categories (general, forex, crypto, merger).

    Sent EXACTLY ONCE per news_id (dedup tracked in macro_alerts_state).
    Capped at 3 per cron run so a Finnhub backlog catch-up doesn't flood.

    Args:
        headline: news headline (truncated at 200 chars)
        source: publisher name (e.g. "Reuters", "Bloomberg")
        url: link to the article
        so_what: short trader-actionable interpretation
                 (e.g. "Crude bid → energy/defense risk-on")
        category: Finnhub category (general/forex/crypto/merger) for label
    """
    body = headline.strip()
    if len(body) > 200:
        body = body[:197] + "..."
    cat_tag = f" · {category}" if category and category != "general" else ""
    lines = [f"📰 MACRO{cat_tag} · {body}"]
    if so_what:
        lines.append(f"💡 {so_what}")
    if source:
        lines.append(f"source: {source}")
    if url:
        lines.append(url)
    return send(
        "\n".join(lines),
        parse_mode="none",
        message_thread_id=MACRO_NEWS_TOPIC,
    )
