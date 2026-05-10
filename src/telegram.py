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

# Insider Trading topic — created by Caspar manually in the Finance &
# Trading supergroup. Topic ID discovered via getUpdates after first
# message lands in the topic, then set as repo secret. Until configured,
# `ping_insider_pulse` is a no-op (graceful skip — strategy still works,
# digest just doesn't send).
_insider_topic_raw = os.environ.get("TELEGRAM_INSIDER_TRADING_TOPIC", "").strip()
INSIDER_TRADING_TOPIC: int | None = (
    int(_insider_topic_raw) if _insider_topic_raw.isdigit() else None
)

# Personal-chat fallback — not used by the production helpers below
# but kept as a backstop for ad-hoc scripts that pre-date routing.
PERSONAL_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "922547929")


def send(
    text: str,
    parse_mode: ParseMode = "none",
    chat_id: str | None = None,
    message_thread_id: int | None = None,
    disable_web_page_preview: bool = False,
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
        disable_web_page_preview: when True, suppresses Telegram's
                 auto-generated link-preview card. Set on the macro
                 pings — the preview card was rendering the article
                 title underneath our message, which visually echoed
                 the headline.
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
    if disable_web_page_preview:
        # Legacy field name still supported by Bot API and simpler than
        # the newer link_preview_options object. Either works.
        payload["disable_web_page_preview"] = True

    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram API error: {body}")
    return body


# ────────────────────────────────────────────────────────────────────
# Multi Day Swing topic — FinancePWA's lane
# ────────────────────────────────────────────────────────────────────

def ping_daily_ready(
    date: str,
    pwa_url: str | None = None,
    headline: str = "",
    verdict: str = "",
    bullets: list[str] | None = None,
    posture: str = "",
    drive_url: str | None = None,
) -> dict:
    """
    Daily-brief Telegram digest. Routed to Multi Day Swing topic so the
    swing book has standing daily content beyond ACT_NOW transitions.

    Includes the brief's headline + verdict + top bullets + posture inline
    so the user can read the topic and skip opening the PWA. The full
    brief is still in the Drive doc + the daily_brief_latest sheet tab.

    Args:
        date: brief date "YYYY-MM-DD"
        pwa_url: PWA link (added as footer)
        headline: 1-line summary (e.g. "SPX +0.4%, semis lead")
        verdict: brain-derived verdict ("constructive" / "cautious" / etc.)
        bullets: up to 3 takeaway bullets
        posture: cash/exposure recommendation 1-liner
        drive_url: link to full brief markdown in Drive
    """
    lines = [f"📰 Daily Brief · {date}"]
    if headline:
        lines.append(headline.strip())
    if verdict:
        lines.append(f"verdict: {verdict.strip()}")
    if bullets:
        lines.append("")
        for b in bullets[:3]:
            b = (b or "").strip()
            if not b:
                continue
            # Truncate per-bullet to keep the Telegram preview readable.
            if len(b) > 140:
                b = b[:137] + "..."
            lines.append(f"• {b}")
    if posture:
        lines.append("")
        lines.append(f"posture: {posture.strip()[:120]}")
    footer_bits = []
    if drive_url:
        footer_bits.append(f"📄 {drive_url}")
    if pwa_url:
        footer_bits.append(f"📱 {pwa_url}")
    if footer_bits:
        lines.append("")
        lines.extend(footer_bits)
    return send(
        "\n".join(lines),
        parse_mode="none",
        message_thread_id=MULTI_DAY_SWING_TOPIC,
    )


def ping_wsr_ready(
    date: str,
    pwa_url: str | None = None,
    kind: str = "WSR",
    verdict: str = "",
    macro_read: str = "",
    action_summary: str = "",
    drive_url: str | None = None,
) -> dict:
    """
    Weekly Strategy Review digest. Routes to Multi Day Swing topic with
    verdict + macro read + action summary inline so the topic carries
    the headline content (full doc still in Drive).

    Args:
        date: review date "YYYY-MM-DD"
        pwa_url: PWA link (footer)
        kind: "WSR Lite" | "WSR Full" — appears in the title line
        verdict: brain-derived verdict
        macro_read: 1-paragraph macro-environment read
        action_summary: this-week action items
        drive_url: link to full markdown
    """
    lines = [f"📊 {kind} · {date}"]
    if verdict:
        lines.append(f"verdict: {verdict.strip()}")
    if macro_read:
        body = macro_read.strip()
        if len(body) > 220:
            body = body[:217] + "..."
        lines.append("")
        lines.append(body)
    if action_summary:
        body = action_summary.strip()
        if len(body) > 220:
            body = body[:217] + "..."
        lines.append("")
        lines.append(f"Action: {body}")
    footer_bits = []
    if drive_url:
        footer_bits.append(f"📄 {drive_url}")
    if pwa_url:
        footer_bits.append(f"📱 {pwa_url}")
    if footer_bits:
        lines.append("")
        lines.extend(footer_bits)
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


def ping_macro_news_to_swing(
    headline: str,
    matched_tickers: list[str],
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
    # Same HTML + inline-link + preview-disable + source-suffix-strip
    # treatment as ping_macro_news so the swing-mirror copy isn't
    # visually noisier than the Macro News original.
    import html
    body = _strip_source_suffix(headline.strip(), source)
    if len(body) > 200:
        body = body[:197] + "..."
    tickers_str = " ".join(f"${t}" for t in matched_tickers[:5])
    lines = [f"📍 NEWS · {html.escape(tickers_str)} · {html.escape(body)}"]
    if source and url:
        lines.append(f'🔗 <a href="{html.escape(url, quote=True)}">{html.escape(source)}</a>')
    elif source:
        lines.append(f"source: {html.escape(source)}")
    elif url:
        lines.append(html.escape(url))
    return send(
        "\n".join(lines),
        parse_mode="HTML",
        message_thread_id=MULTI_DAY_SWING_TOPIC,
        disable_web_page_preview=True,
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


def _strip_source_suffix(headline: str, source: str) -> str:
    """Strip a trailing " - Source" / " — Source" / " | Source" attribution.

    Many news APIs (Reuters via Finnhub, Bloomberg via RSS) include the
    publisher name at the tail of the headline string — fine for a feed
    reader, but in our pings we already show the source on its own line,
    so the suffix is just visual repetition. Match is case-insensitive
    against the explicit source value, so "...says - Reuters" with
    source="Reuters" or source="reuters" both strip cleanly.
    """
    if not source:
        return headline
    h = headline.rstrip()
    s_lower = source.strip().lower()
    for sep in (" - ", " — ", " – ", " | ", " · "):
        suffix_lower = f"{sep}{s_lower}"
        if h.lower().endswith(suffix_lower):
            return h[:-(len(suffix_lower))].rstrip(" .,:;-—–|·")
    return h


def ping_macro_news(
    headline: str,
    source: str = "",
    url: str = "",
    category: str = "",
) -> dict:
    """
    Edge-triggered hot-news headline ping. Fired when the macro_blackouts
    poller catches a headline matching HOT_KEYWORDS (fed/cpi/iran/tariff/
    opec/etc.) across Finnhub (general/forex/crypto/merger) + RSS feeds
    (WSJ/Bloomberg/MarketWatch/CNBC).

    Sent EXACTLY ONCE per news_id (dedup tracked in macro_alerts_state).
    Capped at 3 per cron run so a Finnhub backlog catch-up doesn't flood.

    No "so what" interpretation line — the keyword heuristic produced
    canned output that read as fake reasoning, and an LLM-driven version
    would re-introduce API cost. Reasoning lives in the daily brief now
    (Multi Day Swing topic, once a day, Opus-quality).

    Args:
        headline: news headline (truncated at 200 chars)
        source: publisher name (e.g. "Reuters", "Bloomberg")
        url: link to the article
        category: Finnhub/RSS category for the inline tag
    """
    # HTML parse mode + inline-linked source. Two fixes layered to kill
    # the headline-twice visual:
    #   1. Strip trailing "- Reuters" / "| Bloomberg" attribution from
    #      the headline since we already show source on its own line.
    #   2. Disable Telegram's auto link-preview card. Otherwise it
    #      fetches the URL and renders the article title underneath,
    #      which echoes the headline a second time.
    import html
    body = _strip_source_suffix(headline.strip(), source)
    if len(body) > 200:
        body = body[:197] + "..."
    cat_tag = f" · {category}" if category and category != "general" else ""
    lines = [f"📰 MACRO{cat_tag} · {html.escape(body)}"]
    # Inline-link the source name; falls back to plain source text if no
    # URL, or the bare URL if no source (rare — Finnhub/RSS items always
    # carry a source).
    if source and url:
        lines.append(f'🔗 <a href="{html.escape(url, quote=True)}">{html.escape(source)}</a>')
    elif source:
        lines.append(f"source: {html.escape(source)}")
    elif url:
        lines.append(html.escape(url))
    return send(
        "\n".join(lines),
        parse_mode="HTML",
        message_thread_id=MACRO_NEWS_TOPIC,
        disable_web_page_preview=True,
    )


# ────────────────────────────────────────────────────────────────────
# Insider Trading topic — gov spending confluence pulse
# ────────────────────────────────────────────────────────────────────

def ping_insider_pulse(
    date: str,
    confluence_picks: list[dict] | None = None,
    capitol_filings: list[dict] | None = None,
    unmapped: list[dict] | None = None,
    pwa_url: str | None = None,
) -> dict:
    """
    Daily Insider Trading topic digest. Single message containing:
      - 🎯 CONFLUENCE PICKS (top 3 from gov_confluence_signals)
      - 🏛 CAPITOL TRADES (top 3 from congress_trades by amount)
      - ⚠ UNMAPPED RECIPIENTS (review for ticker mapping addition)

    Args:
        date: ISO YYYY-MM-DD
        confluence_picks: list of dicts with keys {ticker, score, tier,
            strategy, action, thesis, contracts_dollars, congress_dollars,
            insider_dollars, contract_count, congress_count, insider_count}
        capitol_filings: list of dicts with keys {politician_name, party,
            chamber, ticker, transaction_type, amount_min, amount_max,
            filing_date}
        unmapped: list of dicts with keys {recipient_name, total_amount,
            agency} for the unmapped-recipients review queue
        pwa_url: optional PWA link for footer

    Returns:
        Telegram API response dict, or {"skipped": ...} if topic not configured.

    HTML parse mode + disable_web_page_preview to keep formatting tight
    and avoid auto-link cards under the message.
    """
    if INSIDER_TRADING_TOPIC is None:
        return {"skipped": "TELEGRAM_INSIDER_TRADING_TOPIC not configured"}

    import html
    lines = [f"📊 <b>INSIDER PULSE</b> · {html.escape(date)}"]

    # ── Confluence picks ──────────────────────────────────────────────
    picks = list(confluence_picks or [])
    if picks:
        lines.append("")
        lines.append("🎯 <b>CONFLUENCE PICKS</b>")
        for i, p in enumerate(picks[:3], start=1):
            tk = html.escape(str(p.get("ticker", "?")))
            score = float(p.get("score", 0))
            tier = str(p.get("tier", "")) or "-"
            strat = html.escape(str(p.get("strategy", "WATCH") or "WATCH"))
            thesis = html.escape(str(p.get("thesis", ""))[:140])
            action = html.escape(str(p.get("action", ""))[:160])
            lines.append(f"{i}. <b>${tk}</b> — score {score:.0f} · Tier {tier}")
            if action:
                lines.append(f"   {action}")
            elif thesis:
                lines.append(f"   {thesis}")
            arrow = "🟢" if strat in ("BUY_DIP", "LONG_CALL", "PMCC") else "👀"
            lines.append(f"   → {arrow} {strat}")
    else:
        lines.append("")
        lines.append("🎯 <b>CONFLUENCE PICKS</b>")
        lines.append("   <i>no signals scored ≥70 today</i>")

    # ── Capitol Trades ────────────────────────────────────────────────
    filings = list(capitol_filings or [])
    if filings:
        lines.append("")
        lines.append("🏛 <b>CAPITOL TRADES</b> (top by amount)")
        for f in filings[:5]:
            pol = html.escape(str(f.get("politician_name", "?"))[:25])
            party = str(f.get("party", ""))[:1]
            chamber = str(f.get("chamber", ""))[:5]
            tk = html.escape(str(f.get("ticker", "?")))
            ttype = html.escape(str(f.get("transaction_type", "?")).upper())
            amax = float(f.get("amount_max", 0))
            amin = float(f.get("amount_min", 0))
            arrow = "🟢" if ttype.lower() == "buy" else "🔴"
            lines.append(
                f"  {arrow} {pol} ({party}-{chamber}) → ${tk} {ttype} "
                f"<code>${amin/1e3:.0f}K-${amax/1e3:.0f}K</code>"
            )

    # ── Unmapped flagged ──────────────────────────────────────────────
    flagged = list(unmapped or [])
    if flagged:
        lines.append("")
        lines.append("⚠ <b>UNMAPPED RECIPIENTS</b> (review)")
        for u in flagged[:3]:
            name = html.escape(str(u.get("recipient_name", "?"))[:50])
            amount = float(u.get("total_amount", 0))
            lines.append(f"  · <code>${amount/1e6:.1f}M</code> — {name}")

    # Footer
    if pwa_url:
        lines.append("")
        lines.append(f"📱 {html.escape(pwa_url)}")

    return send(
        "\n".join(lines),
        parse_mode="HTML",
        message_thread_id=INSIDER_TRADING_TOPIC,
        disable_web_page_preview=True,
    )
