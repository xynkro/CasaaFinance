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

# Keywords for hot-topic news that could move markets sharply. Preserved
# verbatim from ZeroDTE so cross-project hot-news classification agrees.
HOT_KEYWORDS = [
    "fed", "fomc", "powell", "rate cut", "rate hike", "inflation",
    "cpi", "ppi", "jobs", "payroll", "unemployment", "gdp",
    "war", "strike", "missile", "attack", "iran", "russia", "ukraine", "china",
    "tariff", "trump", "biden", "election", "shutdown",
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

    def _refresh_news(self, api_key: str, timeout: float) -> None:
        try:
            r = requests.get(
                f"{FINNHUB_BASE}/news",
                params={"category": "general", "token": api_key},
                timeout=timeout,
            )
            r.raise_for_status()
            raw = r.json()
        except Exception as e:
            log.warning("MacroFeed news fetch failed: %s", e)
            return

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        out: list[dict] = []
        for n in raw:
            ts = datetime.fromtimestamp(n.get("datetime", 0), tz=timezone.utc)
            if ts < cutoff:
                continue
            out.append({
                "id": n.get("id"),
                "datetime": ts.isoformat(),
                "headline": n.get("headline", ""),
                "summary": (n.get("summary") or "")[:200],
                "source": n.get("source", ""),
                "url": n.get("url", ""),
                "hot": is_hot_news(n.get("headline", ""), n.get("summary", "")),
            })
        out.sort(key=lambda x: x["datetime"], reverse=True)
        self.news = out[:30]
        log.info("MacroFeed news: %d items (%d hot)", len(out), sum(1 for x in out if x["hot"]))

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
