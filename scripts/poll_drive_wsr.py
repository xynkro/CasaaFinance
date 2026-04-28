"""
poll_drive_wsr.py — Drive-folder polling replacement for the Mac
folder-watching LaunchAgent (com.caspar.wsr-archive).

Watches Drive folders:
  - Weekly Strategy Review/   (full WSR .md files you write manually)
  - WSR Lite/                 (mid-week .md you might upload mobile)

For each new file (not already in wsr_archive sheet):
  1. Download contents from Drive
  2. Parse via existing wsr_md_parser / wsr_lite_md_parser
  3. Write parsed row to wsr_summary
  4. Append a wsr_archive row pointing to the Drive file ID

Mac-independent. Runs from GitHub Actions every 30 minutes.

Usage:
  python scripts/poll_drive_wsr.py             # incremental
  python scripts/poll_drive_wsr.py --force-id <drive_file_id>  # re-process one file
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("poll-drive-wsr")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


def _list_drive_md_files(drive_svc, folder_id: str) -> list[dict]:
    """List all .md files in a Drive folder. Returns [{id, name, modifiedTime}]."""
    q = (
        f"'{folder_id}' in parents and "
        f"(name contains '.md') and trashed=false"
    )
    res = drive_svc.files().list(
        q=q, fields="files(id,name,modifiedTime)", pageSize=100
    ).execute()
    return res.get("files", [])


def _download_drive_text(drive_svc, file_id: str) -> str:
    """Download a Drive file as UTF-8 text."""
    from googleapiclient.http import MediaIoBaseDownload
    req = drive_svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue().decode("utf-8", errors="replace")


def _date_from_name(name: str) -> str:
    """Extract YYYY-MM-DD from filename like 20260424_WSR_lite.md."""
    import re
    m = re.match(r"^(\d{8})", name)
    if m:
        s = m.group(1)
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return datetime.now().strftime("%Y-%m-%d")


def process_drive_file(drive_svc, file_meta: dict, sheet_client, ss, logger: logging.Logger,
                       force: bool = False) -> bool:
    """Download + parse + push to sheets a single Drive file. Returns True if processed."""
    from src import schema as S
    from src import sheets as sh

    file_id = file_meta["id"]
    name = file_meta["name"]
    date_iso = _date_from_name(name)

    # Determine type by filename
    name_lower = name.lower()
    is_lite = "lite" in name_lower
    is_options = "options" in name_lower or "scan" in name_lower
    if is_options:
        logger.info(f"Skip options scan file (handled separately): {name}")
        return False

    # Idempotency check: is this file_id already in wsr_archive?
    if not force:
        ws_arch = ss.worksheet(S.WsrArchiveRow.TAB_NAME)
        existing_ids = set(ws_arch.col_values(3))  # drive_file_id column (1-indexed col 3)
        if file_id in existing_ids:
            logger.info(f"Skip (already archived): {name}")
            return False

    # Download
    try:
        md = _download_drive_text(drive_svc, file_id)
    except Exception as e:
        logger.error(f"Download failed for {name}: {e}")
        return False

    # Parse
    try:
        if is_lite:
            from src.wsr_lite_md_parser import parse_wsr_lite_md_text
            parsed = parse_wsr_lite_md_text(md, date_iso)
        else:
            from src.wsr_md_parser import parse_wsr_md_text
            parsed = parse_wsr_md_text(md, date_iso)
    except (ImportError, AttributeError):
        # Fallback: if no _text variants exist, write a temp file then parse
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tf:
            tf.write(md)
            tmp_path = Path(tf.name)
        try:
            if is_lite:
                from src.wsr_lite_md_parser import parse_wsr_lite_md
                parsed = parse_wsr_lite_md(tmp_path, date_iso)
            else:
                from src.wsr_md_parser import parse_wsr_md
                parsed = parse_wsr_md(tmp_path, date_iso)
        finally:
            tmp_path.unlink(missing_ok=True)

    # Write parsed row to wsr_summary (upsert by date+source)
    sh.ensure_headers(sheet_client, S.WsrSummaryRow.TAB_NAME, S.WsrSummaryRow.HEADERS)
    ws = ss.worksheet(S.WsrSummaryRow.TAB_NAME)
    existing = ws.get_all_values()
    keep_rows = [existing[0]] if existing else [S.WsrSummaryRow.HEADERS]
    src_val = parsed.get("source", "wsr_lite" if is_lite else f"{date_iso.replace('-', '')}_WSR.md")
    for r in (existing[1:] if existing else []):
        if not r:
            continue
        row_date = r[0][:10]
        row_src = r[1] if len(r) > 1 else ""
        if row_date == date_iso and row_src == src_val:
            continue  # drop the old, replace below
        keep_rows.append(r)
    new_row = S.WsrSummaryRow(**parsed).to_row()
    keep_rows.append(new_row)
    ws.clear()
    ws.update("A1", keep_rows, value_input_option="USER_ENTERED")
    logger.info(f"✓ wsr_summary updated: {name} ({src_val})")

    # Append to wsr_archive
    sh.ensure_headers(sheet_client, S.WsrArchiveRow.TAB_NAME, S.WsrArchiveRow.HEADERS)
    arch_row = S.WsrArchiveRow(
        date=date_iso,
        title=("WSR Lite" if is_lite else "WSR"),
        drive_file_id=file_id,
    )
    sh.append_row(sheet_client, S.WsrArchiveRow.TAB_NAME, arch_row.to_row())
    logger.info(f"✓ wsr_archive row added")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force-id", default=None, help="Re-process a specific Drive file ID")
    args = ap.parse_args()

    logger = _setup_logging()
    logger.info("=== poll_drive_wsr start ===")

    from src.sync import load_env
    from src import sheets as sh
    from src import drive as dr
    load_env()
    sheet_client = sh.authenticate()
    ss = sh._open_sheet(sheet_client)
    drive_svc = dr._drive_service()

    parent_id = os.environ.get("DRIVE_FOLDER_ID")
    if not parent_id:
        logger.error("DRIVE_FOLDER_ID not set")
        return 2

    # Find both folders (create if absent so first run doesn't fail)
    folders = {
        "Weekly Strategy Review": dr.get_or_create_folder("Weekly Strategy Review", parent_folder_id=parent_id),
        "WSR Lite":               dr.get_or_create_folder("WSR Lite", parent_folder_id=parent_id),
    }
    logger.info(f"Watching folders: {list(folders.keys())}")

    if args.force_id:
        meta = drive_svc.files().get(
            fileId=args.force_id, fields="id,name,modifiedTime"
        ).execute()
        ok = process_drive_file(drive_svc, meta, sheet_client, ss, logger, force=True)
        return 0 if ok else 1

    processed, skipped, failed = 0, 0, 0
    for fname, fid in folders.items():
        files = _list_drive_md_files(drive_svc, fid)
        logger.info(f"[{fname}] {len(files)} .md files")
        for f in files:
            try:
                if process_drive_file(drive_svc, f, sheet_client, ss, logger):
                    processed += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.exception(f"failed: {f.get('name')}")
                failed += 1

    logger.info(f"=== done: processed={processed} skipped={skipped} failed={failed} ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
