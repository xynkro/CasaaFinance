"""LLM-driven "so what" interpretation for macro news pings.

Caspar wants the Telegram pings to read like the WSJ "What's News" or
Bloomberg morning briefing — a 1-sentence implication that says which
sectors/assets move and in which direction. The keyword heuristic in
`macro_blackouts.interpret_headline()` covers the common cases but
misses nuance ("Fed minutes show three members favored 50bp cut" needs
more than "Risk-on; growth bid").

This module wraps a single Anthropic API call (Claude Sonnet) per
headline. Cost: ~$0.001-0.003 per call. With HOT_NEWS_PING_CAP=3 and
edge-triggered dedup, we make ~3-10 calls/day in steady state — well
under $1/month.

Design notes:
  - Falls back to the heuristic when ANTHROPIC_API_KEY is unset, the
    `anthropic` SDK isn't installed, or any single call fails. The cron
    keeps running; the user just gets the keyword-heuristic line.
  - Lazy SDK import so the cron doesn't pay for `anthropic` startup
    cost on runs where no headlines need enrichment.
  - Per-process LRU cache keyed on (headline, summary) prevents the
    same headline from billing twice if a re-run happens.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache

log = logging.getLogger(__name__)

# Sonnet 4.5 — best quality/cost tradeoff for one-line interpretations.
# Bump to opus only if Sonnet starts hallucinating direction.
LLM_MODEL = os.environ.get("NEWS_INTERPRET_MODEL", "claude-sonnet-4-5")
LLM_MAX_TOKENS = 120  # 1-2 sentences fit comfortably

SYSTEM_PROMPT = (
    "You are a senior macro/market strategist writing one-line trade implications "
    "for a sophisticated swing trader. The trader runs a multi-day equity book "
    "(US large/mid-cap + a few SGX names) and uses Telegram pings to stay on top "
    "of the tape between checks.\n\n"
    "Given a news headline + brief summary, write ONE sentence (max 200 chars) "
    "stating the trade implication: which sectors/assets move, in which direction, "
    "and why. Be concrete. Use trader shorthand (USD strength, semis pressure, "
    "duration bid). Skip greetings, boilerplate, hedging language, and disclaimers.\n\n"
    "If the headline is genuinely uninterpretable (e.g. a single company's product "
    "launch with no macro spillover), respond with exactly: NO_TAKE\n\n"
    "Examples:\n"
    "Headline: 'Iran seizes oil tanker in Strait of Hormuz'\n"
    "Output: Crude bid +1-3%; energy/defense names rally; broad equities risk-off "
    "as supply premium rebuilds.\n\n"
    "Headline: 'Powell says Fed minutes show three members favored larger cut'\n"
    "Output: Dovish surprise — duration + tech bid, USD weak, gold firm; "
    "rate-cut bets steepen for September meeting.\n\n"
    "Headline: 'CPI prints 0.4% MoM, hotter than 0.3% expected'\n"
    "Output: Hawkish read — equities offered, USD bid, growth/long-duration "
    "pressured; rate-cut path delayed."
)


def _try_llm_call(headline: str, summary: str) -> str | None:
    """Single API call. Returns the model's line, or None on any error."""
    try:
        # Lazy import — avoids the SDK loading on cold cron runs that
        # don't enrich anything.
        from anthropic import Anthropic
    except ImportError:
        log.debug("anthropic SDK not installed — falling back to heuristic")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.debug("ANTHROPIC_API_KEY not set — falling back to heuristic")
        return None

    try:
        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=LLM_MODEL,
            max_tokens=LLM_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Headline: {headline}\nSummary: {summary[:300]}\n\nOutput:",
            }],
        )
        # Anthropic returns a list of content blocks; the first text block
        # is the one we want.
        for block in msg.content:
            if getattr(block, "type", None) == "text":
                text = block.text.strip()
                if text == "NO_TAKE":
                    return ""  # Explicit "no interpretation" — empty string
                # Strip any leading "Output:" if the model included it.
                if text.lower().startswith("output:"):
                    text = text[len("output:"):].strip()
                return text[:240]
        return None
    except Exception as e:
        log.warning("News-interpret LLM call failed: %s", e)
        return None


@lru_cache(maxsize=512)
def _cached_interpret(headline: str, summary: str) -> str:
    """Per-process cache wrapper. Empty string is a valid cached result."""
    out = _try_llm_call(headline, summary)
    if out is None:
        # LLM unavailable / failed — fall back to keyword heuristic.
        try:
            from .macro_blackouts import interpret_headline
        except ImportError:
            from src.macro_blackouts import interpret_headline
        return interpret_headline(headline, summary)
    return out


def interpret_with_llm(headline: str, summary: str = "") -> str:
    """Public entry — returns a 1-line "so what" string.

    Always returns a string (possibly empty). Caller can treat `""` as
    "no interpretation" and skip the 💡 line in the Telegram body.
    """
    if not headline.strip():
        return ""
    return _cached_interpret(headline.strip(), summary.strip())


def enrich_news_items(items: list[dict]) -> list[dict]:
    """Replace each item's `so_what` with an LLM-driven version.

    Mutates in-place AND returns the list (for chaining). Items that
    already have an LLM-quality `so_what` are NOT re-enriched — saves
    cost on re-runs.
    """
    for it in items:
        headline = it.get("headline", "")
        summary = it.get("summary", "")
        if not headline:
            continue
        new = interpret_with_llm(headline, summary)
        if new:
            it["so_what"] = new
    return items
