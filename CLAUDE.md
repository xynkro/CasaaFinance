# CasaaFinance (repo dir: FinancePWA)

Caspar's personal portfolio / personal-finance app for himself + Sarah. Two halves in one repo: a **Python sync/data layer** (`src/`, `scripts/`) that grabs portfolio + market data and writes a **Google Sheet** (`PORTFOLIO_DASHBOARD`, the hand-editable source of truth), archives WSR PDFs to **Google Drive**, and pings **Telegram** (`@Tron_shaft_bot`); and a **Vite + React 19 + TypeScript PWA** (`pwa/`) deployed to GitHub Pages at `/CasaaFinance/` that reads those tabs from a private Firestore mirror behind Google sign-in. Most workflows run as **GitHub Actions cron jobs** (`.github/workflows/`) plus local `launchd` agents (`com.caspar.*.plist`). The single most important thing: this touches real brokerage/portfolio data — see Hard rules before running anything that connects out.

## Hard rules — never break these
- **Never commit or expose secrets.** Real values live in `.env`, `.config/client_secret.json`, `.state/*.json` — all gitignored. `*.example` files list key NAMES only. Never echo a secret into code, logs, or commits.
- **IBKR access is READ-ONLY and must stay that way.** `src/ibkr_grab.py` (ib_insync to local TWS/Gateway) and `ibkr-flex-sync` only pull positions/summary. There is zero order-placement code against IBKR — do not add any.
- **Alpaca is PAPER-ONLY, hard-guarded.** `src/alpaca.py` / `scripts/alpaca_paper_execute.py` can place orders but refuse any non-`paper-api` base URL and default to dry-run. Never remove the paper guard or point it at a live endpoint. (Note: this paper account is shared with the ZeroDTE project — its `casaa-*` orders are this app's; don't let ZeroDTE touch them and vice-versa.)

## How we work here
- **Python sync/run:** `source .venv/bin/activate` then `python src/sync.py {auth|daily|wsr|dryrun}` (deps in `requirements.txt`). Test with `pytest` (`tests/conftest.py`).
- **PWA dev/build:** from `pwa/` — `npm run dev` (Vite), `npm run build` (`tsc -b && vite build`), `npm run lint`. Deploy via `.github/workflows/deploy.yml`.
- **Conventions:** Python stdlib + `requests` over heavy SDKs; secrets via `os.environ` only. PWA reads data through `pwa/src/data/transport.ts` (Firestore) — don't hardcode new fetch URLs elsewhere.
- **Done means:** `pytest` green for Python changes; `npm run build` clean for PWA changes; never claim a sync works without a `dryrun` against a fixture first.

## Architecture — only what isn't obvious from the code
- `src/sync.py` — CLI entry for the Sheet/Drive/Telegram sinks (subcommands `auth`/`daily`/`wsr`/`dryrun`; exit 0 OK, 1 partial, 2 fatal).
- `scripts/mirror_to_firestore.py` — copies Sheet tabs into private Firestore docs every 15 min; **inert until `FIREBASE_SERVICE_ACCOUNT_JSON` is set**, so safe to ship before Firebase setup. `firestore.rules` enforces an email allowlist and blocks all client writes.
- The Sheet (`SHEET_ID` in `.env` and `transport.ts`) is the source of truth; the PWA never writes back. The backend and PWA do NOT talk over HTTP — they communicate indirectly through the Sheet (+ optional Firestore mirror). 

## Anti-patterns — things that have gone wrong here
- Don't read portfolio data via the Sheet's gviz CSV URL — that originally leaked holdings to anyone who view-sourced the bundle; the Firestore mirror + Auth allowlist exists to close that. The PWA's gviz and PIN paths are gone: don't bring them back.
- The repo and its Actions logs are PUBLIC: no holdings, account values or names of tickers held, in code, docs or log lines.

## When unsure
- Read `README.md`, `src/sync.py`, and `pwa/src/data/transport.ts` first.
- Default to read-only / dry-run / paper; never place a real-money order, and ask before touching auth, secrets, or the paper/IBKR guards.
