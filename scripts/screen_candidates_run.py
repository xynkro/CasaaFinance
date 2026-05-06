#!/usr/bin/env python3
"""
screen_candidates_run.py — weekly wrapper that runs vcp-screener and
canslim-screener and writes top-10 from each into the `screen_candidates`
Google Sheet tab. Sunday before WSR Full so the brain has fresh names.

Skipped silently (logged warning, exit 0) if FMP_API_KEY is not set — both
screeners require FMP for fundamentals + price history.

Behavior:
  - --dry / --dry-run : print rows that would be appended; no Sheet write
  - any individual screener failure : log + continue (other screener may run)
  - $FMP_API_KEY absent : log + exit 0 (gracefully skipped)

Usage:
  python scripts/screen_candidates_run.py [--dry]

Cron:
  .github/workflows/screen-candidates.yml — Sunday 11:00 UTC
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

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src import schema as S          # noqa: E402
from src import sheets as sh         # noqa: E402
from src.sync import load_env        # noqa: E402


# Skill scripts: prefer user-local `~/.claude/skills/...`, fall back to
# vendored `vendor/skills/...` copy in the repo (used by cloud GH Actions).
_USER_SKILLS = Path.home() / ".claude" / "skills"
_VENDOR_SKILLS = _PROJECT_ROOT / "vendor" / "skills"


def _resolve_skill_script(skill_name: str, script_filename: str) -> Path:
    for base in (_USER_SKILLS, _VENDOR_SKILLS):
        candidate = base / skill_name / "scripts" / script_filename
        if candidate.exists():
            return candidate
    return _USER_SKILLS / skill_name / "scripts" / script_filename


TOP_N = 10


# ---------------- per-screener result extractors ----------------

def extract_vcp(data: dict) -> list[S.ScreenCandidateRow]:
    """vcp-screener JSON -> top-N rows. Schema: {results: [{...}, ...]}."""
    rows: list[S.ScreenCandidateRow] = []
    today = S.now_sgt_date()
    for stock in (data.get("results") or [])[:TOP_N]:
        sym = str(stock.get("symbol", "")).strip()
        if not sym:
            continue
        sector = str(stock.get("sector", "Unknown") or "Unknown").strip()
        score = float(stock.get("composite_score", 0) or 0)
        # Trigger = pivot price (breakout level). Stop = last contraction low.
        trigger = float(
            (stock.get("vcp_pattern") or {}).get("pivot_price") or 0
        )
        stop = float(
            (stock.get("pivot_proximity") or {}).get("stop_loss_price") or 0
        )
        rating = str(stock.get("rating", "") or "").strip()
        state = str(stock.get("execution_state", "") or "").strip()
        guidance = str(stock.get("guidance", "") or "").strip()
        rationale_bits = []
        if rating:
            rationale_bits.append(f"rating={rating}")
        if state:
            rationale_bits.append(f"state={state}")
        if guidance:
            rationale_bits.append(guidance[:150])
        rationale = " | ".join(rationale_bits) or "VCP candidate"
        rows.append(S.ScreenCandidateRow(
            date=today, source="vcp", ticker=sym, sector=sector,
            score=score, trigger_price=trigger, stop_price=stop,
            rationale=rationale[:500],
        ))
    return rows


def extract_canslim(data: dict) -> list[S.ScreenCandidateRow]:
    """canslim-screener JSON -> top-N rows. CANSLIM has no entry pivot field."""
    rows: list[S.ScreenCandidateRow] = []
    today = S.now_sgt_date()
    for stock in (data.get("results") or [])[:TOP_N]:
        sym = str(stock.get("symbol", "")).strip()
        if not sym:
            continue
        sector = str(stock.get("sector", "Unknown") or "Unknown").strip()
        score = float(stock.get("composite_score", 0) or 0)
        rating = str(stock.get("rating", "") or "").strip()
        guidance = str(stock.get("guidance", "") or "").strip()
        weakest = str(stock.get("weakest_component", "") or "").strip()
        rationale_bits = []
        if rating:
            rationale_bits.append(f"rating={rating}")
        if weakest:
            rationale_bits.append(f"weakest={weakest}")
        if guidance:
            rationale_bits.append(guidance[:150])
        rationale = " | ".join(rationale_bits) or "CANSLIM candidate"
        rows.append(S.ScreenCandidateRow(
            date=today, source="canslim", ticker=sym, sector=sector,
            score=score, trigger_price=0.0, stop_price=0.0,
            rationale=rationale[:500],
        ))
    return rows


# ---------------- screener spec + invoker ----------------

@dataclass
class ScreenerSpec:
    source: str                              # "vcp" | "canslim"
    script_path: Path
    json_glob: str
    extra_args: list[str]
    extractor: Callable[[dict], list[S.ScreenCandidateRow]]


def _run_screener(spec: ScreenerSpec, logger: logging.Logger) -> list[S.ScreenCandidateRow]:
    """Run one screener, return list of candidate rows. [] on error."""
    if not spec.script_path.exists():
        logger.warning(f"  [{spec.source}] skipped — script not found: {spec.script_path}")
        return []

    with tempfile.TemporaryDirectory() as tmp:
        cmd = [sys.executable, str(spec.script_path), "--output-dir", tmp, *spec.extra_args]
        logger.info(f"  [{spec.source}] running: {' '.join(cmd[-4:])}")
        try:
            r = subprocess.run(
                cmd, cwd=tmp, capture_output=True, text=True, timeout=900,
            )
        except subprocess.TimeoutExpired:
            logger.error(f"  [{spec.source}] TIMEOUT after 900s")
            return []
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or "")[-500:]
            logger.error(f"  [{spec.source}] exit={r.returncode}: {tail}")
            return []

        json_files = sorted(Path(tmp).glob(spec.json_glob), key=lambda p: p.stat().st_mtime)
        if not json_files:
            logger.error(f"  [{spec.source}] no JSON matched {spec.json_glob}")
            return []
        try:
            data = json.loads(json_files[-1].read_text())
        except Exception as e:
            logger.error(f"  [{spec.source}] failed to parse {json_files[-1].name}: {e}")
            return []

        try:
            rows = spec.extractor(data)
            logger.info(f"  [{spec.source}] OK -> {len(rows)} rows")
            return rows
        except Exception as e:
            logger.error(f"  [{spec.source}] extractor raised: {e}")
            return []


def build_specs() -> list[ScreenerSpec]:
    return [
        ScreenerSpec(
            source="vcp",
            script_path=_resolve_skill_script("vcp-screener", "screen_vcp.py"),
            json_glob="vcp_screener_*.json",
            extra_args=["--top", str(TOP_N), "--max-candidates", "100"],
            extractor=extract_vcp,
        ),
        ScreenerSpec(
            source="canslim",
            script_path=_resolve_skill_script("canslim-screener", "screen_canslim.py"),
            json_glob="canslim_*.json",
            extra_args=["--top", str(TOP_N), "--max-candidates", "35"],  # 35 = free-tier safe
            extractor=extract_canslim,
        ),
    ]


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("screen_candidates")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


# ---------------- main ----------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry", "--dry-run", action="store_true",
                        help="parse only, print rows that would be appended; no Sheet write")
    args = parser.parse_args()

    load_env()
    logger = setup_logger()

    if not os.environ.get("FMP_API_KEY"):
        logger.warning("FMP_API_KEY not set — both screeners require it; exiting cleanly")
        return 0

    today = S.now_sgt_date()
    logger.info(f"screen_candidates_run start (date={today}, dry={args.dry})")

    all_rows: list[S.ScreenCandidateRow] = []
    for spec in build_specs():
        all_rows.extend(_run_screener(spec, logger))

    if not all_rows:
        logger.warning("no candidates produced — nothing to append")
        return 0

    if args.dry:
        for row in all_rows:
            print(f"  [dry] {row.to_row()}")
        return 0

    try:
        client = sh.authenticate()
        sh.ensure_headers(client, S.ScreenCandidateRow.TAB_NAME, S.ScreenCandidateRow.HEADERS)
        n = sh.append_rows(client, S.ScreenCandidateRow.TAB_NAME,
                           [r.to_row() for r in all_rows])
        logger.info(f"appended {n} rows to {S.ScreenCandidateRow.TAB_NAME}")
    except Exception as e:
        logger.error(f"sheets write failed: {e}")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
