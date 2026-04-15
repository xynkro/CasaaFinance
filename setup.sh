#!/bin/bash
# FinancePWA — one-shot setup script.
# Usage: from Terminal, run:
#   cd "~/Documents/Trading/FinancePWA"
#   bash setup.sh
#
# This script:
#   1. Creates a Python 3 venv at .venv/
#   2. Installs required packages
#   3. Runs the OAuth consent flow (opens browser)
#   4. Executes two dryruns against bundled fixtures to verify plumbing
#
# Idempotent: safe to re-run. If .venv exists it is reused.

set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

echo "==> Working in: $HERE"

# 1. venv
if [ ! -d ".venv" ]; then
  echo "==> Creating Python venv..."
  python3 -m venv .venv
else
  echo "==> Reusing existing .venv"
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 2. deps
echo "==> Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet gspread pydrive2 python-dotenv requests

# 3. pre-flight checks
if [ ! -f ".config/client_secret.json" ]; then
  echo "!! Missing .config/client_secret.json — download OAuth Desktop client from GCP."
  exit 2
fi
if [ ! -f ".env" ]; then
  echo "!! Missing .env — copy .env.example and fill in TELEGRAM_BOT_TOKEN."
  exit 2
fi

# 4. dryrun (no network)
echo "==> Dryrun Daily..."
python src/sync.py dryrun --fixture fixtures/daily_sample.json --kind daily
echo ""
echo "==> Dryrun WSR..."
python src/sync.py dryrun --fixture fixtures/wsr_sample.json --kind wsr
echo ""

# 5. OAuth consent
echo "==> Running OAuth consent (browser will open)..."
echo "    If this is your first run, a Google consent screen will appear."
echo "    Approve the scopes, close the browser tab, return here."
python src/sync.py auth

echo ""
echo "==> Setup complete. Next steps:"
echo "    source .venv/bin/activate"
echo "    python src/sync.py daily --json fixtures/daily_sample.json"
echo "  ↑ this writes a REAL row to your Sheet + sends a REAL Telegram ping."
