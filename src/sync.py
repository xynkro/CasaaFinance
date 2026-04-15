#!/usr/bin/env python3
"""
sync.py — standalone CLI that pushes Daily / WSR outputs to Google Sheet +
Drive + Telegram. Invoked from the Cowork workflow prompts at end-of-run.

Subcommands:
  auth    - one-time OAuth browser consent
  daily   - process Daily News Brief output
  wsr     - process Weekly Strategy Review output
  dryrun  - parse a fixture and print what would be written, no network I/O

Exit codes:
  0 - all sinks OK
  1 - partial failure (stderr lists which)
  2 - fatal (auth / unreadable input)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Make both `python src/sync.py ...` (script) and `python -m src.sync ...` work.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src import schema as S  # type: ignore
    from src import sheets as sh  # type: ignore
    from src import telegram as tg  # type: ignore
else:
    from . import schema as S
    from . import sheets as sh
    from . import telegram as tg


def _get_drive():
    """Lazy import drive module so Daily path doesn't load pydrive2."""
    if __package__ in (None, ""):
        from src import drive as dr  # type: ignore
    else:
        from . import drive as dr
    return dr


# ---------- env + logging ----------

def load_env() -> None:
    """
    Load .env from project root if python-dotenv is available. Silent fallback
    to existing env vars if not.
    """
    root = Path(__file__).resolve().parent.parent
    env_path = root / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
    except ImportError:
        # Manual parse — avoid hard dependency on python-dotenv
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def setup_logging() -> logging.Logger:
    root = Path(__file__).resolve().parent.parent
    log_path = root / os.environ.get("SYNC_LOG", ".state/sync.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sync")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    # Avoid duplicate handlers on re-import
    if not logger.handlers:
        fh = logging.FileHandler(log_path)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        sh_ = logging.StreamHandler(sys.stderr)
        sh_.setFormatter(fmt)
        logger.addHandler(sh_)
    return logger


# ---------- result container ----------

@dataclass
class SyncResult:
    sheet_ok: bool = False
    drive_ok: bool = False
    telegram_ok: bool = False
    errors: List[str] = field(default_factory=list)
    rows_written: dict = field(default_factory=dict)  # tab -> count

    def exit_code(self, drive_required: bool, telegram_required: bool) -> int:
        ok = self.sheet_ok
        if drive_required:
            ok = ok and self.drive_ok
        if telegram_required:
            ok = ok and self.telegram_ok
        if ok:
            return 0
        if self.sheet_ok or self.drive_ok or self.telegram_ok:
            return 1  # partial
        return 2  # fatal


# ---------- subcommand: auth ----------

def cmd_auth(args: argparse.Namespace, logger: logging.Logger) -> int:
    try:
        client = sh.authenticate(force=bool(args.force))
        # Smoke-test: open the sheet metadata
        ss = client.open_by_key(os.environ["SHEET_ID"])
        logger.info(f"Auth OK. Sheet title: {ss.title}")
        print(f"auth ok — {ss.title}")
        return 0
    except Exception as e:
        logger.error(f"Auth failed: {e}")
        traceback.print_exc()
        return 2


# ---------- subcommand: daily ----------

def cmd_daily(args: argparse.Namespace, logger: logging.Logger) -> int:
    result = SyncResult()
    try:
        sidecar_path = Path(args.json)
        if not sidecar_path.exists():
            logger.error(f"Sidecar JSON missing: {sidecar_path}")
            return 2
        sidecar = json.loads(sidecar_path.read_text())
        date = str(sidecar.get("date") or datetime.now().strftime("%Y-%m-%d"))

        daily_row = S.daily_from_sidecar(sidecar)
        # Daily may carry optional 'macro' block if the pipeline emits it
        macro_row: Optional[S.MacroRow] = None
        if isinstance(sidecar.get("macro"), dict):
            macro_row = S.MacroRow(date=date, **{
                k: sidecar["macro"].get(k) for k in ("vix", "dxy", "us_10y", "spx", "usd_sgd")
            })

        if args.dryrun:
            print(f"[dryrun] daily_brief_latest row: {daily_row.to_row()}")
            if macro_row:
                print(f"[dryrun] macro row: {macro_row.to_row()}")
            else:
                print("[dryrun] macro row: (skipped — no 'macro' block in sidecar)")
            print(f"[dryrun] telegram would send: daily ready + PWA URL")
            return 0

        # --- Sheets ---
        try:
            client = sh.authenticate()
            sh.ensure_headers(client, S.DailyBriefRow.TAB_NAME, S.DailyBriefRow.HEADERS)
            sh.append_row(client, S.DailyBriefRow.TAB_NAME, daily_row.to_row())
            result.rows_written[S.DailyBriefRow.TAB_NAME] = 1
            if macro_row:
                sh.ensure_headers(client, S.MacroRow.TAB_NAME, S.MacroRow.HEADERS)
                sh.append_row(client, S.MacroRow.TAB_NAME, macro_row.to_row())
                result.rows_written[S.MacroRow.TAB_NAME] = 1
            result.sheet_ok = True
            logger.info(f"Sheets OK — {result.rows_written}")
        except Exception as e:
            result.errors.append(f"sheets: {e}")
            logger.error(f"Sheets failed: {e}")

        # --- Drive: N/A for Daily (md-only per format rule) ---
        result.drive_ok = True  # not required

        # --- Telegram ---
        try:
            pwa_url = os.environ.get("PWA_URL") or None
            tg.ping_daily_ready(date, pwa_url)
            result.telegram_ok = True
            logger.info("Telegram OK")
        except Exception as e:
            result.errors.append(f"telegram: {e}")
            logger.error(f"Telegram failed: {e}")

        print(json.dumps(asdict(result), indent=2))
        return result.exit_code(drive_required=False, telegram_required=True)

    except Exception as e:
        logger.error(f"Daily sync fatal: {e}")
        traceback.print_exc()
        return 2


