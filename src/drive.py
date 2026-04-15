"""
Google Drive upload helper — piggybacks on the same OAuth token as sheets.py.

Public API:
  upload_pdf(local_path, folder_id=None, name=None) -> file_id
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .sheets import _paths, SCOPES  # reuse token cache + scopes


def _auth():
    # Lazy import so `sync.py daily` (which doesn't touch Drive) doesn't pay the
    # pydrive2 import cost and isn't blocked by transitive OpenSSL breakage on
    # some systems.
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive

    client_secret, token_cache = _paths()
    gauth = GoogleAuth()
    # Configure pydrive2 to use the same cached OAuth token gspread writes.
    gauth.settings["client_config_backend"] = "file"
    gauth.settings["client_config_file"] = str(client_secret)
    gauth.settings["save_credentials"] = True
    gauth.settings["save_credentials_backend"] = "file"
    gauth.settings["save_credentials_file"] = str(token_cache)
    gauth.settings["get_refresh_token"] = True
    gauth.settings["oauth_scope"] = SCOPES

    # gspread wrote the token in its own format. Rather than share, force pydrive2
    # to load fresh via LoadCredentialsFile and fall back to refresh if needed.
    try:
        gauth.LoadCredentialsFile(str(token_cache))
    except Exception:
        pass

    if gauth.credentials is None:
        # No cached creds — trigger browser consent (should be rare since
        # sync.py auth primes the token first).
        gauth.LocalWebserverAuth()
    elif gauth.access_token_expired:
        gauth.Refresh()
    else:
        gauth.Authorize()

    return GoogleDrive(gauth)


def upload_pdf(local_path: str | Path, folder_id: Optional[str] = None, name: Optional[str] = None) -> str:
    """
    Upload a PDF to the configured Drive folder. Returns Drive file ID.

    If a file with the same name already exists in the folder, creates a new
    version rather than a duplicate.
    """
    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(local_path)

    folder_id = folder_id or os.environ.get("DRIVE_FOLDER_ID")
    if not folder_id:
        raise RuntimeError("DRIVE_FOLDER_ID not set in environment")

    drive = _auth()
    name = name or local_path.name

    # Look for an existing file with the same name in the folder
    query = f"'{folder_id}' in parents and title='{name}' and trashed=false"
    existing = drive.ListFile({"q": query}).GetList()

    if existing:
        # Update in place (new revision)
        f = existing[0]
        f.SetContentFile(str(local_path))
        f.Upload()
        return f["id"]

    f = drive.CreateFile({
        "title": name,
        "parents": [{"id": folder_id}],
        "mimeType": "application/pdf",
    })
    f.SetContentFile(str(local_path))
    f.Upload()
    return f["id"]
