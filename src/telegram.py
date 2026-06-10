"""
Telegram push — raw requests POST to api.telegram.org. No library dependency.

Routing model
-------------
All FinancePWA pings now land in the **Finance & Trading** supergroup
(@-1003942004211, set up by Caspar with topic threads). The bot
(@Tron_shaft_bot) is a member there.

Per-helper routing:
  - Trigger / WSR / IBKR pings → "Multi Day Swing" topic (3)
  - Macro blackout warnings + hot-news headlines → "Macro Financial News" topic (6)
  - Options scan digests (CSP/CC/LONG_CALL/PMCC) → "Options Intel" topic (492)
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


def _env_int(key: str, default: int) -> int:
    """Read an env var as int, falling back to *default* when missing OR empty."""
    val = os.environ.get(key, "").strip()
    return int(val) if val else default


MULTI_DAY_SWING_TOPIC = _env_int("TELEGRAM_MULTI_DAY_SWING_TOPIC", 3)
MACRO_NEWS_TOPIC = _env_int("TELEGRAM_MACRO_NEWS_TOPIC", 6)
OPTIONS_INTEL_TOPIC = _env_int("TELEGRAM_OPTIONS_INTEL_TOPIC", 492)
INSIDER_TRADING_TOPIC = _env_int("TELEGRAM_INSIDER_TRADING_TOPIC", 510)

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
    if not r.ok:
        import logging as _log
        _log.getLogger(__name__).error(
            "Telegram %s → %s", r.status_code, r.text[:500]
        )
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
    gov_confluence: list[str] | None = None,
    insider_alert: list[str] | None = None,
    overnight: str | list[str] = "",
    premarket: str | list[str] = "",
    catalysts: str | list[str] = "",
    commodities: str | list[str] = "",
    watch: str | list[str] = "",
    earnings_today: str | list[str] = "",
    macro_today: str | list[str] = "",
    negative_news: str | list[str] = "",
) -> dict:
    """
    Full daily-brief Telegram digest. Routed to Multi Day Swing topic.
    Includes all brief sections so the user gets the complete picture
    without opening the PWA.
    """
    import html as _html

    def _bullets(val) -> list[str]:
        if not val:
            return []
        if isinstance(val, list):
            return [str(v).strip() for v in val if str(v).strip()]
        return [s.strip() for s in str(val).split("|") if s.strip()]

    def _section(emoji: str, title: str, items: list[str], max_items: int = 5) -> None:
        if not items:
            return
        lines.append("")
        lines.append(f"{emoji} <b>{title}</b>")
        for item in items[:max_items]:
            if len(item) > 160:
                item = item[:157] + "..."
            lines.append(f"  · {_html.escape(item)}")

    lines = [f"<b>📰 Daily Brief</b> · {_html.escape(date)}"]
    if headline:
        lines.append(_html.escape(headline.strip()))
    if verdict:
        lines.append(f"<b>verdict:</b> {_html.escape(verdict.strip())}")

    # Key takeaways
    if bullets:
        lines.append("")
        for b in bullets[:3]:
            b = (b or "").strip()
            if not b:
                continue
            if len(b) > 140:
                b = b[:137] + "..."
            lines.append(f"• {_html.escape(b)}")

    if posture:
        lines.append("")
        lines.append(f"<b>posture:</b> {_html.escape(posture.strip()[:120])}")

    # Market sections
    _section("🌙", "OVERNIGHT", _bullets(overnight))
    _section("📊", "PRE-MARKET", _bullets(premarket))
    _section("⚡", "CATALYSTS", _bullets(catalysts))
    _section("🛢", "COMMODITIES", _bullets(commodities))
    _section("📅", "EARNINGS TODAY", _bullets(earnings_today))
    _section("🏛", "MACRO TODAY", _bullets(macro_today))

    # Alerts
    _section("⚠", "NEGATIVE NEWS", _bullets(negative_news))
    _section("👁", "WATCH LIST", _bullets(watch))

    gc = list(gov_confluence or []) if not isinstance(gov_confluence, str) else _bullets(gov_confluence)
    _section("🏛", "GOV CONFLUENCE", gc, max_items=5)

    ia = list(insider_alert or []) if not isinstance(insider_alert, str) else _bullets(insider_alert)
    _section("👤", "INSIDER ALERT", ia, max_items=3)

    footer_bits = []
    if drive_url:
        footer_bits.append(f'📄 <a href="{_html.escape(drive_url)}">Full Brief</a>')
    if pwa_url:
        footer_bits.append(f'📱 <a href="{_html.escape(pwa_url)}">PWA</a>')
    if footer_bits:
        lines.append("")
        lines.extend(footer_bits)
    return send(
        "\n".join(lines),
        parse_mode="HTML",
        message_thread_id=MULTI_DAY_SWING_TOPIC,
        disable_web_page_preview=True,
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


def ping_held_news(
    ticker: str,
    headline: str,
    sentiment_score: float,
    sentiment_label: str = "",
    source: str = "",
    url: str = "",
) -> dict:
    """
    Held-name news alert — strong-sentiment fresh headline on a ticker
    currently HELD (positions tabs). Fired by scripts/trigger_alerts.py
    from the news_sentiment tab (zero extra Finnhub quota). Before this
    lane existed, held-name news reached no push channel at all — the
    tab's only consumer was the PWA mirror.

    Dedup by headline hash in macro_alerts_state; capped per run.
    """
    import html
    body = _strip_source_suffix((headline or "").strip(), source)
    if len(body) > 200:
        body = body[:197] + "..."
    dot = "🔴" if sentiment_score < 0 else "🟢"
    label_str = f" ({html.escape(sentiment_label)})" if sentiment_label else ""
    lines = [
        f"{dot} HELD NEWS · ${html.escape(ticker)} · sentiment {sentiment_score:+.2f}{label_str}",
        html.escape(body),
    ]
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


def ping_market_pressure(
    severity: str,                  # "WARN" | "ALERT"
    spy_pct: float | None,
    qqq_pct: float | None,
    worst_held: list[tuple[str, float]] | None = None,
    posture: str = "",
) -> dict:
    """
    Index-level "time to get out" tape alert. Fired by
    scripts/trigger_alerts.py when SPY or QQQ day change crosses
    -1.25% (WARN) / -2.0% (ALERT). One page per severity per day
    (dedup in macro_alerts_state).

    Args:
        severity: "WARN" | "ALERT"
        spy_pct / qqq_pct: day change % (None when missing from feed)
        worst_held: [(ticker, day_change_pct), ...] worst-first — the
            text mini-heatmap of held names under pressure
        posture: latest exposure_posture recommendation, omitted if empty
    """
    icon = "🔴" if severity == "ALERT" else "🟠"

    def _idx(name: str, v: float | None) -> str:
        return f"{name} {v:+.1f}%" if v is not None else f"{name} ?"

    parts = [
        f"{icon} MARKET PRESSURE ({severity}): {_idx('SPY', spy_pct)} {_idx('QQQ', qqq_pct)}"
    ]
    if worst_held:
        parts.append(
            "worst held: " + ", ".join(f"{t} {c:+.1f}%" for t, c in worst_held[:5])
        )
    if posture:
        parts.append(f"posture: {posture}")
    return send(
        " | ".join(parts),
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
    context: str = "",
    held: list[str] | None = None,
) -> dict:
    """
    Edge-triggered hot-news headline ping. Fired when the macro_blackouts
    poller catches a headline matching HOT_KEYWORDS (fed/cpi/iran/tariff/
    opec/etc.) across Finnhub (general/forex/crypto/merger) + RSS feeds
    (WSJ/Bloomberg/FT/NYTimes/MarketWatch/CNBC/newsdata).

    Sent EXACTLY ONCE per news_id (dedup tracked in macro_alerts_state).
    Capped at 3 per cron run so a Finnhub backlog catch-up doesn't flood.

    The "so what" line is CONTEXT, not interpretation — it joins the headline to
    live state already computed (exposure posture + GEX gate + held tickers), so
    it costs zero AI tokens and never reads as canned filler. Deep reasoning
    still lives in the once-a-day Opus brief.

    Args:
        headline: news headline (truncated at 200 chars)
        source: publisher name (e.g. "Reuters", "Bloomberg")
        url: link to the article
        category: Finnhub/RSS category for the inline tag
        context: live regime string (e.g. "exposure CASH_PRIORITY · GEX NEGATIVE_TREND")
        held: held tickers the headline mentions (flags portfolio exposure)
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
    # "So what for my book" — free context join (no AI). Held-ticker exposure
    # flag first (most actionable), then the live regime.
    so_what = []
    if held:
        so_what.append("⚠️ you hold " + ", ".join(html.escape(t) for t in held[:4]))
    if context:
        so_what.append(html.escape(context))
    if so_what:
        lines.append("📍 " + " · ".join(so_what))
    return send(
        "\n".join(lines),
        parse_mode="HTML",
        message_thread_id=MACRO_NEWS_TOPIC,
        disable_web_page_preview=True,
    )


