"""
Google Sheets wrapper — thin layer over gspread using OAuth user credentials.

Why OAuth user creds and not a service account?
  GCP org policy `iam.disableServiceAccountKeyCreation` blocks SA key creation on
  personal projects by default. For a single-user local script, OAuth user creds
  via the installed-app flow are simpler, safer, and unblocked. The refresh
  token is cached locally and used silently after first consent.

Public API:
  authenticate(force=False)      -> gspread.Client
  ensure_headers(client, ...)    -> create tab + write header row if missing
  append_row(client, tab, row)   -> append a single row to a tab
  append_rows(client, tab, rows) -> append many rows in one batch call
  upsert_tab(ws, values, ...)    -> ATOMIC full-tab overwrite (no empty window)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, List, Sequence

import gspread
from gspread.exceptions import WorksheetNotFound


# OAuth scopes needed for Sheets read/write and Drive file upload via the same
# credential. Drive scope is broader than necessary but pydrive2 needs it and
# bundling scopes avoids two consent prompts.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _paths() -> tuple[Path, Path]:
    """Resolve client-secret and token-cache paths relative to project root."""
    root = Path(__file__).resolve().parent.parent
    client_secret = root / os.environ.get("OAUTH_CLIENT_SECRET", ".config/client_secret.json")
    token_cache = root / os.environ.get("OAUTH_TOKEN_CACHE", ".state/authorized_user.json")
    token_cache.parent.mkdir(parents=True, exist_ok=True)
    return client_secret, token_cache


def _install_sheets_retry(max_tries: int = 5, base_delay: float = 5.0) -> None:
    """Patch gspread's HTTP layer to retry on Google Sheets rate limits (429)
    and transient 5xx, with exponential backoff. Many workflows hit the Sheet in
    the same minute and trip 'Read requests per minute' — a short backoff sleeps
    past the window instead of failing the whole run. Idempotent + defensive."""
    try:
        import time
        import gspread
        from gspread.exceptions import APIError
        hc = gspread.http_client.HTTPClient
    except Exception:
        return
    if getattr(hc.request, "_casaa_retry", False):
        return
    _orig = hc.request

    def _request(self, *args, **kwargs):
        delay = base_delay
        for attempt in range(max_tries):
            try:
                return _orig(self, *args, **kwargs)
            except APIError as e:
                code = getattr(getattr(e, "response", None), "status_code", None)
                if code in (429, 500, 502, 503) and attempt < max_tries - 1:
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise

    _request._casaa_retry = True
    hc.request = _request


def authenticate(force: bool = False) -> gspread.Client:
    """
    Returns an authorised gspread client. Three credential paths:

      1. **OAUTH_TOKEN_JSON env var** (CI / GitHub Actions) — full contents of
         a previously-cached authorized_user.json. No filesystem needed.
      2. **GOOGLE_SERVICE_ACCOUNT_JSON env var** — service-account key JSON.
      3. **Local OAuth flow** — falls back to gspread.oauth() with browser
         consent on first call, refresh-token thereafter.

    `force=True` only affects path 3 (deletes cached token to force re-consent).
    """
    _install_sheets_retry()   # backoff on 429 / transient 5xx for every request

    # Path 1: OAuth user-credential JSON via env var (CI-friendly)
    token_json = os.environ.get("OAUTH_TOKEN_JSON")
    if token_json:
        import json as _json
        from google.oauth2.credentials import Credentials
        info = _json.loads(token_json)
        creds = Credentials.from_authorized_user_info(info, scopes=SCOPES)
        return gspread.authorize(creds)

    # Path 2: Service account JSON via env var (preferred for true automation)
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        import json as _json
        from google.oauth2.service_account import Credentials as SACreds
        info = _json.loads(sa_json)
        creds = SACreds.from_service_account_info(info, scopes=SCOPES)
        return gspread.authorize(creds)

    # Path 3: Local browser OAuth flow (developer machine)
    client_secret, token_cache = _paths()
    if not client_secret.exists():
        raise FileNotFoundError(
            f"OAuth client secret not found at {client_secret}. "
            f"Set OAUTH_TOKEN_JSON or GOOGLE_SERVICE_ACCOUNT_JSON env var, "
            f"or download the OAuth Desktop client_secret from GCP Console "
            f"and place it at the configured path."
        )
    if force and token_cache.exists():
        token_cache.unlink()
    return gspread.oauth(
        scopes=SCOPES,
        credentials_filename=str(client_secret),
        authorized_user_filename=str(token_cache),
    )


def _open_sheet(client: gspread.Client) -> gspread.Spreadsheet:
    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        raise RuntimeError("SHEET_ID not set in environment")
    return client.open_by_key(sheet_id)


def ensure_headers(client: gspread.Client, tab_name: str, headers: List[str]) -> gspread.Worksheet:
    """
    Idempotent: creates the tab if missing, writes headers if first row is empty
    or mismatched. Safe to call on every run.
    """
    ss = _open_sheet(client)
    try:
        ws = ss.worksheet(tab_name)
    except WorksheetNotFound:
        ws = ss.add_worksheet(title=tab_name, rows=1000, cols=max(len(headers), 10))
        ws.append_row(headers, value_input_option="RAW")
        return ws

    # Check row 1
    try:
        first = ws.row_values(1)
    except Exception:
        first = []

    if first != headers:
        # Header row missing or drifted — overwrite
        ws.update("A1", [headers], value_input_option="RAW")
    return ws


def append_row(client: gspread.Client, tab_name: str, row: List[str]) -> None:
    ss = _open_sheet(client)
    ws = ss.worksheet(tab_name)
    ws.append_row(row, value_input_option="USER_ENTERED")


def append_rows(client: gspread.Client, tab_name: str, rows: Iterable[List[str]]) -> int:
    """Batch append. Returns count of rows appended."""
    rows_list = list(rows)
    if not rows_list:
        return 0
    ss = _open_sheet(client)
    ws = ss.worksheet(tab_name)
    ws.append_rows(rows_list, value_input_option="USER_ENTERED")
    return len(rows_list)


def replace_today_rows(client: gspread.Client, tab_name: str,
                       new_rows: Iterable[List[str]],
                       today_prefix: str | None = None) -> int:
    """Replace TODAY's rows with `new_rows` in one atomic write.

    The 30-min IBKR grab loop used to append a fresh batch every cycle without
    removing the prior one — by midday the positions tabs carried 5+ duplicate
    rows per (account, ticker), which exploded every PWA consumer (Concentration
    showed SCHD ×5, Movers showed AMD ×3, render churn lit Safari's
    'significant energy' kill). This helper does the upsert the writer SHOULD
    have been doing all along: keep every row whose date column doesn't start
    with today's prefix, then write the fresh batch — all in a single
    ``upsert_tab`` (no observable empty window).

    Date prefix defaults to today's ISO date (UTC). Empty `new_rows` is still a
    valid call — it removes today's stale rows without writing replacements
    (useful for tabs an account no longer participates in). Returns the count
    of rows in the fresh batch.
    """
    from datetime import date
    rows_list = [list(r) for r in new_rows]
    if today_prefix is None:
        today_prefix = date.today().isoformat()
    ss = _open_sheet(client)
    ws = ss.worksheet(tab_name)
    existing = ws.get_all_values()
    if not existing:
        # Empty tab — fall back to a plain append (ensure_headers will plant a
        # header row first when it ran before this).
        if rows_list:
            ws.append_rows(rows_list, value_input_option="USER_ENTERED")
        return len(rows_list)
    header = existing[0]
    keep = [r for r in existing[1:]
            if r and not (r[0] or "").startswith(today_prefix)]
    upsert_tab(ws, [header] + keep + rows_list)
    return len(rows_list)


def upsert_tab(
    ws: gspread.Worksheet,
    values: Sequence[Sequence[Any]],
    *,
    start: str = "A1",
    value_input_option: str = "USER_ENTERED",
) -> None:
    """
    ATOMIC full-tab overwrite. Drop-in replacement for the non-atomic idiom

        ws.clear()
        ws.update("A1", values, value_input_option=...)

    The clear()+update() pair is *not* atomic: a crash, network error, or 429
    rate-limit landing between the two calls leaves the tab EMPTY. For the
    trigger_alerts dedup ledgers that means every alert re-fires on the next
    run. This helper does the whole overwrite in a SINGLE write call, so the
    tab is never observably empty.

    Strategy
    --------
    The new `values` block is written at `start` in one `ws.update(...)`. If the
    tab previously held MORE rows than `values` has, the stale trailing rows are
    erased by padding `values` with blank rows (same width) up to the prior row
    count — that padding rides along in the SAME write. No standalone clear()
    that opens an empty window. Growing tabs just write the larger block.

    `value_input_option` and `start` mirror what the existing callers passed to
    `ws.update(...)` so semantics (RAW vs USER_ENTERED) are preserved exactly.

    Notes
    -----
    * `values` rows may be ragged; padding rows match the width of the widest
      written row so the trailing-cell blanking covers every previously-used
      column.
    * Empty `values` ([]) blanks the prior occupied range in one write (the
      faithful atomic analogue of clear() on a tab that only ever held data).
    """
    new_rows: List[List[Any]] = [list(r) for r in values]

    # Prior occupied row count: get_all_values() returns the populated range,
    # so its length is the number of rows currently holding data.
    try:
        prior_rows = len(ws.get_all_values())
    except Exception:
        prior_rows = 0

    # Width to use when blanking stale tail / prior data: widest row we will
    # write, falling back to the worksheet's declared column count so we cover
    # every previously-populated column even when shrinking to nothing.
    width = max((len(r) for r in new_rows), default=0)
    if width == 0:
        width = getattr(ws, "col_count", 0) or 1

    # Pad with blank rows so the single write also overwrites any stale tail
    # left from a previously-larger tab. Only pads DOWN (shrink case); growing
    # tabs already cover the prior range.
    if prior_rows > len(new_rows):
        blank = [""] * width
        new_rows.extend([list(blank) for _ in range(prior_rows - len(new_rows))])

    if not new_rows:
        # Nothing was ever there and nothing to write — no-op (avoids an empty
        # update payload, which the API rejects).
        return

    ws.update(new_rows, start, value_input_option=value_input_option)
