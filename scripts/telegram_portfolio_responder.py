"""
telegram_portfolio_responder.py — every-N-min Telegram bot poller.

⚠️ INACTIVE — single-bot conflict.

The @Tron_Shaft_Bot is also polled by ZeroDTE's FastAPI service. Telegram's
getUpdates model only supports ONE polling client per bot — two clients
race and ack each other's messages. So the GH Actions cron for this
responder is intentionally absent. To re-enable, you need either:

(a) extend ZeroDTE's command handler to read FinancePWA's snapshot
    sheets and reply with the portfolio summary (recommended — single
    bot, single command surface), OR
(b) create a separate bot via @BotFather (e.g. @Casaa_Finance_Bot),
    set its token as TELEGRAM_BOT_TOKEN, and re-add the workflow.

The summary helper at src/portfolio_summary.py is project-agnostic and
can be imported by either path. The functions below remain useful for
ad-hoc local polls (`casaa portfolio-respond`) when ZeroDTE's responder
isn't running, e.g. between dev sessions.

Original docstring follows.
─────────────────────────────────────────────────────────────────────

Watches the "Portfolio Ping" topic in the Finance & Trading supergroup
for messages matching `~/portfolio` (or `/portfolio`, `~/positions`,
`/positions`). When a known user posts one, the bot replies in-thread
with a snapshot of THEIR account.

User → account mapping resolved via env (TELEGRAM_USER_CASPAR,
TELEGRAM_USER_SARAH). Unknown users get a polite "I don't know who
you are" reply with their user_id so an admin can register them.

State: `telegram_offset` sheet stores `last_update_id` so the cron
doesn't re-process old messages. Single row, UPSERT on every run.

Usage
-----
    python scripts/telegram_portfolio_responder.py             # poll once + reply
    python scripts/telegram_portfolio_responder.py --dry       # show what we'd do
    python scripts/telegram_portfolio_responder.py --reset     # clear offset (replay 24h)

Schedule
--------
.github/workflows/telegram-responder.yml — every 2 min during waking
hours (07:00-23:00 SGT = 23:00-15:00 UTC)
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.sync import load_env       # noqa: E402
from src import sheets as sh        # noqa: E402
from src import schema as S         # noqa: E402
from src import telegram as tg      # noqa: E402
from src.portfolio_summary import build_portfolio_summary  # noqa: E402

import requests  # noqa: E402

# ────────────────────────────────────────────────────────────────────
# Config — match the Finance & Trading supergroup setup
# ────────────────────────────────────────────────────────────────────
GROUP_CHAT_ID    = "-1003942004211"
PORTFOLIO_PING_TOPIC = 31

# Commands we listen for. Case-insensitive whole-word match.
COMMAND_RE = re.compile(
    r"^\s*[~/](portfolio|positions|snapshot)\b",
    re.IGNORECASE,
)


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("telegram-portfolio-responder")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger


def _user_to_account() -> dict[int, str]:
    """Read user→account mapping from env. None when unset."""
    out: dict[int, str] = {}
    caspar_id = os.environ.get("TELEGRAM_USER_CASPAR", "")
    sarah_id = os.environ.get("TELEGRAM_USER_SARAH", "")
    if caspar_id and caspar_id.isdigit():
        out[int(caspar_id)] = "caspar"
    if sarah_id and sarah_id.isdigit():
        out[int(sarah_id)] = "sarah"
    return out


# ────────────────────────────────────────────────────────────────────
# Telegram API wrappers
# ────────────────────────────────────────────────────────────────────

def _api(method: str, params: dict, timeout: int = 30) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    r = requests.post(
        f"https://api.telegram.org/bot{token}/{method}",
        json=params,
        timeout=timeout,
    )
    r.raise_for_status()
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} error: {body}")
    return body.get("result")


def get_updates(offset: int, timeout: int = 0) -> list[dict]:
    """getUpdates with no long-poll (cron-driven)."""
    return _api("getUpdates", {
        "offset": offset,
        "timeout": timeout,
        "limit": 100,
        "allowed_updates": ["message"],
    })


def reply_to(thread_id: int, text: str, reply_to_message_id: int | None = None) -> dict:
    """Reply inside the Portfolio Ping topic, optionally quoting the trigger msg."""
    payload = {
        "chat_id": GROUP_CHAT_ID,
        "message_thread_id": thread_id,
        "text": text,
    }
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    return _api("sendMessage", payload)


# ────────────────────────────────────────────────────────────────────
# Sheet state — telegram_offset (single row)
# ────────────────────────────────────────────────────────────────────

def load_offset(client) -> int:
    """Latest stored offset (or 0 to fetch all unread)."""
    sh.ensure_headers(client, S.TelegramOffsetRow.TAB_NAME, S.TelegramOffsetRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.TelegramOffsetRow.TAB_NAME)
    rows = ws.get_all_values()
    if len(rows) < 2:
        return 0
    for r in rows[1:]:
        if r and r[0] == "last":
            try:
                return int(r[1])
            except (ValueError, TypeError):
                return 0
    return 0


def save_offset(client, offset: int, logger: logging.Logger) -> None:
    sh.ensure_headers(client, S.TelegramOffsetRow.TAB_NAME, S.TelegramOffsetRow.HEADERS)
    ss = sh._open_sheet(client)
    ws = ss.worksheet(S.TelegramOffsetRow.TAB_NAME)
    rows = ws.get_all_values()
    hdr = rows[0] if rows else list(S.TelegramOffsetRow.HEADERS)
    keep = [hdr]
    for r in rows[1:]:
        if r and r[0] == "last":
            continue
        keep.append(r)
    keep.append([
        "last", str(offset), S.now_sgt_iso(),
    ])
    ws.clear()
    ws.update(values=keep, range_name="A1", value_input_option="USER_ENTERED")
    logger.info(f"✓ telegram_offset saved: {offset}")


# ────────────────────────────────────────────────────────────────────
# Snapshot lookup — read latest row for an account from sheets
# ────────────────────────────────────────────────────────────────────

def fetch_account_summary(client, account: str, logger: logging.Logger) -> str:
    """Build the portfolio summary string for `account`.

    Reads:
      - snapshot_<account>          → top metrics
      - positions_<account>         → top holdings
      - options                     → count of options held
    """
    ss = sh._open_sheet(client)
    name_lc = account.lower()

    # Snapshot
    snap_tab = "snapshot_caspar" if name_lc == "caspar" else "snapshot_sarah"
    ws = ss.worksheet(snap_tab)
    snap_rows = ws.get_all_values()
    snapshot: dict | None = None
    if len(snap_rows) > 1:
        hdr = snap_rows[0]
        # Sarah uses *_sgd suffix variants — normalize to net_liq/cash/upl/upl_pct.
        latest = max(snap_rows[1:], key=lambda r: r[0] if r else "")
        rec = {hdr[i]: (latest[i] if i < len(latest) else "") for i in range(len(hdr))}
        snapshot = {
            "date": rec.get("date", ""),
            "net_liq": rec.get("net_liq") or rec.get("net_liq_usd") or rec.get("net_liq_sgd") or "",
            "cash": rec.get("cash") or rec.get("cash_sgd") or "",
            "upl": rec.get("upl") or rec.get("upl_sgd") or "",
            "upl_pct": rec.get("upl_pct") or "",
        }

    # Positions — latest BATCH only (exact date match, mirroring the
    # PWA's `latestGroup()`). Yahoo-grab writes all positions for a
    # refresh with identical audit-suffix timestamps, so filtering by
    # the full date string returns just that one batch — no SCHD-x6
    # duplicates from prior refreshes.
    pos_tab = "positions_caspar" if name_lc == "caspar" else "positions_sarah"
    ws = ss.worksheet(pos_tab)
    pos_rows = ws.get_all_values()
    positions: list[dict] = []
    if len(pos_rows) > 1:
        hdr = pos_rows[0]
        latest_ts = max((r[0] for r in pos_rows[1:] if r), default="")
        for r in pos_rows[1:]:
            if not r or r[0] != latest_ts:
                continue
            rec = {hdr[i]: (r[i] if i < len(r) else "") for i in range(len(hdr))}
            positions.append(rec)

    # Options count for this account — same exact-timestamp filter as positions.
    options_count = 0
    try:
        ws = ss.worksheet("options")
        opt_rows = ws.get_all_values()
        if len(opt_rows) > 1:
            hdr = opt_rows[0]
            account_col = hdr.index("account") if "account" in hdr else -1
            date_col = hdr.index("date") if "date" in hdr else 0
            latest_ts = max(
                (r[date_col] for r in opt_rows[1:] if r and len(r) > date_col),
                default="",
            )
            for r in opt_rows[1:]:
                if not r or len(r) <= max(date_col, account_col):
                    continue
                if r[date_col] != latest_ts:
                    continue
                if account_col >= 0 and r[account_col].lower() == name_lc:
                    options_count += 1
    except Exception as e:
        logger.warning(f"options count fetch failed: {e}")

    return build_portfolio_summary(account, snapshot, positions, options_count=options_count)


# ────────────────────────────────────────────────────────────────────
# Update processing
# ────────────────────────────────────────────────────────────────────

def is_target_message(update: dict) -> tuple[bool, str]:
    """Return (matches, reason). Match = portfolio command in our topic."""
    msg = update.get("message")
    if not msg:
        return False, "non-message update"
    chat = msg.get("chat", {})
    if str(chat.get("id")) != GROUP_CHAT_ID:
        return False, f"different chat ({chat.get('id')})"
    if msg.get("message_thread_id") != PORTFOLIO_PING_TOPIC:
        return False, f"different thread ({msg.get('message_thread_id')})"
    text = (msg.get("text") or "").strip()
    if not text:
        return False, "no text"
    if not COMMAND_RE.match(text):
        return False, f"not a command: {text[:40]!r}"
    return True, "match"


def process_update(client, update: dict, user_to_account: dict[int, str], logger: logging.Logger, dry: bool) -> None:
    msg = update["message"]
    user = msg.get("from", {})
    user_id = user.get("id")
    user_name = user.get("first_name") or user.get("username") or f"user_{user_id}"
    msg_id = msg.get("message_id")
    text = (msg.get("text") or "").strip()

    account = user_to_account.get(user_id)
    if not account:
        # Polite registration nudge.
        reply = (
            f"👋 Hi {user_name}!\n\n"
            f"I don't have your account on file yet. Ask the admin to add\n"
            f"  TELEGRAM_USER_<NAME>={user_id}\n"
            f"to repo secrets so I can look up your portfolio."
        )
        logger.info(f"  ↳ unknown user_id={user_id} ({user_name}) — sending nudge")
        if not dry:
            reply_to(PORTFOLIO_PING_TOPIC, reply, reply_to_message_id=msg_id)
        return

    logger.info(f"  ↳ {user_name} (user_id={user_id}, account={account}) — {text!r}")
    summary = fetch_account_summary(client, account, logger)
    if not dry:
        reply_to(PORTFOLIO_PING_TOPIC, summary, reply_to_message_id=msg_id)


# ────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry", action="store_true", help="Print plan, no replies, no offset save")
    p.add_argument("--reset", action="store_true", help="Reset offset to 0 (replay last 24h)")
    args = p.parse_args()

    logger = _setup_logging()
    logger.info(f"telegram_portfolio_responder start (dry={args.dry}, reset={args.reset})")

    load_env()
    client = sh.authenticate()

    user_map = _user_to_account()
    if not user_map:
        logger.warning(
            "No user_id mapping configured. Set TELEGRAM_USER_CASPAR / "
            "TELEGRAM_USER_SARAH env vars."
        )

    if args.reset:
        save_offset(client, 0, logger)
        logger.info("Offset reset to 0 — next run replays")
        return 0

    offset = load_offset(client)
    logger.info(f"Polling getUpdates(offset={offset}, mapping={user_map})")
    updates = get_updates(offset)
    logger.info(f"  fetched {len(updates)} updates")

    processed = 0
    for u in updates:
        match, why = is_target_message(u)
        if not match:
            logger.debug(f"  skip update_id={u.get('update_id')}: {why}")
            continue
        try:
            process_update(client, u, user_map, logger, args.dry)
            processed += 1
        except Exception as e:
            logger.warning(f"  ✗ failed update_id={u.get('update_id')}: {e}")

    if updates:
        new_offset = max(u["update_id"] for u in updates) + 1
        if not args.dry:
            save_offset(client, new_offset, logger)

    logger.info(f"telegram_portfolio_responder done — processed {processed}/{len(updates)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
