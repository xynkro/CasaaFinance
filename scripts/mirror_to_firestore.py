#!/usr/bin/env python3
"""
mirror_to_firestore.py — copy the PWA-needed Google Sheet tabs into Firestore so
the PWA can read portfolio data **privately** (behind Firebase Auth + security
rules) instead of via the public gviz CSV endpoint.

Why this exists
  The PWA reads ~39 Sheet tabs via the *public* gviz CSV endpoint, leaking real
  financial data to anyone who view-sources the bundle. This mirror is the one
  new hop: a 15-min GitHub Action reads each tab and writes it to a private
  Firestore doc. The Sheet stays the hand-editable source of truth; cron writers
  and hand-edits are untouched. See docs/plans/2026-06-07-private-read-path-*.

Firestore doc contract (shared with the PWA reader — do NOT deviate)
  Collection `tabs`, document id = tab name:
      { rows: Array<object>, updatedAt: <iso str>, rowCount: int,
        sourceHash: <sha256 hex of json(rows)>, chunks: int }
  A tab whose serialized doc would exceed ~900 KB is split into a base doc
  `tabs/{name}` plus numbered chunk docs `tabs/{name}__1`, `tabs/{name}__2`, …
  each under 900 KB, with the base doc's `chunks` = N. The reader concatenates
  rows across base + numbered chunks in order. Normal tabs have `chunks` = 0 and
  all rows in the base doc.

Inert-without-key
  The whole module is a **no-op when `FIREBASE_SERVICE_ACCOUNT_JSON` is unset** —
  `_db()` logs one clear line and returns `None`, and `main()` exits 0 without
  touching the network. Exactly like `src/gmail_client._access_token()` and
  `src/news_aggregator.fetch_newsdata()`: committing this changes nothing until
  Caspar pastes the service-account JSON into CI secrets + `.env`.

Fail-safe
  Per-tab try/except → log + skip + keep the last-good doc (never delete).
  Hash-diff: a tab whose existing doc `sourceHash` matches the freshly-read rows
  is skipped (no write). Exit codes mirror `src/sync.py`:
      0 — all tabs ok (written, unchanged, or cleanly skipped)
      1 — partial (≥1 tab errored, others mirrored)
      2 — fatal (auth: could not build a Firestore client when a key was present)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("mirror_to_firestore")


# --- the exact 39 tabs the PWA fetches (from data.ts `fetchDashboard`) ---
# Authoritative list lives in docs/plans/2026-06-07-private-read-path-plan.md.
# Order is informational; mirroring is per-tab and order-independent.
PWA_TABS: list[str] = [
    "daily_brief_latest",
    "snapshot_caspar",
    "snapshot_sarah",
    "positions_caspar",
    "positions_sarah",
    "options",
    "technical_scores",
    "wheel_next_leg",
    "exit_plans",
    "options_defense",
    "wsr_summary",
    "decision_queue",
    "macro",
    "wsr_archive",
    "regime_signals",
    "exposure_posture",
    "screen_candidates",
    "tv_signals",
    "risk_parity_audit",
    "live_prices",
    "earnings_calendar",
    "economic_calendar",
    "news_sentiment",
    "insider_transactions",
    "analyst_consensus",
    "api_usage",
    "gov_confluence_signals",
    "congress_trades",
    "snapshot_alpaca",
    "positions_alpaca",
    "harvest_scan",
    "iv_surface_scan",
    "uoa_alerts",
    "scan_results",
    "paper_benchmark",
    "gex_regime",
    "daily_plan",
    "macro_lean",
    "curated_picks",
]

# Per-doc serialized-size ceiling. Firestore's hard limit is 1 MiB/doc; we leave
# headroom for the wrapper fields (updatedAt/rowCount/sourceHash/chunks) and
# Firestore's own per-field overhead by chunking anything whose `rows` JSON
# exceeds this.
MAX_DOC_BYTES = 900_000

# Default rows kept per tab. Rows are chronological (oldest→newest in the Sheet),
# so we keep the tail. The PWA only ever needs the most-recent slice.
DEFAULT_CAP = 400

_ENV_KEY = "FIREBASE_SERVICE_ACCOUNT_JSON"


# ---------- helpers ----------

def _now_iso() -> str:
    """UTC ISO-8601 timestamp for `updatedAt` (e.g. 2026-06-07T12:00:00+00:00)."""
    return datetime.now(timezone.utc).isoformat()


def _source_hash(rows: list[dict]) -> str:
    """sha256 hex of the canonically-serialized rows.

    `sort_keys=True` + tight separators make the hash stable regardless of dict
    key ordering, so an unchanged tab hashes identically run-to-run and the
    hash-diff can skip the write. `default=str` keeps it total over odd cell
    types (datetimes etc.) that gspread might hand back.
    """
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cap_rows(rows: list[dict], cap: int) -> list[dict]:
    """Keep the last `cap` rows (rows are chronological → keep the tail).

    `cap <= 0` means "no cap" (keep everything). Defensive against a `None`/empty
    rows argument.
    """
    rows = rows or []
    if cap and cap > 0 and len(rows) > cap:
        return rows[-cap:]
    return rows


def _rows_json_size(rows: list[dict]) -> int:
    """Byte length of the rows array serialized the way it goes into the doc."""
    return len(json.dumps(rows, separators=(",", ":"), default=str).encode("utf-8"))


def _chunk_if_oversize(name: str, rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Split a tab's rows across base + numbered chunk docs if oversize.

    Returns a list of `(doc_id, rows_slice)` pairs:
      - normal tab → `[(name, rows)]` (single base doc, caller sets chunks=0)
      - oversize   → `[(name, slice0), (f"{name}__1", slice1), …]` where each
        slice serializes under `MAX_DOC_BYTES`. The caller writes the base doc
        with `chunks` = (number of numbered chunks) and each numbered chunk as a
        bare `{rows, …}` doc.

    Splitting is greedy: accumulate rows into the current slice until adding the
    next row would exceed the ceiling, then start a new slice. A single row that
    is itself larger than the ceiling lands alone in its own chunk (we can't
    split within a row); Firestore would reject it, which is the correct loud
    failure rather than silent truncation.
    """
    rows = rows or []
    if _rows_json_size(rows) <= MAX_DOC_BYTES:
        return [(name, rows)]

    chunks: list[list[dict]] = []
    current: list[dict] = []
    for row in rows:
        candidate = current + [row]
        if current and _rows_json_size(candidate) > MAX_DOC_BYTES:
            chunks.append(current)
            current = [row]
        else:
            current = candidate
    if current:
        chunks.append(current)

    out: list[tuple[str, list[dict]]] = []
    for i, slice_rows in enumerate(chunks):
        doc_id = name if i == 0 else f"{name}__{i}"
        out.append((doc_id, slice_rows))
    return out


