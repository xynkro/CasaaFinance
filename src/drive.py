"""
Google Drive upload helper — piggybacks on the same OAuth token as sheets.py.

Public API:
  upload_pdf(local_path, folder_id=None, name=None) -> file_id
  upload_file(local_path, folder_id=None, name=None, mime_type=None) -> file_id
"""
from __future__ import annotations

import mimetypes
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


def _drive_service():
    """
    Build a Drive v3 service using the same gspread-compatible OAuth token.
    Avoids pydrive2's oauth2client format requirement.
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    _, token_cache = _paths()
    if not token_cache.exists():
        raise RuntimeError(
            f"OAuth token missing at {token_cache}. Run sheets.authenticate() first."
        )

    creds = Credentials.from_authorized_user_file(str(token_cache), SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def upload_file(
    local_path: str | Path,
    folder_id: Optional[str] = None,
    name: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> str:
    """
    Generic file upload — works for .md, .pdf, .txt, etc. Returns Drive file ID.
    Updates existing file with same name rather than creating a duplicate.

    Uses google-api-python-client directly (compatible with gspread's OAuth
    token format, unlike pydrive2 which needs oauth2client-style creds).
    """
    from googleapiclient.http import MediaFileUpload

    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(local_path)

    folder_id = folder_id or os.environ.get("DRIVE_FOLDER_ID")
    if not folder_id:
        raise RuntimeError("DRIVE_FOLDER_ID not set in environment")

    svc = _drive_service()
    name = name or local_path.name

    # Infer MIME type — .md treated as text/markdown so Drive previews properly
    if not mime_type:
        if local_path.suffix.lower() == ".md":
            mime_type = "text/markdown"
        else:
            mime_type, _ = mimetypes.guess_type(str(local_path))
            if not mime_type:
                mime_type = "application/octet-stream"

    # Check for existing file with same name in the folder
    query = (
        f"'{folder_id}' in parents and name='{name}' "
        f"and trashed=false"
    )
    existing = svc.files().list(
        q=query, fields="files(id,name)", pageSize=1
    ).execute().get("files", [])

    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=False)

    if existing:
        file_id = existing[0]["id"]
        svc.files().update(fileId=file_id, media_body=media).execute()
        return file_id

    body = {"name": name, "parents": [folder_id], "mimeType": mime_type}
    created = svc.files().create(body=body, media_body=media, fields="id").execute()
    return created["id"]
