"""
llm_brain.py — Anthropic SDK wrapper that orchestrates the cost-optimised
Opus 4.7 synthesis + Sonnet 4.6 formatting pipeline.

Used by the GitHub Actions brief generators (scripts/generate_*_brief.py).

Cost split (rates as of Apr 2026, may shift):
  Opus 4.7  → $15/M input, $75/M output  → THINKING (synthesis JSON)
  Sonnet 4.6 → $3/M input, $15/M output  → WRITING  (markdown expansion)

Usage:
    from src.llm_brain import synthesize, format_markdown

    synthesis = synthesize(
        system="You are the trading brain...",
        user_prompt="Today's data:\n" + data_dump,
        model="opus",
        max_tokens=2048,
    )

    markdown = format_markdown(
        template_path="prompts/sonnet_format_daily.md",
        synthesis_json=synthesis,
    )
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOGGER = logging.getLogger("llm-brain")

# Model aliases — central place to bump versions
MODEL_OPUS   = os.environ.get("MODEL_OPUS",   "claude-opus-4-7")
MODEL_SONNET = os.environ.get("MODEL_SONNET", "claude-sonnet-4-6")
MODEL_HAIKU  = os.environ.get("MODEL_HAIKU",  "claude-haiku-4-5")


def _client():
    """Lazy-import the Anthropic SDK so non-LLM scripts don't pay the cost."""
    from anthropic import Anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Required for brief generation. "
            "Add as GitHub Secret for CI runs."
        )
    return Anthropic(api_key=api_key)


def _resolve_model(alias: str) -> str:
    """opus|sonnet|haiku → real model id."""
    return {"opus": MODEL_OPUS, "sonnet": MODEL_SONNET, "haiku": MODEL_HAIKU}.get(alias, alias)


def synthesize(
    system: str,
    user_prompt: str,
    model: str = "opus",
    max_tokens: int = 2048,
    temperature: float = 0.5,
    expect_json: bool = True,
) -> dict | str:
    """
    Run the THINKING step. Default Opus 4.7. Returns parsed JSON if `expect_json`,
    otherwise raw text. The prompt should explicitly ask for JSON in a fenced block
    when expect_json=True.

    Cost budget: keep `max_tokens` tight (~2048). Synthesis should be COMPRESSED.
    """
    client = _client()
    model_id = _resolve_model(model)
    LOGGER.info(f"synthesize() → {model_id} (max_tokens={max_tokens})")

    resp = client.messages.create(
        model=model_id,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = resp.content[0].text if resp.content else ""
    LOGGER.info(
        f"synthesis usage: in={resp.usage.input_tokens} out={resp.usage.output_tokens} "
        f"stop_reason={resp.stop_reason}"
    )

    if not expect_json:
        return text

    # Extract JSON from response (may be in fenced block or naked)
    json_text = _extract_json(text)
    if not json_text:
        raise ValueError(f"synthesize() expected JSON but got:\n{text[:500]}")
    try:
        return json.loads(json_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"synthesize() returned invalid JSON: {e}\n{json_text[:500]}")


def format_markdown(
    template_path: str | Path,
    synthesis_json: dict | str,
    model: str = "sonnet",
    max_tokens: int = 8192,
    temperature: float = 0.3,
) -> str:
    """
    Run the WRITING step. Default Sonnet 4.6 (cheaper than Opus, better prose
    than Haiku). Reads a template from disk, appends the JSON, calls the model,
    returns the markdown.
    """
    template = Path(template_path)
    if not template.is_absolute():
        template = ROOT / template
    if not template.exists():
        raise FileNotFoundError(f"Template not found: {template}")
    template_text = template.read_text()

    if isinstance(synthesis_json, dict):
        synthesis_text = json.dumps(synthesis_json, indent=2, ensure_ascii=False)
    else:
        synthesis_text = synthesis_json

    user_prompt = f"{template_text}\n\n```json\n{synthesis_text}\n```"

    client = _client()
    model_id = _resolve_model(model)
    LOGGER.info(f"format_markdown() → {model_id} (max_tokens={max_tokens})")

    resp = client.messages.create(
        model=model_id,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = resp.content[0].text if resp.content else ""
    LOGGER.info(
        f"format usage: in={resp.usage.input_tokens} out={resp.usage.output_tokens} "
        f"stop_reason={resp.stop_reason}"
    )

    # Strip any wrapping code fences if Sonnet added them despite instructions
    text = _strip_outer_fences(text)
    return text.strip()


def _extract_json(text: str) -> str:
    """Find a JSON object in the response — fenced ```json blocks first, then bare {…}."""
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, flags=re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    # Find first balanced { … } — naive but works for our flat schemas
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return ""


def _strip_outer_fences(text: str) -> str:
    """Remove a single outer ```...``` if Sonnet wrapped the markdown despite being told not to."""
    m = re.match(r"^\s*```(?:markdown|md)?\s*\n(.*)\n```\s*$", text, flags=re.DOTALL)
    return m.group(1) if m else text


# ── Public token-usage tracking helper for cost auditing ──────────────────────

class CostTracker:
    """Accumulate input/output tokens across a run; print summary at end."""

    PRICES_PER_M = {  # USD per 1M tokens
        "opus":   {"in": 15.0, "out": 75.0},
        "sonnet": {"in":  3.0, "out": 15.0},
        "haiku":  {"in":  0.80, "out": 4.0},
    }

    def __init__(self) -> None:
        self.records: list[tuple[str, int, int]] = []

    def add(self, model_alias: str, input_tokens: int, output_tokens: int) -> None:
        self.records.append((model_alias, input_tokens, output_tokens))

    def summary(self) -> dict:
        total_cost = 0.0
        per_model: dict[str, dict[str, float]] = {}
        for alias, ti, to in self.records:
            p = self.PRICES_PER_M.get(alias, {"in": 0, "out": 0})
            cost = (ti * p["in"] + to * p["out"]) / 1_000_000
            total_cost += cost
            slot = per_model.setdefault(alias, {"input": 0, "output": 0, "cost": 0})
            slot["input"]  += ti
            slot["output"] += to
            slot["cost"]   += cost
        return {"total_cost_usd": round(total_cost, 4), "per_model": per_model}