def _existing_hash(db: Any, name: str) -> Optional[str]:
    """Read the current doc's `sourceHash` for hash-diff. None if missing/error.

    A read failure must never block a write — we degrade to "no known hash" so
    the tab is treated as changed and re-written.
    """
    try:
        snap = db.collection("tabs").document(name).get()
        if not getattr(snap, "exists", False):
            return None
        data = snap.to_dict() or {}
        h = data.get("sourceHash")
        return str(h) if h else None
    except Exception as e:  # noqa: BLE001 — isolated, never fatal
        log.warning("hash read failed for %s: %s", name, e)
        return None


# ---------- core ----------

def mirror_tab(read_tab: Callable[[str], list[dict]], db: Any, name: str,
               cap: int = DEFAULT_CAP) -> str:
    """Mirror one tab. Returns a status string.

    Statuses: "written" | "unchanged" | "empty" | "error".
    Raises nothing — errors are caught by `mirror_tabs` per tab. This helper does
    the read → cap → hash → diff → (chunk) write for a single tab so the loop in
    `mirror_tabs` stays a thin try/except wrapper.
    """
    rows = read_tab(name) or []
    rows = _cap_rows(rows, cap)
    source_hash = _source_hash(rows)

    if _existing_hash(db, name) == source_hash:
        log.info("tab %s unchanged (hash %s…) — skip", name, source_hash[:8])
        return "unchanged"

    pieces = _chunk_if_oversize(name, rows)
    n_chunks = len(pieces) - 1  # numbered chunks beyond the base doc
    updated_at = _now_iso()

    # Write numbered chunks first, then the base doc last. The base doc's
    # `chunks` count is what the reader trusts to know how many to fetch; writing
    # it last means a reader never sees chunks=N before chunk N exists.
    for doc_id, slice_rows in pieces[1:]:
        db.collection("tabs").document(doc_id).set({
            "rows": slice_rows,
            "rowCount": len(slice_rows),
            "updatedAt": updated_at,
        })

    db.collection("tabs").document(name).set({
        "rows": pieces[0][1],
        "updatedAt": updated_at,
        "rowCount": len(rows),          # total across base + chunks
        "sourceHash": source_hash,
        "chunks": n_chunks,
    })

    if n_chunks:
        log.info("tab %s written — %d rows across base + %d chunk(s)",
                 name, len(rows), n_chunks)
    else:
        log.info("tab %s written — %d rows", name, len(rows))
    return "written" if rows else "empty"


