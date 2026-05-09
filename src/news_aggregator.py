"""RSS-based news aggregator — Bloomberg, WSJ, MarketWatch, CNBC, Yahoo.

Finnhub's `general` category is Reuters-heavy. To get the same
publisher mix that Caspar gets in his WSJ "What's News" and Bloomberg
emails, we pull a handful of free RSS feeds directly. No API key, no
rate limits worth worrying about, and stdlib-only XML parsing so we
don't pull in feedparser as another dependency.

Each item is normalised to the same dict shape as Finnhub news items
(`id`, `datetime`, `headline`, `summary`, `source`, `url`, `category`,
`hot`) so `macro_blackouts.MacroFeed._refresh_news` can merge them
side-by-side and dedupe by URL.

Failures are isolated — one feed timing out doesn't kill the others.
The aggregator returns whatever it managed to collect, which is the
right behaviour for a cron that runs every 10 min: a missed pull just
means we'll catch the headline next iteration.
"""
from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

log = logging.getLogger(__name__)

# Curated free-tier RSS feeds. Each entry: (source label, url, category).
# Order matters for the dedupe-by-URL pass — earlier sources win when an
# item appears in multiple feeds (which happens often, e.g. WSJ Markets
# vs CNBC carrying the same wire piece).
RSS_SOURCES: list[tuple[str, str, str]] = [
    # WSJ Markets — Caspar reads the WSJ "What's News" emails so this
    # is the most-trusted source. Free RSS, no paywall on the headline+
    # summary even if the article is gated.
    ("WSJ",        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",         "wsj"),
    ("WSJ Opinion","https://feeds.a.dj.com/rss/RSSOpinion.xml",             "wsj"),
    # Bloomberg Markets — usually the freshest macro takes; readable
    # headlines + 1-2 sentence summaries.
    ("Bloomberg",  "https://feeds.bloomberg.com/markets/news.rss",          "bloomberg"),
    ("Bloomberg",  "https://feeds.bloomberg.com/economics/news.rss",        "bloomberg"),
    ("Bloomberg",  "https://feeds.bloomberg.com/politics/news.rss",         "bloomberg"),
    # MarketWatch top stories — Dow Jones brand, broad coverage including
    # earnings/corporate actions.
    ("MarketWatch","https://www.marketwatch.com/rss/topstories",            "marketwatch"),
    ("MarketWatch","https://www.marketwatch.com/rss/marketpulse",           "marketwatch"),
    # CNBC top news — fast-moving, often picks up commentary that the
    # wires miss (Cramer reactions, Fed-watcher takes).
    ("CNBC",       "https://www.cnbc.com/id/100003114/device/rss/rss.html", "cnbc"),
    ("CNBC Markets","https://www.cnbc.com/id/15839135/device/rss/rss.html", "cnbc"),
]
# Note: Reuters business RSS is no longer free as of late 2024. Finnhub
# `general` already surfaces Reuters wires. Yahoo Finance and Investing.com
# RSS feeds returned empty in testing — left out rather than logging
# warnings every cron run.


def _parse_pubdate(s: str) -> datetime | None:
    """Parse RFC-2822 (`Mon, 01 Jan 2026 12:00:00 GMT`) → UTC datetime.

    Falls back to `None` on garbage; the caller drops items missing
    a parseable timestamp so they don't get a sentinel `0` epoch and
    show up as 1970 in the ranking.
    """
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(s: str) -> str:
    """Cheap HTML-to-text. RSS summaries often embed CDATA + HTML; the
    Telegram ping wants plain text, so strip tags and collapse whitespace."""
    if not s:
        return ""
    s = _HTML_TAG_RE.sub("", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


def _stable_id(url: str, headline: str) -> int:
    """Deterministic 63-bit int id from url+headline.

    Finnhub items have a real `id`. RSS items don't — but the dedup logic
    in trigger_alerts uses `news:{id}` as a sheet key, so we synthesise
    one from a hash. Same input → same id, so reruns are idempotent.
    """
    h = hashlib.sha1(f"{url}\n{headline}".encode("utf-8", errors="ignore")).hexdigest()
    # 16 hex chars = 64 bits; mask to 63 to fit a positive signed int64.
    return int(h[:16], 16) & ((1 << 63) - 1)


def fetch_rss(label: str, url: str, category: str, timeout: float = 8.0) -> list[dict]:
    """Pull and parse a single RSS feed. Returns normalised items.

    Defensive — any parse error returns []; one bad feed shouldn't break
    the aggregator. Logs at warning level so the cron output flags issues.
    """
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "FinancePWA-news-aggregator/1.0"},
        )
        r.raise_for_status()
    except Exception as e:
        log.warning("RSS %s fetch failed: %s", label, e)
        return []

    try:
        # `r.content` (bytes) — let ElementTree pick up the encoding from
        # the XML declaration. Passing `r.text` strips it and breaks UTF-8
        # for some feeds (Bloomberg in particular).
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        log.warning("RSS %s parse failed: %s", label, e)
        return []

    out: list[dict] = []
    # RSS 2.0 spec: items live at /rss/channel/item; Atom uses /feed/entry.
    # Try both — some feeds (Reuters Agency) are Atom even though the URL
    # ends `.rss`.
    items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for it in items:
        # RSS fields
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        desc = (it.findtext("description") or "").strip()
        pub = it.findtext("pubDate") or it.findtext("{http://www.w3.org/2005/Atom}published") or ""
        # Atom fields fallback
        if not link:
            link_el = it.find("{http://www.w3.org/2005/Atom}link")
            if link_el is not None:
                link = link_el.attrib.get("href", "")
        if not title:
            title = (it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        if not desc:
            desc = (it.findtext("{http://www.w3.org/2005/Atom}summary") or "").strip()

        if not title:
            continue

        ts = _parse_pubdate(pub)
        if ts is None:
            # No timestamp → skip. Keeps ranking sane.
            continue

        summary = _strip_html(desc)[:200]
        out.append({
            "id":       _stable_id(link or title, title),
            "datetime": ts.isoformat(),
            "headline": _strip_html(title),
            "summary":  summary,
            "source":   label,
            "url":      link,
            "category": category,
            # `hot` is filled by the caller after merge so all sources
            # use the same HOT_KEYWORDS list (kept in macro_blackouts).
        })

    log.info("RSS %s: %d items", label, len(out))
    return out


def aggregate_rss(timeout: float = 8.0) -> list[dict]:
    """Pull every configured feed and return a flat list of items.

    The caller merges this with the Finnhub feed and dedupes by URL.
    Per-feed timeouts are independent — total wall time is bounded by
    the slowest single feed (sequential pulls; the cron runs once every
    ~10 min so threading isn't worth the complexity).
    """
    out: list[dict] = []
    for label, url, category in RSS_SOURCES:
        out.extend(fetch_rss(label, url, category, timeout=timeout))
    return out
