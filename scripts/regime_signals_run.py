#!/usr/bin/env python3
"""
regime_signals_run.py — daily wrapper that runs the trader's regime-detection
skills and appends one row per source to the `regime_signals` Google Sheet tab.

Skills wrapped (in order):
  - market-breadth-analyzer      no API key — runs every day
  - ftd-detector                 FMP_API_KEY required (skipped gracefully if absent)
  - ibd-distribution-day-monitor FMP_API_KEY required
  - macro-regime-detector        FMP_API_KEY required
  - market-top-detector          FMP_API_KEY required + breadth args (skipped here)

Each skill is invoked as a subprocess into a tempdir, then the most-recent JSON
is parsed for a normalized (score, label, summary) tuple. The full JSON is
serialised into the `raw_json` column (truncated to 5KB).

Behavior:
  - --dry / --dry-run : print rows that would be appended; no Sheet write
  - $FMP_API_KEY absent : log a warning per skipped skill, NOT a failure
  - any individual skill failure : log + continue (don't fail the whole run)

Usage:
  python scripts/regime_signals_run.py [--dry]

Cron:
  .github/workflows/regime-signals.yml — daily 22:00 UTC (Mon-Fri, after US close)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# Project-root import shim — works whether invoked as `python scripts/...` or `python -m`.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
from src.logging_util import setup_logging  # noqa: E402

from src import schema as S          # noqa: E402
from src import sheets as sh         # noqa: E402
from src.sync import load_env        # noqa: E402


# Skill scripts live in two places. Local dev (Mac): user's installed
# `~/.claude/skills/<skill>/scripts/...`. Cloud (GitHub Actions): vendored
# copy at `vendor/skills/<skill>/scripts/...` next to this script. We resolve
# per-skill: prefer local, fall back to vendored.
_USER_SKILLS = Path.home() / ".claude" / "skills"
_VENDOR_SKILLS = _PROJECT_ROOT / "vendor" / "skills"


def _resolve_skill_script(skill_name: str, script_filename: str) -> Path:
    """Return the first existing path between user-local and vendored copy."""
    for base in (_USER_SKILLS, _VENDOR_SKILLS):
        candidate = base / skill_name / "scripts" / script_filename
        if candidate.exists():
            return candidate
    # Return user-local path so the caller's "not found" log is informative.
    return _USER_SKILLS / skill_name / "scripts" / script_filename


@dataclass
class ParsedSignal:
    """Normalized fields extracted from one skill's JSON output."""
    source: str
    score: float
    label: str
    summary: str
    raw: dict


# ---------------- per-skill JSON parsers ----------------

def parse_market_breadth(data: dict) -> ParsedSignal:
    """market-breadth-analyzer JSON -> normalized signal.

    Keys we care about: composite.composite_score, composite.zone,
    composite.guidance.
    """
    comp = data.get("composite", {}) or {}
    score = float(comp.get("composite_score", 0) or 0)
    label = str(comp.get("zone", "UNKNOWN")).strip()
    guidance = str(comp.get("guidance", "")).strip()
    exposure = str(comp.get("exposure_guidance", "")).strip()
    summary_bits = []
    if exposure:
        summary_bits.append(f"exposure {exposure}")
    if guidance:
        summary_bits.append(guidance)
    summary = " | ".join(summary_bits) or f"score {score}"
    return ParsedSignal(
        source="market_breadth", score=score, label=label,
        summary=summary, raw=data,
    )


def parse_ftd(data: dict) -> ParsedSignal:
    """ftd-detector JSON -> normalized signal.

    Key path: market_state.quality_score.{total_score, signal, guidance}.
    """
    market_state = data.get("market_state", {}) or {}
    quality = market_state.get("quality_score", {}) or {}
    score = float(quality.get("total_score", 0) or 0)
    label = str(quality.get("signal", "UNKNOWN")).strip()
    guidance = str(quality.get("guidance", "")).strip()
    exposure_range = str(quality.get("exposure_range", "")).strip()
    summary_bits = [s for s in (label, exposure_range, guidance) if s]
    summary = " | ".join(summary_bits[:3]) or f"score {score}"
    return ParsedSignal(
        source="ftd", score=score, label=label, summary=summary, raw=data,
    )


def parse_distribution_day(data: dict) -> ParsedSignal:
    """ibd-distribution-day-monitor JSON -> normalized signal.

    Key path: market_distribution_state.overall_risk_level + portfolio_action.
    Risk levels: NORMAL/CAUTION/HIGH/SEVERE — we map to a 0-100 score.
    """
    state = data.get("market_distribution_state", {}) or {}
    risk = str(state.get("overall_risk_level", "UNKNOWN")).strip().upper()
    portfolio = data.get("portfolio_action", {}) or {}
    target_exposure = portfolio.get("target_exposure_pct")
    action = str(portfolio.get("action", "")).strip()

    # Risk-level -> score (higher = healthier; matches breadth convention).
    risk_score = {
        "NORMAL": 80.0,
        "CAUTION": 50.0,
        "HIGH": 25.0,
        "SEVERE": 5.0,
    }.get(risk, 40.0)

    summary_bits = [f"risk={risk}"]
    if target_exposure is not None:
        summary_bits.append(f"target_exposure={target_exposure}%")
    if action:
        summary_bits.append(action[:120])
    return ParsedSignal(
        source="distribution_day", score=risk_score,
        label=risk, summary=" | ".join(summary_bits), raw=data,
    )