def mirror_tabs(read_tab: Callable[[str], list[dict]], db: Any,
                tabs: list[str] = PWA_TABS, cap: int = DEFAULT_CAP) -> dict[str, str]:
    """Mirror all `tabs` into Firestore. Returns `{tab: status}`.

    Per-tab try/except: a tab that raises is logged + recorded as "error" and the
    loop continues; the last-good doc for that tab is never touched. This is the
    fail-safe the design requires — one bad Sheet read can't take down the run or
    wipe good data.
    """
    results: dict[str, str] = {}
    for name in tabs:
        try:
            results[name] = mirror_tab(read_tab, db, name, cap=cap)
        except Exception as e:  # noqa: BLE001 — isolate per tab, keep going
            # A tab that simply doesn't exist in the Sheet yet (an optional tab
            # whose pipeline hasn't created it — e.g. macro_lean, curated_picks)
            # is NOT a failure: the PWA already tolerates its absence (.catch ->
            # []). gspread raises WorksheetNotFound; match by class name so the
            # generic core stays gspread-free.
            if type(e).__name__ == "WorksheetNotFound":
                log.info("tab %s not in Sheet yet — skipping (benign)", name)
                results[name] = "missing"
            else:
                log.error("tab %s failed: %s — skipping (last-good doc preserved)", name, e)
                results[name] = "error"
    return results


# ---------- wiring (auth + sheet read) ----------

def _db() -> Optional[Any]:
    """Return an initialized Firestore client, or None when inert.

    Inert path (no log noise beyond one info line): `FIREBASE_SERVICE_ACCOUNT_JSON`
    unset → return None. `main()` treats None as a clean no-op exit 0. This
    mirrors the project's inert-without-key pattern (gmail_client / news_aggregator).

    With the key present, init `firebase-admin` from the service-account JSON and
    return a Firestore client. A failure here is a real auth fault → the
    exception propagates so `main()` can exit 2.
    """
    sa_json = os.environ.get(_ENV_KEY)
    if not sa_json:
        log.info("%s unset — mirror is inert (no-op, exit 0)", _ENV_KEY)
        return None

    # Lazy import so the module imports cleanly (and tests run) without
    # firebase-admin installed; it's only needed on the live write path.
    import firebase_admin
    from firebase_admin import credentials, firestore

    info = json.loads(sa_json)
    cred = credentials.Certificate(info)
    # Guard against re-init if something already initialized the default app.
    try:
        app = firebase_admin.get_app()
    except ValueError:
        app = firebase_admin.initialize_app(cred)
    return firestore.client(app)


def _default_read_tab(name: str) -> list[dict]:
    """Read a worksheet's rows as a list of dicts via the project's Sheets layer.

    Uses `src.sheets.authenticate()` (OAUTH_TOKEN_JSON / service-account / local
    OAuth, same credential every other workflow uses) then
    `worksheet(name).get_all_records()`, which returns one dict per data row keyed
    by the header — exactly the `rows: Array<object>` shape the PWA's PapaParse
    (`header: true`) path produces today, so downstream parsing is unchanged.
    """
    # Make `python scripts/mirror_to_firestore.py` work without installing the
    # package — put the project root on sys.path, then import src.sheets.
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from src import sheets as sh  # type: ignore

    client = sh.authenticate()
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        raise RuntimeError("SHEET_ID not set in environment")
    ss = client.open_by_key(sheet_id)
    return ss.worksheet(name).get_all_records()


def _load_env() -> None:
    """Load .env from project root if python-dotenv is available (best-effort).

    Mirrors src/sync.load_env so a local run picks up SHEET_ID / creds without
    exporting them by hand. Silent if .env is absent or dotenv isn't installed.
    """
    root = Path(__file__).resolve().parent.parent
    env_path = root / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
    except Exception:  # noqa: BLE001 — env loading must never be fatal
        pass


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint. Exit 0 all-ok / 1 partial / 2 fatal-auth.

    Inert when the service-account key is unset (clean exit 0). Otherwise reads
    every PWA tab from the Sheet and mirrors it to Firestore, then returns the
    summary exit code based on per-tab results.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    _load_env()

    db = _db()
    if db is None:
        # Inert path — the one clear log line was emitted by _db().
        return 0

    try:
        # Pass PWA_TABS explicitly (read at call time) rather than relying on the
        # function default, which is bound once at definition.
        results = mirror_tabs(_default_read_tab, db, tabs=PWA_TABS)
    except Exception as e:  # noqa: BLE001 — unexpected top-level fault
        log.error("fatal: %s", e)
        traceback.print_exc()
        return 2

    written = sum(1 for v in results.values() if v in ("written", "empty"))
    unchanged = sum(1 for v in results.values() if v == "unchanged")
    missing = sum(1 for v in results.values() if v == "missing")
    errored = sum(1 for v in results.values() if v == "error")
    log.info("mirror summary: %d written, %d unchanged, %d missing, %d errored (of %d tabs)",
             written, unchanged, missing, errored, len(results))

    if errored == 0:
        return 0
    if written or unchanged:
        return 1  # partial
    return 2      # everything failed → treat as fatal


if __name__ == "__main__":
    sys.exit(main())
