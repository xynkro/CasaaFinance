"""
push_brief.py — Universal "write a brief to Sheets + Drive" endpoint.

Accepts a JSON payload (via stdin or --json-file) describing a daily brief
or WSR document, writes structured fields to the appropriate Sheet tab,
and archives the raw markdown to a Drive folder. Replaces the local-file
+ LaunchAgent pipeline (no Mac filesystem dependency).

Used by:
  - CronCreate scheduled brain sessions (daily brief, WSR Lite, WSR Monday)
  - Manual ad-hoc pushes from any environment

Brief types supported:
  - daily          → daily_brief_latest sheet + Drive/Daily Briefs/
  - wsr_lite       → wsr_summary sheet (source=wsr_lite) + Drive/WSR Lite/
  - wsr_full       → wsr_summary sheet (source=YYYYMMDD_WSR.md) + Drive/Weekly Strategy Review/

JSON schema (daily):
  {
    "type":       "daily",
    "date":       "2026-04-28",
    "headline":   "one-line summary",
    "sentiment":  "bullish|bearish|neutral",
    "bullets":    ["...", "...", "..."],   # exactly 3
    "verdict":    "trader-facing one-liner",
    "overnight":  "pipe-separated bullets" or "",
    "premarket":  "...",
    "catalysts":  "...",
    "commodities":"...",
    "posture":    "...",
    "watch":      "...",
    "raw_md":     "full markdown for archive"
  }

JSON schema (wsr_lite | wsr_full):
  {
    "type":              "wsr_lite" | "wsr_full",
    "date":              "2026-04-28",
    "verdict":           "...",
    "confidence":        0.0-1.0,
    "regime":            "bull_late_cycle|...",
    "macro_read":        "...",
    "action_summary":    "...",
    "options_summary":   "...",
    "redteam_summary":   "...",
    "week_events":       "...",
    "raw_md":            "full markdown"
  }

Usage:
  cat brief.json | python scripts/push_brief.py
  python scripts/push_brief.py --json-file brief.json
  python scripts/push_brief.py --no-drive  # skip Drive upload (sheet only)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _setup_logging() -> logging.Logger:
    log_path = ROOT / ".state" / "push-brief.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("push-brief")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(log_path)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(sh)
    return logger


def _validate_payload(payload: dict, logger: logging.Logger) -> tuple[bool, str]:
    """Return (ok, error_msg). All briefs need at least type, date, raw_md."""
    btype = payload.get("type")
    if btype not in ("daily", "wsr_lite", "wsr_full"):
        return False, f"Invalid type: {btype!r}. Must be daily|wsr_lite|wsr_full"
    if not payload.get("date"):
        return False, "Missing required field: date"
    if not payload.get("raw_md"):
        return False, "Missing required field: raw_md"

    if btype == "daily":
        bullets = payload.get("bullets", [])
        if not isinstance(bullets, list) or len(bullets) < 1:
            return False, "daily brief requires bullets[] with 1-3 items"
        if not payload.get("headline"):
            return False, "daily brief requires headline"

    if btype in ("wsr_lite", "wsr_full"):
        if not payload.get("verdict"):
            return False, f"{btype} requires verdict"
        conf = payload.get("confidence")
        if conf is not None and not (0.0 <= float(conf) <= 1.0):
            return False, f"confidence must be 0.0-1.0, got {conf}"

    return True, ""


def _push_daily(payload: dict, logger: logging.Logger, no_drive: bool = False) -> dict:
    """Write a daily brief to daily_brief_latest sheet + Drive/Daily Briefs/."""
    from src.sync import load_env
    from src import sheets as sh
    from src import schema as S
    from src import drive as dr

    load_env()
    client = sh.authenticate()

    # Build the row (left-pad bullets to 3 entries to match schema)
    bullets = payload.get("bullets", []) + ["", "", ""]
    row = S.DailyBriefRow(
        date=payload["date"],
        bullet_1=bullets[0],
        bullet_2=bullets[1],
        bullet_3=bullets[2],
        verdict=payload.get("verdict", ""),
        sentiment=payload.get("sentiment", "neutral"),
        headline=payload.get("headline", ""),
        overnight=payload.get("overnight", ""),
        premarket=payload.get("premarket", ""),
        catalysts=payload.get("catalysts", ""),
        commodities=payload.get("commodities", ""),
        posture=payload.get("posture", ""),
        watch=payload.get("watch", ""),
        raw_md=payload.get("raw_md", ""),
    )
    sh.ensure_headers(client, S.DailyBriefRow.TAB_NAME, S.DailyBriefRow.HEADERS)
    sh.append_row(client, S.DailyBriefRow.TAB_NAME, row.to_row())
    logger.info(f"✓ Sheet write: daily_brief_latest @ {payload['date']}")

    drive_url = None
    drive_file_id = None
    if not no_drive:
        try:
            parent_id = os.environ.get("DRIVE_FOLDER_ID")
            briefs_folder_id = dr.get_or_create_folder("Daily Briefs", parent_folder_id=parent_id)
            iso = payload["date"].replace("-", "")  # 20260428
            file_name = f"{iso}_DailyBrief.md"
            drive_file_id = dr.upload_text(payload["raw_md"], file_name, folder_id=briefs_folder_id)
            drive_url = f"https://drive.google.com/file/d/{drive_file_id}/view"
            logger.info(f"✓ Drive write: {file_name} → {drive_file_id}")
        except Exception as e:
            logger.warning(f"⚠ Drive write failed (non-fatal): {e}")

    return {"sheet_tab": "daily_brief_latest", "drive_file_id": drive_file_id, "drive_url": drive_url}


def _push_wsr(payload: dict, logger: logging.Logger, no_drive: bool = False) -> dict:
    """Write a WSR Lite or WSR Full to wsr_summary sheet + Drive folder."""
    from src.sync import load_env
    from src import sheets as sh
    from src import schema as S
    from src import drive as dr

    load_env()
    client = sh.authenticate()

    btype = payload["type"]  # wsr_lite | wsr_full
    iso = payload["date"].replace("-", "")
    if btype == "wsr_lite":
        source = "wsr_lite"
        drive_folder_name = "WSR Lite"
        archive_name = f"{iso}_WSR_lite.md"
    else:
        source = f"{iso}_WSR.md"
        drive_folder_name = "Weekly Strategy Review"
        archive_name = f"{iso}_WSR.md"

    row = S.WsrSummaryRow(
        date=payload["date"],
        source=source,
        verdict=payload.get("verdict", ""),
        confidence=float(payload.get("confidence", 0.7)),
        regime=payload.get("regime", ""),
        macro_read=payload.get("macro_read", ""),
        action_summary=payload.get("action_summary", ""),
        options_summary=payload.get("options_summary", ""),
        redteam_summary=payload.get("redteam_summary", ""),
        week_events=payload.get("week_events", ""),
        raw_md=payload.get("raw_md", ""),
    )

    # Upsert dedup: same date + same source → replace, not duplicate
    sh.ensure_headers(client, S.WsrSummaryRow.TAB_NAME, S.WsrSummaryRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.WsrSummaryRow.TAB_NAME)
    existing = ws.get_all_values()
    keep_rows = [existing[0]] if existing else [S.WsrSummaryRow.HEADERS]
    for r in (existing[1:] if existing else []):
        if not r:
            continue
        row_date = r[0][:10]
        row_src = r[1] if len(r) > 1 else ""
        if row_date == payload["date"] and row_src == source:
            continue  # drop the old row for this date+source — replace below
        keep_rows.append(r)
    keep_rows.append(row.to_row())
    ws.clear()
    ws.update("A1", keep_rows, value_input_option="USER_ENTERED")
    logger.info(f"✓ Sheet write: wsr_summary @ {payload['date']} (source={source})")

    drive_url = None
    drive_file_id = None
    if not no_drive:
        try:
            parent_id = os.environ.get("DRIVE_FOLDER_ID")
            folder_id = dr.get_or_create_folder(drive_folder_name, parent_folder_id=parent_id)
            drive_file_id = dr.upload_text(payload["raw_md"], archive_name, folder_id=folder_id)
            drive_url = f"https://drive.google.com/file/d/{drive_file_id}/view"
            logger.info(f"✓ Drive write: {archive_name} → {drive_file_id}")

            # Also append to wsr_archive sheet so PWA Archive page sees it
            sh.ensure_headers(client, S.WsrArchiveRow.TAB_NAME, S.WsrArchiveRow.HEADERS)
            ws_arch = ss.worksheet(S.WsrArchiveRow.TAB_NAME)
            existing_ids = set(ws_arch.col_values(3))  # drive_file_id col
            if drive_file_id not in existing_ids:
                arch_row = S.WsrArchiveRow(
                    date=payload["date"],
                    title=("WSR Lite" if btype == "wsr_lite" else "WSR"),
                    drive_file_id=drive_file_id,
                )
                sh.append_row(client, S.WsrArchiveRow.TAB_NAME, arch_row.to_row())
                logger.info(f"✓ Sheet write: wsr_archive (new file)")
        except Exception as e:
            logger.warning(f"⚠ Drive/archive write failed (non-fatal): {e}")

    return {"sheet_tab": "wsr_summary", "drive_file_id": drive_file_id, "drive_url": drive_url}


def push_brief(payload: dict, no_drive: bool = False) -> dict:
    """Public API. Returns dict with {sheet_tab, drive_file_id, drive_url, ok, error}."""
    logger = _setup_logging()
    ok, err = _validate_payload(payload, logger)
    if not ok:
        logger.error(f"Validation failed: {err}")
        return {"ok": False, "error": err}

    try:
        if payload["type"] == "daily":
            result = _push_daily(payload, logger, no_drive=no_drive)
        else:
            result = _push_wsr(payload, logger, no_drive=no_drive)
        return {**result, "ok": True}
    except Exception as e:
        logger.exception("push_brief failed")
        return {"ok": False, "error": str(e)}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--json-file", type=Path, help="Path to JSON payload file. If omitted, reads stdin.")
    ap.add_argument("--no-drive", action="store_true", help="Skip Drive upload, write only to Sheets")
    args = ap.parse_args()

    if args.json_file:
        payload_text = args.json_file.read_text()
    else:
        payload_text = sys.stdin.read()

    if not payload_text.strip():
        print("ERROR: No JSON payload provided (stdin empty or file missing)", file=sys.stderr)
        return 2

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON: {e}", file=sys.stderr)
        return 2

    result = push_brief(payload, no_drive=args.no_drive)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