def parse_macro_regime(data: dict) -> ParsedSignal:
    """macro-regime-detector JSON -> normalized signal.

    Key paths: composite.composite_score, regime.regime_label, regime.confidence.
    """
    comp = data.get("composite", {}) or {}
    regime = data.get("regime", {}) or {}
    score = float(comp.get("composite_score", 0) or 0)
    label = str(regime.get("regime_label", "UNKNOWN")).strip()
    confidence = str(regime.get("confidence", "")).strip()
    transition = (regime.get("transition_probability") or {}).get("probability_range", "")
    summary_bits = [b for b in (label, f"confidence={confidence}",
                                f"transition={transition}") if b and "=" not in b or b.split("=", 1)[1]]
    summary = " | ".join(summary_bits) or f"score {score}"
    return ParsedSignal(
        source="macro_regime", score=score, label=label,
        summary=summary, raw=data,
    )


# ---------------- skill invocation ----------------

@dataclass
class SkillSpec:
    """Declarative spec for one skill we invoke."""
    source: str                              # value for regime_signals.source
    script_path: Path                        # path to skill's CLI script
    json_glob: str                           # output filename glob pattern
    extra_args: list[str]                    # CLI args beyond --output-dir
    parser: Callable[[dict], ParsedSignal]  # JSON-> ParsedSignal
    requires_fmp: bool                       # skip if FMP_API_KEY unset


def _run_skill(spec: SkillSpec, logger: logging.Logger) -> Optional[ParsedSignal]:
    """Execute one skill via subprocess; return ParsedSignal or None on skip/error."""
    if spec.requires_fmp and not os.environ.get("FMP_API_KEY"):
        logger.warning(f"  [{spec.source}] skipped — FMP_API_KEY not set")
        return None
    if not spec.script_path.exists():
        logger.warning(f"  [{spec.source}] skipped — script not found: {spec.script_path}")
        return None

    with tempfile.TemporaryDirectory() as tmp:
        cmd = [sys.executable, str(spec.script_path), "--output-dir", tmp, *spec.extra_args]
        logger.info(f"  [{spec.source}] running: {' '.join(cmd[-4:])}")
        try:
            r = subprocess.run(
                cmd, cwd=tmp, capture_output=True, text=True, timeout=180,
            )
        except subprocess.TimeoutExpired:
            logger.error(f"  [{spec.source}] TIMEOUT after 180s")
            return None
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or "")[-500:]
            logger.error(f"  [{spec.source}] exit={r.returncode}: {tail}")
            return None

        # Pick newest JSON matching the glob.
        json_files = sorted(Path(tmp).glob(spec.json_glob), key=lambda p: p.stat().st_mtime)
        if not json_files:
            logger.error(f"  [{spec.source}] no JSON matched {spec.json_glob}")
            return None
        try:
            data = json.loads(json_files[-1].read_text())
        except Exception as e:
            logger.error(f"  [{spec.source}] failed to parse {json_files[-1].name}: {e}")
            return None

        try:
            sig = spec.parser(data)
            logger.info(f"  [{spec.source}] OK score={sig.score:.1f} label={sig.label}")
            return sig
        except Exception as e:
            logger.error(f"  [{spec.source}] parser raised: {e}")
            return None


# ---------------- main ----------------

def build_specs() -> list[SkillSpec]:
    return [
        SkillSpec(
            source="market_breadth",
            script_path=_resolve_skill_script(
                "market-breadth-analyzer", "market_breadth_analyzer.py"
            ),
            json_glob="market_breadth_*.json",
            extra_args=[],
            parser=parse_market_breadth,
            requires_fmp=False,
        ),
        SkillSpec(
            source="ftd",
            script_path=_resolve_skill_script("ftd-detector", "ftd_detector.py"),
            json_glob="ftd_*.json",
            extra_args=[],
            parser=parse_ftd,
            requires_fmp=True,
        ),
        SkillSpec(
            source="distribution_day",
            script_path=_resolve_skill_script(
                "ibd-distribution-day-monitor", "ibd_monitor.py"
            ),
            json_glob="ibd_distribution_*.json",
            extra_args=["--symbols", "QQQ,SPY"],
            parser=parse_distribution_day,
            requires_fmp=True,
        ),
        SkillSpec(
            source="macro_regime",
            script_path=_resolve_skill_script(
                "macro-regime-detector", "macro_regime_detector.py"
            ),
            json_glob="macro_regime_*.json",
            extra_args=[],
            parser=parse_macro_regime,
            requires_fmp=True,
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry", "--dry-run", action="store_true",
                        help="parse only, print rows that would be appended; no Sheet write")
    args = parser.parse_args()

    load_env()
    logger = setup_logging("regime_signals")

    today = S.now_sgt_date()
    logger.info(f"regime_signals_run start (date={today}, dry={args.dry})")

    specs = build_specs()
    rows: list[S.RegimeSignalRow] = []

    for spec in specs:
        sig = _run_skill(spec, logger)
        if sig is None:
            continue
        row = S.RegimeSignalRow(
            date=today,
            source=sig.source,
            score=sig.score,
            label=sig.label,
            summary=sig.summary[:500],
            raw_json=json.dumps(sig.raw, default=str),
        )
        rows.append(row)

    if not rows:
        logger.warning("no regime signals produced — nothing to append")
        return 0 if args.dry else 1

    if args.dry:
        for row in rows:
            r = row.to_row()
            # Compress raw_json column for readable dry output.
            r_short = r[:5] + [f"<{len(r[5])} chars>"]
            print(f"  [dry] {r_short}")
        return 0

    try:
        client = sh.authenticate()
        sh.ensure_headers(client, S.RegimeSignalRow.TAB_NAME, S.RegimeSignalRow.HEADERS)
        n = sh.append_rows(client, S.RegimeSignalRow.TAB_NAME, [r.to_row() for r in rows])
        logger.info(f"appended {n} rows to {S.RegimeSignalRow.TAB_NAME}")
    except Exception as e:
        logger.error(f"sheets write failed: {e}")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