# ---------- subcommand: wsr ----------

def cmd_wsr(args: argparse.Namespace, logger: logging.Logger) -> int:
    result = SyncResult()
    try:
        ledger_path = Path(args.ledger)
        pdf_path = Path(args.pdf) if args.pdf else None
        if not ledger_path.exists():
            logger.error(f"Ledger JSON missing: {ledger_path}")
            return 2
        ledger = json.loads(ledger_path.read_text())
        date = str(ledger.get("date") or datetime.now().strftime("%Y-%m-%d"))

        # Build all rows up-front
        snap_c = S.snapshot_caspar_from_ledger(ledger, date)
        pos_c = S.positions_caspar_from_ledger(ledger, date)
        snap_s = S.snapshot_sarah_from_ledger(ledger, date)
        pos_s = S.positions_sarah_from_ledger(ledger, date)
        macro = S.macro_from_ledger(ledger, date)
        decisions = S.decisions_from_ledger(ledger, date)

        if args.dryrun:
            print(f"[dryrun] snapshot_caspar: {snap_c.to_row()}")
            print(f"[dryrun] positions_caspar: {len(pos_c)} rows")
            for p in pos_c[:3]:
                print(f"  {p.to_row()}")
            if snap_s:
                print(f"[dryrun] snapshot_sarah: {snap_s.to_row()}")
                print(f"[dryrun] positions_sarah: {len(pos_s)} rows")
            else:
                print("[dryrun] snapshot_sarah: (skipped — ledger.sarah_portfolio absent)")
            print(f"[dryrun] decision_queue: {len(decisions)} rows")
            print(f"[dryrun] macro: {macro.to_row()}")
            print(f"[dryrun] drive upload: {pdf_path.name if pdf_path else '(none)'}")
            print(f"[dryrun] telegram: WSR ready + PWA URL")
            return 0

        # --- Sheets ---
        try:
            client = sh.authenticate()

            # snapshot_caspar
            sh.ensure_headers(client, S.SnapshotCaspar.TAB_NAME, S.SnapshotCaspar.HEADERS)
            sh.append_row(client, S.SnapshotCaspar.TAB_NAME, snap_c.to_row())
            result.rows_written[S.SnapshotCaspar.TAB_NAME] = 1

            # positions_caspar
            sh.ensure_headers(client, "positions_caspar", S.PositionRow.HEADERS)
            n = sh.append_rows(client, "positions_caspar", [p.to_row() for p in pos_c])
            result.rows_written["positions_caspar"] = n

            # Sarah — only if ledger carries her portfolio
            if snap_s:
                sh.ensure_headers(client, S.SnapshotSarah.TAB_NAME, S.SnapshotSarah.HEADERS)
                sh.append_row(client, S.SnapshotSarah.TAB_NAME, snap_s.to_row())
                result.rows_written[S.SnapshotSarah.TAB_NAME] = 1
                sh.ensure_headers(client, "positions_sarah", S.PositionRow.HEADERS)
                n = sh.append_rows(client, "positions_sarah", [p.to_row() for p in pos_s])
                result.rows_written["positions_sarah"] = n

            # decision_queue
            if decisions:
                sh.ensure_headers(client, S.DecisionRow.TAB_NAME, S.DecisionRow.HEADERS)
                n = sh.append_rows(client, S.DecisionRow.TAB_NAME, [d.to_row() for d in decisions])
                result.rows_written[S.DecisionRow.TAB_NAME] = n

            # macro
            sh.ensure_headers(client, S.MacroRow.TAB_NAME, S.MacroRow.HEADERS)
            sh.append_row(client, S.MacroRow.TAB_NAME, macro.to_row())
            result.rows_written[S.MacroRow.TAB_NAME] = 1

            result.sheet_ok = True
            logger.info(f"Sheets OK — {result.rows_written}")
        except Exception as e:
            result.errors.append(f"sheets: {e}")
            logger.error(f"Sheets failed: {e}")

        # --- Drive ---
        if pdf_path and pdf_path.exists():
            try:
                dr = _get_drive()
                file_id = dr.upload_pdf(pdf_path)
                result.drive_ok = True
                logger.info(f"Drive OK — file_id {file_id}")
                # Write archive row so PWA can list WSR PDFs
                try:
                    archive_row = S.WsrArchiveRow(
                        date=date, title=pdf_path.stem, drive_file_id=file_id,
                    )
                    sh.ensure_headers(client, S.WsrArchiveRow.TAB_NAME, S.WsrArchiveRow.HEADERS)
                    sh.append_row(client, S.WsrArchiveRow.TAB_NAME, archive_row.to_row())
                    result.rows_written[S.WsrArchiveRow.TAB_NAME] = 1
                except Exception as ae:
                    logger.warning(f"Archive row failed (non-fatal): {ae}")
            except Exception as e:
                result.errors.append(f"drive: {e}")
                logger.error(f"Drive failed: {e}")
        else:
            result.drive_ok = True  # nothing requested
            if args.pdf:
                result.errors.append(f"drive: pdf path not found ({args.pdf})")

        # --- Telegram ---
        try:
            pwa_url = os.environ.get("PWA_URL") or None
            tg.ping_wsr_ready(date, pwa_url)
            result.telegram_ok = True
            logger.info("Telegram OK")
        except Exception as e:
            result.errors.append(f"telegram: {e}")
            logger.error(f"Telegram failed: {e}")

        print(json.dumps(asdict(result), indent=2))
        return result.exit_code(
            drive_required=bool(args.pdf),
            telegram_required=True,
        )

    except Exception as e:
        logger.error(f"WSR sync fatal: {e}")
        traceback.print_exc()
        return 2


