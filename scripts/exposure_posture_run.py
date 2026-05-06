#!/usr/bin/env python3
"""
exposure_posture_run.py — daily wrapper that calls the exposure-coach skill
with the latest regime_signals + portfolio state, then appends one row to the
`exposure_posture` Google Sheet tab.

What it does:
  1. Read latest regime_signals rows (last 24h) for each source.
  2. Materialize them into the input-file shape exposure-coach expects (per
     source: a single JSON file with a flat `*_score` field).
  3. Read latest snapshot_caspar / snapshot_sarah for current NLV.
  4. Invoke `~/.claude/skills/exposure-coach/scripts/calculate_exposure.py`
     with the materialized JSON paths.
  5. Compute Caspar + Sarah headroom from the recommended ceiling and append
     a row to `exposure_posture`. Headroom is in the rationale text.

Headroom math:
  headroom = (exposure_ceiling_pct / 100) * net_liq - equity_value
  where equity_value = NLV - cash (positive numbers), or just NLV (worst case).

Behavior:
  - --dry / --dry-run : print the row that would be appended; no Sheet write
  - works even if NO regime_signals rows exist (exposure-coach degrades to LOW
    confidence rather than failing)
  - works without FMP_API_KEY — the breadth signal alone is enough input

Usage:
  python scripts/exposure_posture_run.py [--dry]

Cron:
  Tail-end of regime-signals.yml (after regime_signals_run.py succeeds).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

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


SKILL_PATH = _resolve_skill_script("exposure-coach", "calculate_exposure.py")


# ---------------- helpers ----------------

def setup_logger() -> logging.Logger:
    logger = logging.getLogger("exposure_posture")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


def _to_float(v: str | float | int | None, default: float = 0.0) -> float:
    if v in (None, ""):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def read_latest_regime_signals(client) -> dict[str, dict]:
    """
    Read regime_signals tab and return {source: latest_raw_json_dict} for the
    most recent observation per source within the last 7 days.
    """
    out: dict[str, dict] = {}
    try:
        ws = sh._open_sheet(client).worksheet(S.RegimeSignalRow.TAB_NAME)
        rows = ws.get_all_values()
    except Exception:
        return out

    if len(rows) < 2:
        return out

    headers = rows[0]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    by_source: dict[str, tuple[str, dict]] = {}
    for r in rows[1:]:
        if not r or not any(r):
            continue
        rec = dict(zip(headers, r))
        source = (rec.get("source") or "").strip()
        date_field = rec.get("date") or ""
        if not source or date_field[:10] < cutoff:
            continue
        # Pick newest per source by lexicographic compare (date + HHMMSS suffix).
        prev = by_source.get(source)
        if prev is None or rec["date"] > prev[0]:
            try:
                raw = json.loads(rec.get("raw_json", "") or "{}")
            except Exception:
                raw = {}
            # Inject the normalized score so flat-file parsers still work even
            # if `raw` is empty / truncated. (exposure-coach accepts either
            # nested `composite.composite_score` or flat `composite_score`.)
            score_val = _to_float(rec.get("score"))
            raw.setdefault("composite_score", score_val)
            # Source-specific shim so exposure-coach's per-skill extractor
            # finds a flat score field even when raw_json is missing.
            if source == "market_breadth":
                raw.setdefault("breadth_score", int(score_val))
            elif source == "ftd":
                raw.setdefault("ftd_score", int(score_val))
            elif source == "macro_regime":
                raw.setdefault("regime_score", int(score_val))
            elif source == "distribution_day":
                # exposure-coach has no top_risk equivalent for distribution_day
                # — pass through as top_risk so HIGH risk reduces the ceiling.
                raw.setdefault("top_risk_score", int(score_val))
            by_source[source] = (rec["date"], raw)

    for source, (_, raw) in by_source.items():
        out[source] = raw
    return out


def read_latest_snapshot(client, tab_name: str) -> dict:
    """Read latest row from a snapshot tab; return {} if absent."""
    try:
        ws = sh._open_sheet(client).worksheet(tab_name)
        rows = ws.get_all_values()
    except Exception:
        return {}
    if len(rows) < 2:
        return {}
    headers = rows[0]
    # Sort rows by `date` and take last.
    data = [dict(zip(headers, r)) for r in rows[1:] if r and any(r)]
    if not data:
        return {}
    data.sort(key=lambda r: r.get("date", ""))
    return data[-1]


def write_signal_files(signals: dict[str, dict], tmp: Path) -> dict[str, Path]:
    """Materialize {source: raw_dict} as JSON files in tmp/. Returns {source: path}."""
    paths: dict[str, Path] = {}
    for source, raw in signals.items():
        # Map our `source` value to exposure-coach's CLI flag name.
        flag_source = {
            "market_breadth": "breadth",
            "ftd": "ftd",
            "macro_regime": "regime",
            "distribution_day": "top_risk",  # we treat dist-day as top-risk proxy
            "market_top": "top_risk",
        }.get(source)
        if flag_source is None:
            continue
        # Don't double-write top_risk if both distribution_day and market_top exist.
        if flag_source in paths and source != "market_top":
            continue
        p = tmp / f"{flag_source}.json"
        p.write_text(json.dumps(raw, default=str))
        paths[flag_source] = p
    return paths


def invoke_exposure_coach(
    signal_paths: dict[str, Path],
    out_dir: Path,
    logger: logging.Logger,
) -> Optional[dict]:
    """Run calculate_exposure.py and return parsed JSON or None on failure."""
    if not SKILL_PATH.exists():
        logger.error(f"exposure-coach script not found: {SKILL_PATH}")
        return None

    cmd = [sys.executable, str(SKILL_PATH), "--output-dir", str(out_dir), "--json-only"]
    for flag, path in signal_paths.items():
        cmd.extend([f"--{flag.replace('_', '-')}", str(path)])

    logger.info(f"  exposure-coach: invoking with {len(signal_paths)} input(s)")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        logger.error("exposure-coach TIMEOUT after 60s")
        return None
    if r.returncode != 0:
        logger.error(f"exposure-coach exit={r.returncode}: {(r.stderr or r.stdout)[-500:]}")
        return None

    json_files = sorted(out_dir.glob("exposure_posture_*.json"),
                        key=lambda p: p.stat().st_mtime)
    if not json_files:
        logger.error("exposure-coach produced no JSON")
        return None

    return json.loads(json_files[-1].read_text())


def compute_headroom_text(
    ceiling_pct: float,
    snapshot_caspar: dict,
    snapshot_sarah: dict,
) -> str:
    """
    Translate the ceiling_pct into concrete USD/SGD headroom for each account.
    Equity-exposure = NLV - cash (positive). Headroom = ceiling*NLV - equity.
    Negative headroom = currently OVER ceiling.
    """
    bits = []
    # Caspar (USD)
    nlv_c = _to_float(snapshot_caspar.get("net_liq_usd"))
    cash_c = _to_float(snapshot_caspar.get("cash"))
    if nlv_c > 0:
        eq_c = max(0.0, nlv_c - cash_c)
        target_c = (ceiling_pct / 100.0) * nlv_c
        headroom_c = target_c - eq_c
        verb = "headroom" if headroom_c >= 0 else "OVER ceiling"
        bits.append(
            f"Caspar NLV ${nlv_c:,.0f} | equity ${eq_c:,.0f} | target ${target_c:,.0f} "
            f"| {verb} ${abs(headroom_c):,.0f}"
        )

    # Sarah (SGD)
    nlv_s = _to_float(snapshot_sarah.get("net_liq_sgd"))
    cash_s = _to_float(snapshot_sarah.get("cash_sgd"))
    if nlv_s > 0:
        eq_s = max(0.0, nlv_s - cash_s)
        target_s = (ceiling_pct / 100.0) * nlv_s
        headroom_s = target_s - eq_s
        verb = "headroom" if headroom_s >= 0 else "OVER ceiling"
        bits.append(
            f"Sarah NLV S${nlv_s:,.0f} | equity S${eq_s:,.0f} | target S${target_s:,.0f} "
            f"| {verb} S${abs(headroom_s):,.0f}"
        )

    return " || ".join(bits) if bits else ""


# ---------------- main ----------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry", "--dry-run", action="store_true",
                        help="parse only, print row that would be appended; no Sheet write")
    args = parser.parse_args()

    load_env()
    logger = setup_logger()

    today = S.now_sgt_date()
    logger.info(f"exposure_posture_run start (date={today}, dry={args.dry})")

    # Read latest signals + snapshots from Sheet (auth either way — needed for
    # both --dry and live runs since we need the regime context for accuracy).
    try:
        client = sh.authenticate()
    except Exception as e:
        logger.error(f"sheets auth failed: {e}")
        return 2

    signals = read_latest_regime_signals(client)
    logger.info(f"  found {len(signals)} regime signal(s): {sorted(signals.keys())}")
    snap_c = read_latest_snapshot(client, S.SnapshotCaspar.TAB_NAME)
    snap_s = read_latest_snapshot(client, S.SnapshotSarah.TAB_NAME)
    logger.info(
        f"  caspar NLV={snap_c.get('net_liq_usd', 'n/a')} "
        f"sarah NLV={snap_s.get('net_liq_sgd', 'n/a')}"
    )

    # Materialize signal files + invoke exposure-coach.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        signal_paths = write_signal_files(signals, tmp_path)
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        result = invoke_exposure_coach(signal_paths, out_dir, logger)

    if result is None:
        logger.error("exposure-coach failed; aborting")
        return 1

    ceiling = float(result.get("exposure_ceiling_pct", 0) or 0)
    bias = str(result.get("bias", "NEUTRAL")).strip()
    participation = str(result.get("participation", "NARROW")).strip()
    recommendation = str(result.get("recommendation", "REDUCE_ONLY")).strip()
    confidence = str(result.get("confidence", "LOW")).strip()
    base_rationale = str(result.get("rationale", "")).strip()

    headroom = compute_headroom_text(ceiling, snap_c, snap_s)
    rationale = base_rationale
    if headroom:
        rationale = (rationale + " HEADROOM: " + headroom).strip()

    components = result.get("component_scores", {}) or {}
    components_json = json.dumps({
        "component_scores": components,
        "inputs_provided": result.get("inputs_provided", []),
        "inputs_missing": result.get("inputs_missing", []),
        "composite_score": result.get("composite_score"),
    }, default=str)

    row = S.ExposurePostureRow(
        date=today,
        exposure_ceiling_pct=ceiling,
        bias=bias,
        participation=participation,
        recommendation=recommendation,
        confidence=confidence,
        rationale=rationale[:2000],  # sheet cell sanity cap
        components_json=components_json,
    )

    logger.info(
        f"  posture: ceiling={ceiling}% rec={recommendation} bias={bias} "
        f"part={participation} conf={confidence}"
    )

    if args.dry:
        out = row.to_row()
        # Trim components_json column for readable dry output.
        out_short = out[:7] + [f"<{len(out[7])} chars>"]
        print(f"  [dry] {out_short}")
        print(f"  [dry] rationale: {row.rationale}")
        return 0

    try:
        sh.ensure_headers(client, S.ExposurePostureRow.TAB_NAME, S.ExposurePostureRow.HEADERS)
        sh.append_row(client, S.ExposurePostureRow.TAB_NAME, row.to_row())
        logger.info(f"appended 1 row to {S.ExposurePostureRow.TAB_NAME}")
    except Exception as e:
        logger.error(f"sheets write failed: {e}")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
