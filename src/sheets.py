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
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List

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