# ---------- subcommand: grab ----------

def cmd_grab(args: argparse.Namespace, logger: logging.Logger) -> int:
    """Push IBKR portfolio grab (both accounts) to Sheet + Telegram."""
    result = SyncResult()
    try:
        grab_path = Path(args.json)
        if not grab_path.exists():
            logger.error(f"Grab JSON missing: {grab_path}")
            return 2
        grab = json.loads(grab_path.read_text())
        date = str(grab.get("grab_date") or datetime.now().strftime("%Y-%m-%d"))

        snap_c = S.snapshot_caspar_from_grab(grab)
        pos_c = S.positions_caspar_from_grab(grab)
        snap_s = S.snapshot_sarah_from_grab(grab)
        pos_s = S.positions_sarah_from_grab(grab)

        # Count skipped options for info
        opts = grab.get("accounts", {}).get("sarah", {}).get("options") or []
        opts_skipped = len(opts)

        if args.dryrun:
            print(f"[dryrun] snapshot_caspar: {snap_c.to_row()}")
            print(f"[dryrun] positions_caspar: {len(pos_c)} rows")
            for p in pos_c[:3]:
                print(f"  {p.to_row()}")
            if len(pos_c) > 3:
                print(f"  ... and {len(pos_c) - 3} more")
            print(f"[dryrun] snapshot_sarah: {snap_s.to_row()}")
            print(f"[dryrun] positions_sarah: {len(pos_s)} rows (stocks only)")
            for p in pos_s[:3]:
                print(f"  {p.to_row()}")
            if len(pos_s) > 3:
                print(f"  ... and {len(pos_s) - 3} more")
            if opts_skipped:
                print(f"[dryrun] options skipped: {opts_skipped} (short calls — no options tab yet)")
            print(f"[dryrun] telegram: grab ready + date")
            return 0

        # --- Sheets ---
        try:
            client = sh.authenticate()

            sh.ensure_headers(client, S.SnapshotCaspar.TAB_NAME, S.SnapshotCaspar.HEADERS)
            sh.append_row(client, S.SnapshotCaspar.TAB_NAME, snap_c.to_row())
            result.rows_written[S.SnapshotCaspar.TAB_NAME] = 1

            sh.ensure_headers(client, "positions_caspar", S.PositionRow.HEADERS)
            n = sh.append_rows(client, "positions_caspar", [p.to_row() for p in pos_c])
            result.rows_written["positions_caspar"] = n

            sh.ensure_headers(client, S.SnapshotSarah.TAB_NAME, S.SnapshotSarah.HEADERS)
            sh.append_row(client, S.SnapshotSarah.TAB_NAME, snap_s.to_row())
            result.rows_written[S.SnapshotSarah.TAB_NAME] = 1

            sh.ensure_headers(client, "positions_sarah", S.PositionRow.HEADERS)
            n = sh.append_rows(client, "positions_sarah", [p.to_row() for p in pos_s])
            result.rows_written["positions_sarah"] = n

            result.sheet_ok = True
            logger.info(f"Sheets OK — {result.rows_written}")
        except Exception as e:
            result.errors.append(f"sheets: {e}")
            logger.error(f"Sheets failed: {e}")

        # --- Drive: N/A for grab ---
        result.drive_ok = True

        # --- Telegram ---
        try:
            pwa_url = os.environ.get("PWA_URL") or None
            tg.ping_grab_ready(date, len(pos_c), len(pos_s), opts_skipped, pwa_url)
            result.telegram_ok = True
            logger.info("Telegram OK")
        except Exception as e:
            result.errors.append(f"telegram: {e}")
            logger.error(f"Telegram failed: {e}")

        print(json.dumps(asdict(result), indent=2))
        return result.exit_code(drive_required=False, telegram_required=True)

    except Exception as e:
        logger.error(f"Grab sync fatal: {e}")
        traceback.print_exc()
        return 2


