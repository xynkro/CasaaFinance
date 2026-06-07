"""
api_usage_scrape.py — pull Anthropic API costs from completed
GitHub Actions brain runs and upsert into the `api_usage` sheet.

How it works
------------
claude-code-action prints a single JSON blob at the end of each brain
run, e.g.

    {"type":"result","subtype":"success","is_error":false,
     "duration_ms":1271673,"num_turns":62,
     "total_cost_usd":5.671771,"permission_denials_count":0}

We use `gh run list` to enumerate recent runs of the brain workflows
(daily-brief, wsr-full, wsr-lite, market-scan), then `gh run view --log`
to grep the result JSON. UPSERT into the api_usage sheet keyed by
GH run_id (idempotent on re-scrape).

Usage
-----
  python scripts/api_usage_scrape.py             # scan last 50 runs across brain workflows
  python scripts/api_usage_scrape.py --limit 200 # wider sweep
  python scripts/api_usage_scrape.py --dry       # print, no sheet write

Schedule (TBD)
--------------
Designed to run as a GH Actions cron daily 23:00 UTC, AFTER all brain
runs of the day have completed. For now, run on-demand via
`casaa api-usage` until the cron is wired in a follow-up.

The Settings panel in the PWA shows MTD spend + per-workflow breakdown
+ last 10 runs. See pwa/src/cards/ApiUsageCard.tsx.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.logging_util import setup_logging  # noqa: E402

from src.sync import load_env  # noqa: E402
from src import sheets as sh   # noqa: E402
from src import schema as S    # noqa: E402

GH_REPO = "xynkro/CasaaFinance"

# Brain workflows that consume Anthropic API. Map gh workflow filename
# → friendly label for the sheet.
BRAIN_WORKFLOWS = {
    "daily-brief.yml": "daily-brief",
    "wsr-full.yml":    "wsr-full",
    "wsr-lite.yml":    "wsr-lite",
    "market-scan.yml": "market-scan",
}

# claude-code-action emits the result JSON pretty-printed across multiple
# log lines (each with a "<step>\t<runner-time>\t" prefix). We can't
# match the whole object in one regex; instead extract individual numeric
# fields once we've confirmed `"type": "result"` is present in the log.
RESULT_MARKER_RE = re.compile(r'"type":\s*"result"')
COST_RE     = re.compile(r'"total_cost_usd":\s*([0-9.]+)')
TURNS_RE    = re.compile(r'"num_turns":\s*(\d+)')
DURATION_RE = re.compile(r'"duration_ms":\s*(\d+)')
ISERR_RE    = re.compile(r'"is_error":\s*(true|false)')
SGT = timezone(timedelta(hours=8))


def _gh_json(args: list[str]) -> dict | list:
    """Run `gh ... --json ...` and parse stdout."""
    try:
        out = subprocess.run(
            ["gh", *args, "--repo", GH_REPO],
            capture_output=True, text=True, check=True, timeout=60,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"gh failed: {e.stderr[:300]}")
    return json.loads(out.stdout)


def _gh_log(run_id: str) -> str:
    """Fetch full log of a completed run (text)."""
    try:
        out = subprocess.run(
            ["gh", "run", "view", str(run_id), "--repo", GH_REPO, "--log"],
            capture_output=True, text=True, check=True, timeout=120,
        )
    except subprocess.CalledProcessError:
        return ""
    return out.stdout


def list_recent_runs(workflow_file: str, limit: int, logger: logging.Logger) -> list[dict]:
    """List recent (completed) runs of a workflow."""
    fields = "databaseId,workflowName,status,conclusion,createdAt,updatedAt"
    try:
        rows = _gh_json([
            "run", "list", "--workflow", workflow_file,
            "--limit", str(limit), "--json", fields,
        ])
    except Exception as e:
        logger.warning(f"  list runs {workflow_file} failed: {e}")
        return []
    # Only completed runs have parseable result JSON
    return [r for r in rows if r.get("status") == "completed"]


def parse_result_from_log(log_text: str) -> dict | None:
    """Extract result fields from a workflow log. JSON is multi-line in
    GH Actions log output, so we look for the marker + grep individual
    fields. Returns None if no result block is present (e.g. older runs
    pre claude-code-action, or runs that errored before brain executed)."""
    if not log_text or not RESULT_MARKER_RE.search(log_text):
        return None
    m_cost = COST_RE.search(log_text)
    m_turns = TURNS_RE.search(log_text)
    m_dur = DURATION_RE.search(log_text)
    m_err = ISERR_RE.search(log_text)
    if not m_cost:  # no cost = no result row worth saving
        return None
    return {
        "total_cost_usd": float(m_cost.group(1)),
        "num_turns": int(m_turns.group(1)) if m_turns else 0,
        "duration_ms": int(m_dur.group(1)) if m_dur else 0,
        "is_error": (m_err.group(1) == "true") if m_err else False,
    }


def scrape_runs(limit: int, logger: logging.Logger) -> list[S.ApiUsageRow]:
    """Across all brain workflows, fetch + parse each run's result JSON."""
    rows: list[S.ApiUsageRow] = []
    now_sgt = S.now_sgt_iso()
    for wf_file, wf_label in BRAIN_WORKFLOWS.items():
        logger.info(f"[{wf_label}] listing runs (limit={limit})")
        runs = list_recent_runs(wf_file, limit, logger)
        for r in runs:
            run_id = str(r.get("databaseId") or "")
            if not run_id:
                continue
            log = _gh_log(run_id)
            result = parse_result_from_log(log)
            if not result:
                # Many older runs (pre claude-code-action) won't have it.
                continue
            updated = str(r.get("updatedAt") or "")
            try:
                # Convert UTC ISO → SGT ISO suffix
                dt_utc = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                date_sgt = dt_utc.astimezone(SGT).strftime("%Y-%m-%dT%H%M%S")
            except Exception:
                date_sgt = now_sgt
            # Model isn't in the result JSON; infer from claude_args in
            # the prompt step (we always pass --model). Default to opus
            # for known brain workflows; market-scan uses opus too.
            model = "claude-opus-4-7"
            rows.append(S.ApiUsageRow(
                date=date_sgt,
                run_id=run_id,
                workflow=wf_label,
                model=model,
                status=str(r.get("conclusion") or "?"),
                num_turns=int(result.get("num_turns") or 0),
                duration_ms=int(result.get("duration_ms") or 0),
                total_cost_usd=float(result.get("total_cost_usd") or 0),
                updated_at=now_sgt,
            ))
        logger.info(f"[{wf_label}] scraped {sum(1 for r in rows if r.workflow == wf_label)} usage rows")
    return rows


