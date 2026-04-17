"""
archive_wsr_folder.py — Watch the Weekly Strategy Review folder and auto-archive
any new/updated .md or .pdf file to Google Drive + the wsr_archive sheet tab
(which the PWA Archive page renders).

By default this script is *incremental*:
  - walks ~/Documents/Trading/Weekly Strategy Review/
  - for each .md/.pdf whose Drive-upload sidecar is missing or stale, uploads
    to Drive, writes/updates a wsr_archive row, and writes a tiny
    `.archive.json` sidecar with the file's mtime + Drive file_id so we don't
    re-upload on every LaunchAgent fire.

Usage:
  python scripts/archive_wsr_folder.py          # pick up new/stale only
  python scripts/archive_wsr_folder.py --all    # force re-archive everything
  python scripts/archive_wsr_folder.py --file 20260417_adhoc_options_scan.md

Invoked automatically by the com.caspar.wsr-archive LaunchAgent on folder change.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WSR_DIR = Path.home() / "Documents" / "Trading" / "Weekly Strategy Review"

# Regex to extract date from filename: 20260417_name.md
DATE_RE = re.compile(r"^(\d{8})[_-]")


def setup_logging() -> logging.Logger:
    log_path = ROOT / ".state" / "wsr-archive.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("wsr-archive")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.FileHandler(log_path)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
        # Also echo to stderr for LaunchAgent log capture
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(sh)
    return logger


def parse_date_from_name(name: str) -> str:
    """Extract YYYY-MM-DD from filename like 20260417_*.md, fall back to today."""
    m = DATE_RE.match(name)
    if m:
        s = m.group(1)
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return datetime.now().strftime("%Y-%m-%d")


def sidecar_path(source: Path) -> Path:
    return source.with_suffix(source.suffix + ".archive.json")


def needs_archiving(source: Path) -> bool:
    """True if source is newer than sidecar (or sidecar missing)."""
    s = sidecar_path(source)
    if not s.exists():
        return True
    try:
        return source.stat().st_mtime > s.stat().st_mtime
    except OSError:
        return True


def archive_file(source: Path, logger: logging.Logger, force: bool = False) -> bool:
    """Upload source to Drive + write/update wsr_archive row. Returns True on success."""
    if not force and not needs_archiving(source):
        logger.info(f"Skip (up-to-date): {source.name}")
        return True

    # Lazy imports — only load heavy deps when actually archiving
    from src.sync import load_env
    from src import drive as dr
    from src import sheets as sh
    from src import schema as S

    load_env()

    date = parse_date_from_name(source.name)
    # Human-friendly title from filename: "20260417_adhoc_options_scan" -> "Adhoc Options Scan"
    raw = source.stem
    if DATE_RE.match(raw):
        raw = DATE_RE.sub("", raw)
    title = raw.replace("_", " ").replace("-", " ").strip().title()

    # Upload to Drive
    try:
        file_id = dr.upload_file(source)
        logger.info(f"Drive upload OK: {source.name} -> {file_id}")
    except Exception as e:
        logger.error(f"Drive upload failed for {source.name}: {e}")
        return False

    # Check if an archive row with this drive_file_id already exists
    try:
        client = sh.authenticate()
        sh.ensure_headers(client, S.WsrArchiveRow.TAB_NAME, S.WsrArchiveRow.HEADERS)
        ss = sh._open_sheet(client)
        ws = ss.worksheet(S.WsrArchiveRow.TAB_NAME)
        existing_ids = set()
        try:
            # Get all drive_file_id values (col 3, 1-indexed)
            existing_ids = set(ws.col_values(3))
        except Exception:
            pass

        if file_id not in existing_ids:
            row = S.WsrArchiveRow(
                date=date, title=title, drive_file_id=file_id,
            )
            sh.append_row(client, S.WsrArchiveRow.TAB_NAME, row.to_row())
            logger.info(f"Archive row written: {title} ({date})")
        else:
            logger.info(f"Archive row already exists for {file_id}, skipping sheet write")
    except Exception as e:
        logger.error(f"Sheet write failed for {source.name}: {e}")
        return False

    # Write sidecar so next run skips this file
    sidecar = sidecar_path(source)
    sidecar.write_text(json.dumps({
        "drive_file_id": file_id,
        "archived_at": datetime.now().isoformat(),
        "title": title,
        "date": date,
    }, indent=2))
    return True


def walk_and_archive(force: bool, specific_file: str | None, logger: logging.Logger) -> int:
    if not WSR_DIR.exists():
        logger.error(f"WSR dir missing: {WSR_DIR}")
        return 2

    if specific_file:
        target = WSR_DIR / specific_file
        if not target.exists():
            logger.error(f"File not found: {target}")
            return 1
        return 0 if archive_file(target, logger, force=True) else 1

    processed = 0
    failed = 0
    for p in sorted(WSR_DIR.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".md", ".pdf"):
            continue
        if p.name.startswith("."):
            continue
        try:
            if archive_file(p, logger, force=force):
                processed += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Unhandled error on {p.name}: {e}")
            failed += 1

    logger.info(f"Done. processed={processed} failed={failed}")
    return 0 if failed == 0 else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="Force re-archive every file")
    ap.add_argument("--file", type=str, help="Archive just this file (by basename)")
    args = ap.parse_args()

    logger = setup_logging()
    return walk_and_archive(args.all, args.file, logger)


if __name__ == "__main__":
    sys.exit(main())