# ---------- subcommand: dryrun ----------

def cmd_dryrun(args: argparse.Namespace, logger: logging.Logger) -> int:
    """
    Route to the appropriate command with dryrun flag set. User picks the
    fixture kind via --kind (daily|wsr) or auto-detects from fixture filename.
    """
    fixture = Path(args.fixture)
    if not fixture.exists():
        logger.error(f"Fixture missing: {fixture}")
        return 2

    kind = args.kind
    if not kind:
        name = fixture.name.lower()
        if "daily" in name or "brief" in name:
            kind = "daily"
        elif "wsr" in name or "ledger" in name:
            kind = "wsr"
        else:
            logger.error("Cannot infer kind from fixture name; pass --kind daily|wsr")
            return 2

    if kind == "daily":
        fake_args = argparse.Namespace(json=str(fixture), dryrun=True)
        return cmd_daily(fake_args, logger)
    elif kind == "wsr":
        fake_args = argparse.Namespace(ledger=str(fixture), md=None, pdf=None, dryrun=True)
        return cmd_wsr(fake_args, logger)
    else:
        logger.error(f"Unknown kind: {kind}")
        return 2


# ---------- main ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sync", description="FinancePWA sync CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("auth", help="one-time OAuth consent")
    a.add_argument("--force", action="store_true", help="delete cached token first")

    d = sub.add_parser("daily", help="push Daily Brief outputs")
    d.add_argument("--json", required=True, help="path to Daily brief sidecar JSON")
    d.add_argument("--md", required=False, help="path to Daily md (informational)")
    d.add_argument("--dryrun", action="store_true", help="parse only, no network")

    w = sub.add_parser("wsr", help="push WSR outputs")
    w.add_argument("--ledger", required=True, help="path to WSR analysis_ledger.json")
    w.add_argument("--md", required=False, help="path to WSR md (informational)")
    w.add_argument("--pdf", required=False, help="path to WSR PDF for Drive upload")
    w.add_argument("--dryrun", action="store_true", help="parse only, no network")

    g = sub.add_parser("grab", help="push IBKR portfolio grab (both accounts)")
    g.add_argument("--json", required=True, help="path to PortfolioGrab JSON")
    g.add_argument("--dryrun", "--dry-run", action="store_true", help="parse only, no network")

    dr_ = sub.add_parser("dryrun", help="parse fixture, print what would be written")
    dr_.add_argument("--fixture", required=True, help="path to fixture JSON")
    dr_.add_argument("--kind", choices=("daily", "wsr"), required=False)

    return p


def main() -> int:
    load_env()
    logger = setup_logging()
    args = build_parser().parse_args()

    if args.cmd == "auth":
        return cmd_auth(args, logger)
    if args.cmd == "daily":
        return cmd_daily(args, logger)
    if args.cmd == "wsr":
        return cmd_wsr(args, logger)
    if args.cmd == "grab":
        return cmd_grab(args, logger)
    if args.cmd == "dryrun":
        return cmd_dryrun(args, logger)
    logger.error(f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
