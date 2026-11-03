# FinancePWA

Phone-first portfolio dashboard for Caspar + Sarah. Wraps the Daily News Brief + Weekly Strategy Review outputs into a PWA surface accessible from iPhone home screen.

## Architecture

```
GitHub Actions jobs (started by a timer on the GCP VM, deploy/vm/)
  ├─ scanners, portfolio sync, paper executor, daily ideas
  ├─ Google Sheet PORTFOLIO_DASHBOARD (hand-editable source of truth)
  ├─ Telegram DM + topic pings
  └─ scripts/mirror_to_firestore.py (every 15 min)
       └─ private Firestore docs (allowlist, no client writes)
            └─ PWA on GitHub Pages, behind Google sign-in
```

The Python jobs and the PWA never talk directly: they meet at the Sheet and its
Firestore mirror. Plan for the mirror: `docs/plans/2026-06-07-private-read-path-plan.md`.
Setup: `docs/runbooks/setup-firebase.md`.

## Repo layout

```
FinancePWA/
├── src/            Shared Python: sinks, schema, scoring, ideas
├── scripts/        Job entry points, one per workflow
├── pwa/            Vite + React PWA
├── prompts/        Prompts the brief and weekly review jobs run
├── vendor/skills/  Vendored regime and screener skills
├── deploy/vm/      Job starter for the GCP VM
├── docs/           Runbooks and pre-registered trial gates
├── fixtures/       Synthetic inputs for dryrun and tests
├── .config/        OAuth client secret (gitignored)
└── .state/         OAuth token cache and local logs (gitignored)
```

## Setup

```bash
cd "~/Documents/Trading/FinancePWA"

# 1. Create venv
python3 -m venv .venv
source .venv/bin/activate

# 2. Install deps
pip install gspread pydrive2 python-dotenv requests

# 3. Configure
cp .env.example .env
# Edit .env — fill TELEGRAM_BOT_TOKEN, confirm other values

# 4. Place OAuth client secret
cp ~/Downloads/client_secret_*.json .config/client_secret.json

# 5. First-time OAuth consent
python src/sync.py auth

# 6. Dry-run against fixture (no real data written)
python src/sync.py dryrun --fixture fixtures/daily_sample.json

# 7. Real run from within Daily/WSR workflow
python src/sync.py daily --json <brief.json> --md <brief.md>
python src/sync.py wsr --ledger <ledger.json> --md <wsr.md> --pdf <wsr.pdf>
```

## CLI reference

| Subcommand | Purpose |
|---|---|
| `auth` | One-time OAuth browser consent. Caches refresh token. |
| `daily` | Write `daily_brief_latest` + best-effort `macro` row from Daily Brief sidecar JSON. Modifies existing Telegram push text. |
| `wsr` | Write all WSR tabs + upload PDF to Drive + Telegram ping with PWA URL. |
| `dryrun` | Parse fixture, print what would be written. No network I/O. |

## Exit codes

- `0` — all sinks OK
- `1` — partial failure (stderr lists which)
- `2` — fatal (auth / unreadable input)

## Current status

- S0: complete
- **S1: in progress** ← you are here
- S2+: not started
