"""Read-only Gmail client — refresh token → access token → Gmail REST.

Raw `requests` against the Gmail REST API; no `google-api-python-client`, no new
runtime dependency (the one-time consent helper in
`scripts/gmail_oauth_setup.py` is the only thing that needs google-auth-oauthlib,
and that's setup-only — it never runs in the cron).

The whole module is a **no-op when `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` /
`GMAIL_REFRESH_TOKEN` are unset** — `_access_token()` returns `None`, and every
public call short-circuits to an empty result. Exactly like `fetch_newsdata()`
without `NEWSDATA_API_KEY`: committing this changes nothing until Caspar pastes
the token into CI secrets + `.env`.

Scope is `gmail.readonly` only (the scope the token was minted with). This
module cannot send mail and never writes. Every network call is wrapped so a
hiccup is isolated — bad token / API blip → empty result + a logged warning,
never an exception that could take down the 10-min cron.
"""
from __future__ import annotations

import base64
import logging
import os

import requests

log = logging.getLogger(__name__)

_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


def _access_token() -> str | None:
    """Exchange the refresh token for a short-lived access token.

    Returns `None` (no log) when any of the three GMAIL_* vars is unset — the
    inert path. On a real failure (network / bad creds) logs a warning and
    returns `None` so callers degrade to empty results.
    """
    client_id = os.environ.get("GMAIL_CLIENT_ID")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET")
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        return None
    try:
        r = requests.post(
            _OAUTH_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        r.raise_for_status()
        return (r.json() or {}).get("access_token")
    except Exception as e:  # noqa: BLE001 — isolated, cron-safe
        log.warning("Gmail token refresh failed: %s", e)
        return None


def search(query: str, max_results: int = 20) -> list[str]:
    """List message ids matching a Gmail search query (`users.messages.list`).

    No token (inert) or any failure → `[]`. The Gmail query language is the same
    as the Gmail search box, e.g. `from:news.bloomberg.com newer_than:1d`.
    """
    token = _access_token()
    if token is None:
        return []
    try:
        r = requests.get(
            f"{_GMAIL_API}/messages",
            params={"q": query, "maxResults": max_results},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        r.raise_for_status()
        messages = (r.json() or {}).get("messages") or []
        return [m["id"] for m in messages if m.get("id")]
    except Exception as e:  # noqa: BLE001
        log.warning("Gmail search failed: %s", e)
        return []


def _header(headers: list[dict], name: str) -> str:
    """Case-insensitive lookup of a single header value from a payload's
    `headers` list (each entry `{"name": ..., "value": ...}`)."""
    target = name.lower()
    for h in headers or []:
        if str(h.get("name", "")).lower() == target:
            return str(h.get("value", "") or "")
    return ""


def _decode_b64url(data: str) -> str:
    """Decode a Gmail base64url `body.data` blob to text. Gmail omits padding,
    so pad to a multiple of 4 before decoding. Lossy-decode as UTF-8."""
    if not data:
        return ""
    try:
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode(
            "utf-8", errors="replace"
        )
    except Exception:  # noqa: BLE001 — never let one bad part raise
        return ""


def _first_plaintext(payload: dict) -> str:
    """Walk a message payload tree and return the first `text/plain` part's
    decoded body. Handles both single-part bodies and nested multipart MIME
    (recurses through `payload.parts`)."""
    if not payload:
        return ""
    mime = str(payload.get("mimeType", "") or "")
    body = payload.get("body") or {}
    if mime == "text/plain" and body.get("data"):
        text = _decode_b64url(body["data"])
        if text:
            return text
    for part in payload.get("parts") or []:
        text = _first_plaintext(part)
        if text:
            return text
    return ""


def get_message(msg_id: str) -> dict:
    """Fetch a full message and extract the bits we care about.

    Returns `{"id", "subject", "sender", "date", "plaintext"}`. No token (inert)
    or any failure → `{}`. `subject`/`sender`/`date` come from the payload
    headers; `plaintext` is the first text/plain part decoded from base64url.
    """
    token = _access_token()
    if token is None:
        return {}
    try:
        r = requests.get(
            f"{_GMAIL_API}/messages/{msg_id}",
            params={"format": "full"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        r.raise_for_status()
        msg = r.json() or {}
        payload = msg.get("payload") or {}
        headers = payload.get("headers") or []
        return {
            "id": msg.get("id", msg_id),
            "subject": _header(headers, "Subject"),
            "sender": _header(headers, "From"),
            "date": _header(headers, "Date"),
            "plaintext": _first_plaintext(payload),
        }
    except Exception as e:  # noqa: BLE001
        log.warning("Gmail get_message %s failed: %s", msg_id, e)
        return {}