def ping_macro_surprise(interp: dict) -> dict:
    """Edge-triggered macro-RELEASE alert with a tailored 'so what' — keyed off
    the actual-vs-forecast surprise, so it's specific, not canned. Zero AI cost.
    `interp` is the dict from src.macro_playbook.interpret_surprise()."""
    import html

    def _n(v):
        if v is None:
            return ""
        return f"{v:g}"

    lean = interp.get("lean", "")
    emoji = {"hawkish": "🦅", "dovish": "🕊️", "risk_on": "📈", "risk_off": "📉"}.get(lean, "📊")
    unit = interp.get("unit", "") or ""
    a, fc, prev = interp.get("actual"), interp.get("forecast"), interp.get("previous")
    label = html.escape(str(interp.get("label", "")))
    direction = interp.get("direction", "")
    prev_str = f" · prev {_n(prev)}{unit}" if prev is not None else ""

    lines = [
        f"📊 <b>{label}</b> · <code>{_n(a)}{unit}</code> vs {_n(fc)}{unit} est"
        f" ({direction}{prev_str})",
        f"{emoji} <b>{lean.replace('_', ' ').title()} surprise</b> — "
        f"{html.escape(interp.get('market_take', ''))}",
        f"📍 Book: {html.escape(interp.get('book_note', ''))}",
    ]
    return send(
        "\n".join(lines),
        parse_mode="HTML",
        message_thread_id=MACRO_NEWS_TOPIC,
        disable_web_page_preview=True,
    )


