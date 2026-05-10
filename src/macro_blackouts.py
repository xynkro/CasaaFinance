"""Macro news + economic-calendar blackout windows.

Ported from ZeroDTE's `backend/app/macro_news.py` so both projects share
the same blackout logic. The original is async (httpx polling loop in a
FastAPI worker); this version is sync (one-shot fetch per cron run) which
matches FinancePWA's batch execution model.

Why this matters for FinancePWA:
The trigger_alerts cron fires Telegram pushes the moment a watching
decision crosses act_now. Without blackout awareness, a row crossing
its trigger 5 min before FOMC would page "ACT NOW" — the same failure
mode that blew up Caspar's iron condor account ("Operation Midnight
Hammer"), just translated to the swing book. With this module wired in,
trigger_alerts checks `in_blackout_window()` first and defers pushes
within ±15 min of high-impact US events.

Usage (one-shot from a cron):

    from src.macro_blackouts import MacroFeed
    feed = MacroFeed.fetch()              # synchronous; returns populated feed
    in_bo, event = feed.in_blackout_window()
    if in_bo:
        log.info(f"In blackout — {event['event']} in {event['_minutes_until']}min")

The `fetch()` classmethod is the only entry point we need on the
FinancePWA side. The original async polling loop is intentionally
omitted — long-lived state is the FastAPI/orchestrator's job, not the
batch cron's.

Shared HOT_KEYWORDS list is preserved verbatim so news classification
agrees across both projects (the Iran/tariff/FOMC list).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

FINNHUB_BASE = "https://finnhub.io/api/v1"

# Blackout window: how close to a high-impact event we suppress signals.
# Same values as ZeroDTE — kept identical so behaviour matches across
# projects. If you tune one, tune the other.
BLACKOUT_BEFORE_MIN = 15
BLACKOUT_AFTER_MIN  = 5

# Keywords for hot-topic news that could move markets sharply. Drives the
# only filter the macro-news cron applies — a headline pings if any of
# these substrings appear in the headline or summary. Originally aligned
# with ZeroDTE's list; extended here with a few macro-relevant terms
# (opec, recession, sanction, dovish, hawkish, oil tanker) that previously
# slipped through the gate but were caught by the now-deleted
# interpret_headline heuristic.
HOT_KEYWORDS = [
    # Fed / rates
    "fed", "fomc", "powell", "rate cut", "rate hike", "inflation",
    "cpi", "ppi", "dovish", "hawkish",
    # Jobs / growth
    "jobs", "payroll", "unemployment", "gdp", "recession",
    # Geopolitics / energy
    "war", "strike", "missile", "attack", "sanction",
    "iran", "russia", "ukraine", "china",
    "opec", "oil tanker", "crude supply",
    # Politics / fiscal
    "tariff", "trade war", "trump", "biden", "election", "shutdown",
    # Market structure
    "spx", "spy", "circuit breaker", "crash", "rally",
]


def is_hot_news(headline: str, summary: str = "") -> bool:
    """True if the headline/summary contains any high-impact keyword.

    Mirrors ZeroDTE's `_is_hot_news()`. Public here so the brain prompts
    + decision pipeline can flag headlines without re-reading the list.
    """
    text = (headline + " " + summary).lower()
    return any(kw in text for kw in HOT_KEYWORDS)


@dataclass
class MacroFeed:
    """One-shot snapshot of Finnhub news + US economic calendar.

    Built via `MacroFeed.fetch()` (synchronous) — pulls both feeds and
    returns a populated instance. After construction, `next_high_impact()`
    and `in_blackout_window()` are pure-Python (no further network).
    """
    news: list[dict] = field(default_factory=list)
    calendar: list[dict] = field(default_factory=list)
    fetched_at: datetime | None = None

    @classmethod
    def fetch(cls, api_key: str | None = None, timeout: float = 15.0) -> "MacroFeed":
        """Pull both feeds. Empty MacroFeed if FINNHUB_API_KEY is unset
        (graceful degrade — caller continues without blackout gating)."""
        key = api_key or os.environ.get("FINNHUB_API_KEY", "")
        if not key:
            log.warning("FINNHUB_API_KEY not set — MacroFeed disabled")
            return cls()

        feed = cls(fetched_at=datetime.now(timezone.utc))
        feed._refresh_news(key, timeout)
        feed._refresh_calendar(key, timeout)
        return feed

    # Finnhub general-news is Reuters-heavy. Pulling forex/crypto/merger
    # broadens the source mix without exploding API quota — each call is
    # one credit and we run this every 10 min. Order matters: `general`
    # first so its items dominate the head of the list when timestamps tie.
    NEWS_CATEGORIES = ("general", "forex", "crypto", "merger")

    def _refresh_news(self, api_key: str, timeout: float) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        seen_urls: set[str] = set()
        seen_ids: set[int] = set()
        out: list[dict] = []

        # ── Finnhub feeds (4 categories) ────────────────────────────────
        for cat in self.NEWS_CATEGORIES:
            try:
                r = requests.get(
                    f"{FINNHUB_BASE}/news",
                    params={"category": cat, "token": api_key},
                    timeout=timeout,
                )
                r.raise_for_status()
                raw = r.json() or []
            except Exception as e:
                log.warning("MacroFeed news[%s] fetch failed: %s", cat, e)
                continue

            for n in raw:
                ts = datetime.fromtimestamp(n.get("datetime", 0), tz=timezone.utc)
                if ts < cutoff:
                    continue
                nid = n.get("id")
                url = n.get("url", "")
                if nid and nid in seen_ids:
                    continue
                if url and url in seen_urls:
                    continue
                if nid:
                    seen_ids.add(nid)
                if url:
                    seen_urls.add(url)
                headline = n.get("headline", "")
                summary = (n.get("summary") or "")[:200]
                out.append({
                    "id": nid,
                    "datetime": ts.isoformat(),
                    "headline": headline,
                    "summary": summary,
                    "source": n.get("source", ""),
                    "url": url,
                    "category": cat,
                    "hot": is_hot_news(headline, summary),
                })

        # ── RSS aggregator (WSJ, Bloomberg, MarketWatch, CNBC) ──────────
        # Imported lazily so a missing module doesn't break Finnhub-only
        # operation. Failures inside aggregate_rss are logged and dropped.
        try:
            from .news_aggregator import aggregate_rss
        except ImportError:
            try:
                from src.news_aggregator import aggregate_rss
            except ImportError:
                aggregate_rss = None  # type: ignore[assignment]
        if aggregate_rss is not None:
            try:
                rss_items = aggregate_rss(timeout=timeout)
            except Exception as e:
                log.warning("MacroFeed RSS aggregate failed: %s", e)
                rss_items = []
            for item in rss_items:
                try:
                    ts = datetime.fromisoformat(item["datetime"])
                except (KeyError, ValueError):
                    continue
                if ts < cutoff:
                    continue
                url = item.get("url", "")
                rid = item.get("id")
                # Dedup — RSS items often duplicate Finnhub by URL.
                if url and url in seen_urls:
                    continue
                if rid and rid in seen_ids:
                    continue
                if url:
                    seen_urls.add(url)
                if rid:
                    seen_ids.add(rid)
                headline = item.get("headline", "")
                summary = item.get("summary", "")
                out.append({
                    **item,
                    "hot": is_hot_news(headline, summary),
                })

        out.sort(key=lambda x: x["datetime"], reverse=True)
        self.news = out[:80]  # widened — 4 Finnhub buckets + 4 RSS feeds
        sources = {x["source"] for x in self.news if x.get("source")}
        log.info(
            "MacroFeed news: %d items (%d hot) across %d sources",
            len(out), sum(1 for x in out if x["hot"]), len(sources),
        )

    def _refresh_calendar(self, api_key: str, timeout: float) -> None:
        try:
            today = datetime.now(ET).date()
            end = today + timedelta(days=14)
            r = requests.get(
                f"{FINNHUB_BASE}/calendar/economic",
                params={"token": api_key, "from": today.isoformat(), "to": end.isoformat()},
                timeout=timeout,
            )
            r.raise_for_status()
            raw = r.json()
        except Exception as e:
            log.warning("MacroFeed calendar fetch failed: %s", e)
            return

        events: list[dict] = []
        for e in raw.get("economicCalendar", []) or []:
            # Match ZeroDTE: US events only (the swing book is also US-dominant).
            if (e.get("country") or "") != "US":
                continue
            events.append({
                "country": e.get("country"),
                "event": e.get("event", ""),
                "impact": e.get("impact", "low"),
                "time": e.get("time", ""),     # "YYYY-MM-DD HH:MM:SS" UTC
                "estimate": e.get("estimate"),
                "actual": e.get("actual"),
                "prev": e.get("prev"),
                "unit": e.get("unit"),
            })
        events.sort(key=lambda x: x["time"])
        self.calendar = events
        log.info("MacroFeed calendar: %d US events (next 14d)", len(events))

    # ----- Blackout helpers (pure-Python after fetch) -------------------

    def next_high_impact(self, within_hours: float = 24.0) -> dict | None:
        """Soonest high-impact US event inside `within_hours`."""
        now = datetime.now(ET)
        cutoff = now + timedelta(hours=within_hours)
        for e in self.calendar:
            if e.get("impact") != "high":
                continue
            t = self._parse_event_time(e.get("time", ""))
            if t is None:
                continue
            if now <= t <= cutoff:
                return {
                    **e,
                    "_t_iso": t.isoformat(),
                    "_minutes_until": int((t - now).total_seconds() / 60),
                }
        return None

    def in_blackout_window(self) -> tuple[bool, dict | None]:
        """True if we're within ±blackout minutes of a high-impact event."""
        now = datetime.now(ET)
        for e in self.calendar:
            if e.get("impact") != "high":
                continue
            t = self._parse_event_time(e.get("time", ""))
            if t is None:
                continue
            delta_min = (t - now).total_seconds() / 60
            if -BLACKOUT_AFTER_MIN <= delta_min <= BLACKOUT_BEFORE_MIN:
                return True, {
                    **e,
                    "_t_iso": t.isoformat(),
                    "_minutes_until": int(delta_min),
                }
        return False, None

    @staticmethod
    def _parse_event_time(s: str) -> datetime | None:
        if not s:
            return None
        try:
            # Finnhub time is UTC, e.g. "2026-05-15 12:30:00"
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            return dt.astimezone(ET)
        except Exception:
            return None