def upsert_usage(client, rows: list[S.ApiUsageRow], logger: logging.Logger) -> int:
    """UPSERT keyed by run_id."""
    sh.ensure_headers(client, S.ApiUsageRow.TAB_NAME, S.ApiUsageRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.ApiUsageRow.TAB_NAME)
    existing = ws.get_all_values()
    hdr = existing[0] if existing else list(S.ApiUsageRow.HEADERS)

    new_keys = {r.run_id for r in rows}
    keep: list[list[str]] = [hdr]
    dropped = 0
    for r in existing[1:]:
        if not r:
            continue
        if r[1] in new_keys:
            dropped += 1
            continue
        keep.append(r)
    keep.extend(r.to_row() for r in rows)

    sh.upsert_tab(ws, keep)
    logger.info(f"✓ api_usage upserted: {len(rows)} (dropped {dropped} stale)")
    return len(rows)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--limit", type=int, default=50,
                   help="Per-workflow run-list cap (default 50; bump for backfills)")
    p.add_argument("--dry", action="store_true")
    args = p.parse_args()

    logger = setup_logging("api-usage-scrape")
    logger.info(f"api_usage_scrape start (limit={args.limit}, dry={args.dry})")

    load_env()
    client = sh.authenticate()

    rows = scrape_runs(args.limit, logger)
    logger.info(f"  Total usage rows scraped: {len(rows)}  "
                f"(${sum(r.total_cost_usd for r in rows):.2f} aggregate)")

    if args.dry:
        # Sort by cost desc to surface biggest spenders
        for r in sorted(rows, key=lambda x: x.total_cost_usd, reverse=True)[:15]:
            logger.info(
                f"  {r.date}  {r.workflow:12} {r.model:18} "
                f"${r.total_cost_usd:>6.4f}  turns={r.num_turns:>3}  "
                f"dur={r.duration_ms / 1000:>5.1f}s  {r.status}"
            )
        return 0

    if rows:
        upsert_usage(client, rows, logger)
    logger.info("api_usage_scrape done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