def ping_curated_pick(kind: str, ticker: str, detail: str = "") -> dict:
    """Edge-triggered Motley Fool curated-pick alert. Four kinds:
      • new_rec — a name newly appears on the MF Scorecard (research, not a buy)
      • overlay — an existing MF name enters CSP-overlay range (suggestion only)
      • core    — an MF Foundational name enters the equal-weight core sleeve
      • refresh — MF emailed a new rec (login-teaser, no ticker) → refresh in-session
    Reference INPUT, never an auto-trade. Lands in the Multi Day Swing lane."""
    import html
    icon = {"new_rec": "🧠", "overlay": "📍", "core": "🟣", "refresh": "🔔"}.get(kind, "🧠")
    label = {"new_rec": "New Motley Fool rec",
             "overlay": "MF pick now in CSP-overlay range",
             "core": "MF name entered core sleeve",
             "refresh": "New MF rec emailed — refresh in-session"}.get(kind, "Motley Fool")
    body = f"{icon} {label}: <b>{html.escape(ticker)}</b>"
    if detail:
        body += f" — {html.escape(str(detail))}"
    return send(
        body + "\n<i>reference input, not auto-traded</i>",
        parse_mode="HTML",
        message_thread_id=MULTI_DAY_SWING_TOPIC,
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
    fallback_topic: int | None = None,
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
        fallback_topic: when INSIDER_TRADING_TOPIC is not configured, use
            this topic ID instead (e.g. MULTI_DAY_SWING_TOPIC). If also
            None, returns {"skipped": ...}.

    Returns:
        Telegram API response dict, or {"skipped": ...} if no topic available.

    HTML parse mode + disable_web_page_preview to keep formatting tight
    and avoid auto-link cards under the message.
    """
    target_topic = INSIDER_TRADING_TOPIC or fallback_topic
    if target_topic is None:
        return {"skipped": "No Insider Trading or fallback topic configured"}

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
        lines.append("   <i>no signals today</i>")

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
        message_thread_id=target_topic,
        disable_web_page_preview=True,
    )


# ────────────────────────────────────────────────────────────────────
# Insider Trading topic — instant alerts (new filings / contracts)
# ────────────────────────────────────────────────────────────────────

def ping_capitol_trades_new(
    filings: list[dict],
    pwa_url: str | None = None,
) -> dict:
    """
    Instant alert when new Congressional trade filings are scraped.
    Fires from fetch_congress_trades.py right after dedup — only truly
    new filings hit Telegram.

    Args:
        filings: list of dicts with keys {politician_name, party, chamber,
            ticker, issuer_name, transaction_type, amount_min, amount_max,
            filing_date, transaction_date}
        pwa_url: optional PWA link for footer
    """
    if not filings:
        return {"skipped": "no new filings"}

    target_topic = INSIDER_TRADING_TOPIC or MULTI_DAY_SWING_TOPIC
    import html

    lines = [f"🏛 <b>NEW CAPITOL TRADES</b> · {len(filings)} filing{'s' if len(filings) != 1 else ''}"]

    for f in filings[:10]:
        pol = html.escape(str(f.get("politician_name", "?"))[:25])
        party = str(f.get("party", ""))[:1]
        chamber = str(f.get("chamber", ""))[:5]
        tk = html.escape(str(f.get("ticker", "?")))
        issuer = html.escape(str(f.get("issuer_name", ""))[:30])
        ttype = str(f.get("transaction_type", "?")).upper()
        amax = float(f.get("amount_max", 0))
        amin = float(f.get("amount_min", 0))
        tx_date = str(f.get("transaction_date", ""))[:10]
        arrow = "🟢" if "buy" in ttype.lower() or "purchase" in ttype.lower() else "🔴"
        lines.append(
            f"\n{arrow} <b>{pol}</b> ({party}-{chamber})"
            f"\n   ${tk} ({issuer}) · {ttype}"
            f"\n   <code>${amin/1e3:.0f}K – ${amax/1e3:.0f}K</code> · traded {tx_date}"
        )

    if len(filings) > 10:
        lines.append(f"\n<i>+{len(filings) - 10} more</i>")

    lines.append("")
    lines.append('🔗 <a href="https://www.capitoltrades.com/trades">Verify on CapitolTrades</a>')
    if pwa_url:
        lines.append(f'📱 <a href="{html.escape(pwa_url)}">PWA</a>')

    return send(
        "\n".join(lines),
        parse_mode="HTML",
        message_thread_id=target_topic,
        disable_web_page_preview=True,
    )


def ping_gov_contracts_new(
    contracts: list[dict],
    unmapped_count: int = 0,
    pwa_url: str | None = None,
) -> dict:
    """
    Instant alert when new government contract awards are fetched.
    Fires from fetch_gov_contracts.py — only new (deduped) awards with
    resolved tickers are shown (unmapped ones just get a count).

    Args:
        contracts: list of dicts with keys {ticker, recipient_name,
            award_amount, agency, naics_description, action_date}
        unmapped_count: how many new unmapped-but-large awards were flagged
        pwa_url: optional PWA link for footer
    """
    if not contracts and unmapped_count == 0:
        return {"skipped": "no new contracts"}

    target_topic = INSIDER_TRADING_TOPIC or MULTI_DAY_SWING_TOPIC
    import html

    mapped = [c for c in contracts if c.get("ticker")]
    total_dollars = sum(float(c.get("award_amount", 0)) for c in mapped)

    lines = [
        f"🏦 <b>NEW GOV CONTRACTS</b> · {len(contracts)} award{'s' if len(contracts) != 1 else ''}"
        f" · <code>${total_dollars/1e6:.1f}M</code> mapped"
    ]

    for c in sorted(mapped, key=lambda x: float(x.get("award_amount", 0)), reverse=True)[:8]:
        tk = html.escape(str(c.get("ticker", "?")))
        recip = html.escape(str(c.get("recipient_name", ""))[:35])
        amt = float(c.get("award_amount", 0))
        agency = html.escape(str(c.get("agency", ""))[:25])
        naics = html.escape(str(c.get("naics_description", ""))[:30])
        # Materiality: how big is this award vs the company? % of REVENUE is the
        # right denominator (a contract is revenue), plus the raw market cap and
        # the label so it reads "is this a catalyst or a rounding error".
        cap = float(c.get("market_cap", 0) or 0)
        pct_rev = float(c.get("pct_rev", 0) or 0)
        mat = str(c.get("materiality", "") or "")
        mbits = []
        if pct_rev > 0:
            mbits.append(f"{pct_rev*100:.1f}% of rev")
        if cap > 0:
            mbits.append(f"${cap/1e9:.1f}B cap")
        if mat:
            mbits.append(f"<b>{mat}</b>")
        mline = ("\n   " + " · ".join(mbits)) if mbits else ""
        lines.append(
            f"\n  <b>${tk}</b> · <code>${amt/1e6:.1f}M</code>"
            f"\n   {recip} · {agency}"
            f"\n   {naics}"
            f"{mline}"
        )

    if len(mapped) > 8:
        lines.append(f"\n<i>+{len(mapped) - 8} more mapped</i>")

    if unmapped_count:
        lines.append(f"\n⚠ {unmapped_count} large unmapped recipient{'s' if unmapped_count != 1 else ''} flagged for review")

    lines.append("")
    lines.append('🔗 <a href="https://www.usaspending.gov/search/?hash=all-awards">Verify on USAspending</a>')
    if pwa_url:
        lines.append(f'📱 <a href="{html.escape(pwa_url)}">PWA</a>')

    return send(
        "\n".join(lines),
        parse_mode="HTML",
        message_thread_id=target_topic,
        disable_web_page_preview=True,
    )


# ────────────────────────────────────────────────────────────────────
# Options Intel topic — daily scan results + strategy alerts
# ────────────────────────────────────────────────────────────────────

def ping_options_intel(
    date: str,
    candidates: list[dict],
    pwa_url: str | None = None,
    banner: str | None = None,
) -> dict:
    """
    Post the daily options scan digest to the Options Intel topic.

    Groups candidates by strategy (CSP, CC, LONG_CALL, etc.) and
    formats each with strike/expiry/premium/yield/quality info.

    Args:
        date: scan date "YYYY-MM-DD"
        candidates: list of scan_results dicts with keys {ticker, strategy,
            strike, expiry, dte, premium, annual_yield_pct, delta, iv,
            composite_score, catalyst_flag, underlying_last, cash_required,
            breakeven, hv30, ...}
        pwa_url: optional PWA link for footer
        banner: optional notice line(s) rendered right under the header —
            used by the SELL_CAUTION / CASH_PRIORITY digest gate so suppressed
            recommendations are VISIBLE silence, never a glitch. When a banner
            is present the digest sends even with zero candidates.
    """
    if not candidates and not banner:
        return {"skipped": "no candidates to post"}

    import html as _html

    # Group by strategy
    by_strat: dict[str, list[dict]] = {}
    for c in candidates:
        s = c.get("strategy", "OTHER")
        by_strat.setdefault(s, []).append(c)

    # ── 3-phase management rules (tastytrade) ──────────────────
    # Each strategy has entry, manage, and exit rules so the
    # Telegram push includes the full lifecycle, not just signals.
    mgmt_rules: dict[str, tuple[str, str, str]] = {
        "CSP": (
            "35 DTE · 20-30Δ OTM · yield ≥12% ann",
            "Close at 50% profit · roll down+out if challenged",
            "50% profit OR assignment → wheel into CC",
        ),
        "CC": (
            "35 DTE · 10-20Δ OTM · yield ≥10% ann",
            "Close at 50% profit · let ride if far OTM",
            "50% profit OR assignment → wheel into CSP",
        ),
        "PCS": (
            "42 DTE · 25Δ short put · credit ≥1/3 width · IVR≥25",
            "Close at 50% profit · roll if short strike tested",
            "50% profit OR 21 DTE mech close · stop at 2× credit",
        ),
        "CCS": (
            "42 DTE · 25Δ short call · credit ≥1/3 width · IVR≥25",
            "Close at 50% profit · roll if short strike tested",
            "50% profit OR 21 DTE mech close · stop at 2× credit",
        ),
        "IC": (
            "45 DTE · 20Δ short strikes · credit/width ≥30% · IVR>40",
            "Close at 50% profit · roll untested side if one tested",
            "50% profit OR 21 DTE mech close · stop at 2× credit",
        ),
        "LONG_CALL": (
            "45 DTE · 50Δ ATM · quality ≥40 · catalyst-driven",
            "Trail stop at 50% of max gain · re-evaluate at 21 DTE",
            "Take profit at 50-100% gain · stop at 50% loss",
        ),
        "PMCC": (
            "LEAPS 70Δ ITM 9+mo · short 25Δ OTM 30-45 DTE",
            "Roll short at 50% profit or 21 DTE · extrinsic value rule",
            "Close if LEAPS under 6mo remaining · stop if LEAPS breached",
        ),
    }

    # Strategy display config: (emoji, label, sort_key, max_show)
    strat_config = {
        "CSP":       ("💰", "CASH-SECURED PUTS",    "annual_yield_pct", 5),
        "CC":        ("📞", "COVERED CALLS",         "annual_yield_pct", 5),
        "LONG_CALL": ("🚀", "LONG CALLS",            "composite_score",  5),
        "PCS":       ("📉", "PUT CREDIT SPREADS",    "annual_yield_pct", 5),
        "CCS":       ("📈", "CALL CREDIT SPREADS",   "annual_yield_pct", 5),
        "IC":        ("🦅", "IRON CONDORS",           "annual_yield_pct", 5),
        "PMCC":      ("🔗", "POOR MAN'S CC",         "composite_score",  5),
    }

    lines = [f"<b>🔬 OPTIONS INTEL</b> · {_html.escape(date)}"]
    lines.append(f"{len(candidates)} candidate{'s' if len(candidates) != 1 else ''} found")
    if banner:
        lines.append("")
        lines.append(_html.escape(banner))

    for strat_key in ["CSP", "CC", "PCS", "CCS", "IC", "LONG_CALL", "PMCC"]:
        items = by_strat.pop(strat_key, [])
        if not items:
            continue
        emoji, label, sort_key, max_show = strat_config[strat_key]
        items.sort(key=lambda c: float(c.get(sort_key, 0)), reverse=True)

        lines.append("")
        lines.append(f"{emoji} <b>{label}</b> ({len(items)})")
        # 3-phase rules — compact one-liner per strategy
        entry_r, manage_r, exit_r = mgmt_rules.get(strat_key, ("", "", ""))
        if manage_r:
            lines.append(f"  <i>📋 {_html.escape(manage_r)} · {_html.escape(exit_r)}</i>")

        for c in items[:max_show]:
            tk = _html.escape(str(c.get("ticker", "?")))
            strike = float(c.get("strike", 0))
            exp = str(c.get("expiry", ""))
            # Format expiry from YYYYMMDD to MM/DD
            if len(exp) == 8:
                exp = f"{exp[4:6]}/{exp[6:]}"
            dte = int(c.get("dte", 0))
            prem = float(c.get("premium", 0))
            price = float(c.get("underlying_last", 0))

            if strat_key in ("CSP", "CC"):
                yld = float(c.get("annual_yield_pct", 0))
                delta = abs(float(c.get("delta", 0)))
                iv = float(c.get("iv", 0))
                lines.append(
                    f"  <b>${tk}</b> ${strike:.0f} {exp} ({dte}d)"
                    f" · <code>${prem:.2f}</code>"
                    f" · {yld:.0f}% ann"
                    f" · Δ{delta:.2f} · IV {iv:.0f}%"
                )
            elif strat_key in ("PCS", "CCS", "IC"):
                # Multi-leg income — show credit, yield, notes (leg detail)
                yld = float(c.get("annual_yield_pct", 0))
                ivr = float(c.get("iv_rank", 0))
                notes = _html.escape(str(c.get("notes", "")))
                lines.append(
                    f"  <b>${tk}</b> {notes} ({dte}d)"
                    f" · <code>${prem:.2f}</code> cr"
                    f" · {yld:.0f}% ann"
                    f" · IVR≈{ivr:.0f}"
                )
            else:
                # LONG_CALL / PMCC — show quality score + catalyst
                quality = float(c.get("composite_score", 0))
                cash = float(c.get("cash_required", 0))
                be = float(c.get("breakeven", 0))
                catalyst = " ⚡" if c.get("catalyst_flag") else ""
                notes_str = str(c.get("notes", ""))
                if notes_str:
                    lines.append(
                        f"  <b>${tk}</b> {_html.escape(notes_str)} ({dte}d)"
                        f" · <code>${prem:.2f}</code>"
                        f" · Q{quality:.0f}{catalyst}"
                        f" · ${cash:.0f} risk"
                    )
                else:
                    lines.append(
                        f"  <b>${tk}</b> ${strike:.0f}C {exp} ({dte}d)"
                        f" · <code>${prem:.2f}</code>"
                        f" · Q{quality:.0f}{catalyst}"
                        f" · BE ${be:.0f} · ${cash:.0f} risk"
                    )

        if len(items) > max_show:
            lines.append(f"  <i>+{len(items) - max_show} more in PWA</i>")

    # Catch any other strategies
    for strat_key, items in by_strat.items():
        if items:
            lines.append("")
            lines.append(f"📋 <b>{_html.escape(strat_key)}</b> ({len(items)})")
            for c in items[:3]:
                tk = _html.escape(str(c.get("ticker", "?")))
                strike = float(c.get("strike", 0))
                lines.append(f"  <b>${tk}</b> ${strike:.0f}")

    if pwa_url:
        lines.append("")
        lines.append(f'📱 <a href="{_html.escape(pwa_url)}">Full scan in PWA</a>')

    return send(
        "\n".join(lines),
        parse_mode="HTML",
        message_thread_id=OPTIONS_INTEL_TOPIC,
        disable_web_page_preview=True,
    )


def ping_daily_plan_diff(
    date: str,
    lean: str,
    diff: dict,
    pwa_url: str | None = None,
) -> dict:
    """One compact "what changed in today's plan" headline → Options Intel.

    User-approved (2026-06-10): the push is the HEADLINE (added/dropped
    opportunities + the macro-lean tilt, with each row's actionable detail
    inline); the PWA's Today's Plan card stays the full-detail view. Caller is
    edge-triggered — this only fires when something actually changed.

    `diff` = build_daily_plan.plan_diff() output:
        {"added": [plan-row dicts], "dropped": [(ticker, strategy), ...]}
    """
    import html as _html

    added = diff.get("added") or []
    dropped = diff.get("dropped") or []
    if not added and not dropped:
        return {"skipped": "no plan changes"}

    lines = [f"<b>📋 PLAN CHANGES</b> · {_html.escape(date)} · lean {_html.escape(lean)}"]
    for p in added[:8]:
        tk = _html.escape(str(p.get("ticker", "?")))
        strat = _html.escape(str(p.get("strategy", "")))
        detail = _html.escape(str(p.get("detail", ""))[:70])
        conv = float(p.get("conviction", 0) or 0)
        lines.append(f"  ➕ <b>{tk}</b> {strat} · conv {conv:.0f} · {detail}")
    if len(added) > 8:
        lines.append(f"  <i>+{len(added) - 8} more added</i>")
    for tk, strat in dropped[:8]:
        lines.append(f"  ➖ <b>{_html.escape(str(tk))}</b> {_html.escape(str(strat))} dropped")
    if len(dropped) > 8:
        lines.append(f"  <i>+{len(dropped) - 8} more dropped</i>")
    if pwa_url:
        lines.append(f'📱 <a href="{_html.escape(pwa_url)}">Full plan in PWA</a>')

    return send(
        "\n".join(lines),
        parse_mode="HTML",
        message_thread_id=OPTIONS_INTEL_TOPIC,
        disable_web_page_preview=True,
    )


def ping_options_defense(
    date: str,
    defense_alerts: list[dict] | None = None,
    exit_alerts: list[dict] | None = None,
    pwa_url: str | None = None,
) -> dict:
    """
    Push defense brief alerts + actionable exit plan alerts to Options Intel.

    Only surfaces alerts that require action — CRITICAL/HIGH defense alerts
    and exit plans with status != HEALTHY/HOLD. Keeps the Telegram push
    tight; full detail lives in the sheet/PWA.

    Args:
        date: ISO YYYY-MM-DD
        defense_alerts: list of dicts from build_defense_brief() with keys
            {severity, title, description, action, ticker, account, ...}
            — only CRITICAL and HIGH are pushed
        exit_alerts: list of dicts with keys {account, ticker, position_type,
            status, recommendation, profit_capture_pct, reasoning}
            — only non-HEALTHY/HOLD statuses are pushed
        pwa_url: optional PWA link for footer
    """
    import html as _html

    defense = list(defense_alerts or [])
    exits = list(exit_alerts or [])

    # Filter to actionable alerts only
    critical_high = [a for a in defense if a.get("severity") in ("CRITICAL", "HIGH")]
    actionable_exits = [
        e for e in exits
        if e.get("status") not in ("HEALTHY", "HOLD", "LET_EXPIRE", "")
    ]

    if not critical_high and not actionable_exits:
        return {"skipped": "no actionable defense/exit alerts"}

    lines = [f"<b>🛡 OPTIONS DEFENSE</b> · {_html.escape(date)}"]

    # ── Defense alerts (CRITICAL/HIGH only) ──────────────────────────
    if critical_high:
        lines.append("")
        for a in critical_high[:8]:
            sev = a.get("severity", "HIGH")
            emoji = "🔴" if sev == "CRITICAL" else "🟠"
            title = _html.escape(str(a.get("title", ""))[:80])
            desc = _html.escape(str(a.get("description", ""))[:120])
            action = _html.escape(str(a.get("action", ""))[:100])
            lines.append(f"{emoji} <b>[{sev}]</b> {title}")
            if desc:
                lines.append(f"  {desc}")
            if action:
                lines.append(f"  → {action}")

    # ── Exit plan alerts (actionable only) ────────────────────────────
    if actionable_exits:
        lines.append("")
        lines.append("<b>📋 EXIT ALERTS</b>")

        # Status → emoji mapping
        status_emoji = {
            "STOP_TRIGGERED": "🔴",
            "PROFIT_TARGET_HIT": "🟢",
            "MECHANICAL_CLOSE": "⏰",
            "ROLL_OR_CLOSE": "🔄",
            "ROLL_OR_ASSIGN": "🔄",
            "STOP_ROLL": "🛑",
            "BREACH_WARNING": "⚠",
            "CATALYST_WARNING": "⚡",
            "WARNING": "🟡",
            "BAG": "💼",
            "TIME_STOP": "⏳",
            "T1_HIT": "🎯",
            "T2_HIT": "🎯",
            "EXPIRED": "📅",
        }

        for e in actionable_exits[:10]:
            acct = str(e.get("account", ""))[:6]
            tk = _html.escape(str(e.get("ticker", "?")))
            pos = str(e.get("position_type", ""))
            status = str(e.get("status", ""))
            emoji = status_emoji.get(status, "📋")
            rec = _html.escape(str(e.get("recommendation", ""))[:140])
            profit = float(e.get("profit_capture_pct", 0))

            # Compact position type label
            type_label = pos.replace("OPTION_", "").replace("SPREAD_", "📊 ")

            line = f"{emoji} <b>${tk}</b> {type_label}"
            if acct:
                line += f" · {acct}"
            if profit != 0:
                line += f" · {profit:+.0f}%"
            lines.append(line)
            if rec:
                lines.append(f"  {rec}")

        if len(actionable_exits) > 10:
            lines.append(f"  <i>+{len(actionable_exits) - 10} more in PWA</i>")

    if pwa_url:
        lines.append("")
        lines.append(f'📱 <a href="{_html.escape(pwa_url)}">Full detail in PWA</a>')

    return send(
        "\n".join(lines),
        parse_mode="HTML",
        message_thread_id=OPTIONS_INTEL_TOPIC,
        disable_web_page_preview=True,
    )


def ping_spread_defense(
    ticker: str,
    right: str,            # "P" | "C"
    strike: float,
    expiry: str,           # "YYYYMMDD"
    dte: int,
    underlying: float,
    level: str,            # "approach" | "breach"
    label: str = "",       # "PCS 180/190" | "CCS 350/360" | "CSP" | "CC"
    account: str = "",
) -> dict:
    """
    Short-strike proximity alert for a HELD option leg. Fired by
    scripts/trigger_alerts.py when the underlying trades into the
    approach band (puts: ≤ strike×1.03, calls: ≥ strike×0.97) or
    through the short strike itself (breach). Each level pages once
    per position per day (dedup in macro_alerts_state).

    Intraday option marks aren't in the 5-min feed, so the message
    can't show mark-vs-credit — it says so and points at the action.
    """
    exp = str(expiry)
    if len(exp) == 8:
        exp = f"{exp[4:6]}-{exp[6:]}"
    r = (right or "").upper()[:1]
    if level == "breach":
        head = "🛡️🔴 DEFENSE BREACH"
        rel = f"{underlying:.2f} {'≤' if r == 'P' else '≥'} short {strike:g}{r}"
        tail = "Short strike breached — roll/close now."
    else:
        head = "🛡️ DEFENSE"
        if r == "P":
            rel = f"{underlying:.2f} ≤ short {strike:g}P ×1.03"
        else:
            rel = f"{underlying:.2f} ≥ short {strike:g}C ×0.97"
        tail = "Mark vs credit unknown — review/roll/close."
    ctx = f"{label} exp {exp}, {dte} DTE" if label else f"exp {exp}, {dte} DTE"
    if account:
        ctx += f", {account}"
    return send(
        f"{head}: {ticker} {rel} ({ctx}). {tail}",
        parse_mode="none",
        message_thread_id=OPTIONS_INTEL_TOPIC,
    )


def ping_unusual_options(
    date: str,
    alerts: list[dict],
    total_scanned: int = 0,
    total_alerts: int = 0,
    pwa_url: str | None = None,
) -> dict:
    """Push unusual options activity alerts to Options Intel topic."""
    import html as _html

    if not alerts:
        return {"skipped": "no UOA alerts"}

    sev_icon = {1: "⚡", 2: "🔥", 3: "🚨"}
    type_label = {
        "VOL_OI_SPIKE": "Vol/OI",
        "STRIKE_CONC": "Concentration",
        "OTM_FLOW": "OTM Flow",
        "PC_SKEW": "P/C Skew",
    }

    lines = [f"<b>🔍 UNUSUAL OPTIONS ACTIVITY</b> · {_html.escape(date)}"]
    lines.append(f"Scanned {total_scanned} tickers · {total_alerts} total alerts")
    lines.append("")

    for a in alerts:
        icon = sev_icon.get(a.get("severity", 1), "⚡")
        tk = _html.escape(str(a.get("ticker", "?")))
        atype = type_label.get(a.get("alert_type", ""), a.get("alert_type", ""))
        side = a.get("side", "")
        strike = float(a.get("strike", 0))
        expiry = a.get("expiry", "")
        vol = int(a.get("volume", 0))
        oi = int(a.get("open_interest", 0))
        notional = float(a.get("notional", 0))
        price = float(a.get("underlying_last", 0))
        opt_price = float(a.get("option_price", 0))
        moneyness = a.get("moneyness", "")
        vol_oi = float(a.get("vol_oi_ratio", 0))

        # Directional lean — naive read: CALL=bullish, PUT=bearish
        dir_icon = "📈" if side == "CALL" else "📉"
        side_label = side.upper() if side else "?"

        if a.get("alert_type") == "PC_SKEW":
            lean = "Bullish" if side == "CALL" else "Bearish"
            lines.append(f"{icon} <b>${tk}</b> {dir_icon} {lean} [{atype}]")
            detail = _html.escape(str(a.get("detail", "")))
            lines.append(f"    {detail}")
        else:
            # Clear format: "🚨 $PLTR 📉 PUT $350 · Jun 18 · ITM · @$136.88"
            # Show side explicitly, strike, expiry, moneyness, underlying
            strike_str = f"${strike:.0f}" if strike > 0 else ""
            price_str = f"@${price:.2f}" if price > 0 else ""
            opt_str = f" · 💰${opt_price:.2f}" if opt_price > 0 else ""
            money_str = f" · {moneyness}" if moneyness else ""

            lines.append(
                f"{icon} <b>${tk}</b> {dir_icon} {side_label} {strike_str}{opt_str} · "
                f"{expiry}{money_str} · {price_str} [{atype}]"
            )

            # Detail line: explicit contract count with side label
            notional_str = (
                f"${notional / 1_000_000:.1f}M" if notional >= 1_000_000
                else f"${notional / 1_000:.0f}K" if notional >= 1_000
                else f"${notional:.0f}"
            )
            oi_str = f" vs {oi:,} OI" if oi > 0 else " (new position)"
            vol_oi_str = f" · {vol_oi:.1f}x Vol/OI" if vol_oi >= 3 else ""
            lines.append(
                f"    {vol:,} {side_label}S{oi_str} · "
                f"{notional_str} notional{vol_oi_str}"
            )
        lines.append("")

    if pwa_url:
        lines.append(f'📱 <a href="{_html.escape(pwa_url)}">Full alerts in PWA → Flow tab</a>')

    return send(
        "\n".join(lines),
        parse_mode="HTML",
        message_thread_id=OPTIONS_INTEL_TOPIC,
        disable_web_page_preview=True,
    )