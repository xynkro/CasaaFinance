#!/usr/bin/env python3
"""One-time Gmail OAuth setup — YOU run this locally, click "Allow" once, and it
prints the three values to paste into CI secrets + .env. Read-only scope.

This script does NOT touch the repo's secrets and stores nothing — it just walks
you through Google's consent and prints the refresh token to your terminal.

Prereq (one-time, ~10 min in Google Cloud Console — see
docs/runbooks/setup-gmail-oauth.md):
  1. Create a project, enable the Gmail API.
  2. Configure the OAuth consent screen (External, add yourself as a test user).
  3. Create an OAuth client of type "Desktop app", download client_secret.json.

Then:
  .venv/bin/python scripts/gmail_oauth_setup.py /path/to/client_secret.json

It opens your browser → you pick your account → "Allow" (read-only Gmail) →
the terminal prints GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN.
"""
from __future__ import annotations

import sys

# Read-only. Cannot send mail, cannot read Drive/Calendar.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main() -> int:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Missing dependency. Install the setup-only library first:\n"
              "  .venv/bin/pip install google-auth-oauthlib", file=sys.stderr)
        return 1

    if len(sys.argv) < 2:
        print("Usage: python scripts/gmail_oauth_setup.py /path/to/client_secret.json",
              file=sys.stderr)
        return 2

    client_secret = sys.argv[1]
    flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
    # Spins up a localhost redirect, opens your browser. You click "Allow".
    creds = flow.run_local_server(port=0, prompt="consent")

    if not creds.refresh_token:
        print("\nNo refresh token returned. Re-run — Google only returns one on the\n"
              "first consent. Revoke prior access at https://myaccount.google.com/permissions\n"
              "then run again (the prompt='consent' flag should force it).", file=sys.stderr)
        return 3

    print("\n" + "=" * 64)
    print("Paste these into CI secrets AND your local .env (NEVER commit them):")
    print("=" * 64)
    print(f"GMAIL_CLIENT_ID={creds.client_id}")
    print(f"GMAIL_CLIENT_SECRET={creds.client_secret}")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print("=" * 64)
    print("Done. Read-only Gmail access. Revoke anytime at "
          "https://myaccount.google.com/permissions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
