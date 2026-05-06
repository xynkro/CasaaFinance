# GitHub Secrets Setup

The cloud-native pipeline replaces all Mac LaunchAgents with GitHub Actions.
For these workflows to authenticate, you need to add **4 repository secrets**
at <https://github.com/xynkro/CasaaFinance/settings/secrets/actions>.

---

## Required Secrets

| Secret Name | What It Is | How to Get It |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Long-lived OAuth token for your **Claude Max subscription** — flat-rate billing, no per-token API charges | Run `claude setup-token` in a regular Terminal (NOT inside Claude Code) |
| `SHEET_ID` | Google Sheets ID (the long alphanumeric in your sheet URL) | Open your sheet → URL is `docs.google.com/spreadsheets/d/{SHEET_ID}/edit` |
| `DRIVE_FOLDER_ID` | Root Drive folder ID (parent of `Daily Briefs/`, `WSR Lite/`, etc.) | Open the folder in Drive → URL is `drive.google.com/drive/folders/{ID}` |
| `OAUTH_TOKEN_JSON` | Full JSON of your cached Google OAuth user creds | See **OAUTH_TOKEN_JSON setup** below |

### CLAUDE_CODE_OAUTH_TOKEN setup (one-time, ~30 seconds)

```bash
# 1. In a fresh Terminal window — NOT inside an active Claude Code session:
claude setup-token

# 2. Follow the prompts (browser opens, sign in to your Max account, approve)
# 3. Copy the long-lived token it prints
# 4. Set as GitHub Secret:
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo xynkro/CasaaFinance
# (paste the token at the prompt)
```

This token authenticates the GitHub Actions runs against your Max
subscription. Cost: included in your existing Max plan — **$0 marginal cost
for the brain**.

---

## OAUTH_TOKEN_JSON setup (one-time)

Your local Mac already has `~/Documents/Trading/FinancePWA/.state/authorized_user.json`
from the first time you ran `python -m src.sheets authenticate`. The file contains
a refresh token Google honours indefinitely (as long as it's used at least once
every 6 months).

**To export it as a GitHub Secret:**

```bash
# 1. Print the contents
cat /Users/xynkro/Documents/Trading/FinancePWA/.state/authorized_user.json

# 2. Copy the entire output (a single JSON object — should look like
#    {"refresh_token": "1//...", "client_id": "...", "client_secret": "...", ...})

# 3. Go to https://github.com/xynkro/CasaaFinance/settings/secrets/actions
# 4. Click "New repository secret"
# 5. Name: OAUTH_TOKEN_JSON
# 6. Value: paste the entire JSON
# 7. Click "Add secret"
```

**Important:** The token includes both the refresh token AND the OAuth client
credentials. Treat it like a password.

---

## OPTIONAL: FMP API key for regime detection

The `regime-signals.yml` and `screen-candidates.yml` workflows wrap the
trader's quant skills (`ftd-detector`, `ibd-distribution-day-monitor`,
`macro-regime-detector`, `vcp-screener`, `canslim-screener`). All of these
need a Financial Modeling Prep API key for fundamentals + price history.

`market-breadth-analyzer` does NOT need FMP — it pulls TraderMonty's public
CSV. It will always run regardless.

**Until `FMP_API_KEY` is set, the FMP-gated skills are skipped gracefully** —
each one logs `skipped — no FMP key` and the workflow exits 0. No failures.

### To enable the FMP-gated skills

1. Sign up at <https://financialmodelingprep.com> (free tier: 250 calls/day —
   plenty for the daily regime cron + the weekly screener cron).
2. Add to your `~/.zshrc` (so `casaa exposure` etc. work locally):
   ```bash
   export FMP_API_KEY=your_key_here
   ```
3. Add as a GitHub Actions secret (so the cron jobs see it):
   ```bash
   gh secret set FMP_API_KEY --repo xynkro/CasaaFinance
   # paste key at the prompt
   ```

After this, the next scheduled `regime-signals` run will populate `ftd`,
`distribution_day`, and `macro_regime` rows in addition to `market_breadth`.

---

## TradingView MCP integration

The brain pipeline reads a daily TradingView 26-indicator consensus per
ticker × interval. No API key needed — `scripts/tv_signals_run.py` hits
the public scanner endpoint at `scanner.tradingview.com/america/scan`
which accepts batches of 20 symbols per call across 1d and 1W intervals.

- **What it writes:** one row per (ticker, interval) to the `tv_signals`
  sheet tab. Universe = active book (positions, options, decision_queue
  last 30d, scan_results last 7d, screen_candidates last 30d).
- **Schedule:** `tv-signals.yml`, daily 22:30 UTC = 06:30 SGT (Mon-Fri).
  Runs 30 min after `regime-signals.yml` so the WSR brain finds both
  signals fresh when it wakes up.
- **Throughput:** ~28 active tickers × 2 intervals = 56 rows in ~10s.
  Rate-limit handling: 0.5s sleep between batches; on HTTP 429 sleep
  60s and retry once. The scanner endpoint is much more lenient than
  the per-symbol library API which gets blocked aggressively.
- **Cost:** $0 (public endpoint, no key, no Claude action).
- **Manual trigger:** `casaa tv` from anywhere on the Mac.

The brain prompts (`prompts/cron_wsr_full.md`, `cron_wsr_lite.md`) have
been updated with explicit multi-timeframe confluence rules — TF
divergence flags, RSI extremes, and BUY_DIP gating that requires daily
TV in {BUY, STRONG_BUY} and weekly NOT in {SELL, STRONG_SELL}.

For pattern recognition vocabulary, see `prompts/swing_playbook.md` —
seven distilled swing-trading patterns the brain cites by name in
thesis prose (VCP, Pullback to 20EMA, Liquidity Sweep, Anchored VWAP,
Breakout Retest, Range Filter, MTF Confluence).

---

## Verify the secrets work

Once all 4 secrets are added, manually trigger any of the simple workflows:

1. <https://github.com/xynkro/CasaaFinance/actions/workflows/yahoo-grab.yml>
2. Click "Run workflow" → leave defaults → "Run workflow"
3. Watch the run — should complete in ~2 min and write fresh prices to your sheet

If it fails, the most likely issue is `OAUTH_TOKEN_JSON` — verify it's the full
file contents (not just the refresh_token portion).

---

## Cron schedule summary

All times shown in **SGT** (your local). GitHub crons run in UTC — see workflow
files for UTC values.

| Workflow | Schedule (SGT) | Purpose |
|---|---|---|
| `daily-brief.yml` | Mon-Fri 07:03 | Opus brain synthesises overnight news + position context |
| `wsr-lite.yml` | Wed/Fri 19:33 | Mid-week pulse (trigger audit + decision queue check) |
| `wsr-full.yml` | Sun 19:37 | Full Monday strategy review |
| `yahoo-grab.yml` | Hourly :07 | Live portfolio prices (no IBKR needed) |
| `macro-grab.yml` | Hourly :17 | Macro indicators (VIX/SPX/DXY) + simple options refresh |
| `options-refresh.yml` | Every 30min, US market hours (Mon-Fri 21:00-05:30 SGT) | Full options refresh: moneyness/DTE/assignment_risk/momentum/RSI/SMA/sigma — frees Mac from daily critical path |
| `market-scan.yml` | Daily 10:33 | Options screener across LunarCrush + WSB + quality watchlist |
| `poll-drive-wsr.yml` | :13, :43 every hour | Pick up any .md you upload manually to Drive |
| `regime-signals.yml` | Mon-Fri 22:00 UTC (06:00 SGT next day) | Regime indicators (breadth + ftd + dist-day + macro) → exposure posture |
| `screen-candidates.yml` | Sun 11:00 UTC (19:00 SGT) | Weekly fresh tickers (vcp + canslim) before WSR Full |
| `tv-signals.yml` | Mon-Fri 22:30 UTC (06:30 SGT next day) | TradingView 26-indicator consensus (1d + 1W) for active universe |

---

## Cost estimate (per month, all workflows running)

| Service | Usage | Cost |
|---|---|---|
| GitHub Actions (public repo) | Unlimited | **$0** |
| Claude Max subscription (brain) | All daily briefs + WSRs | **$0 marginal** (already paying for Max) |
| Google Sheets/Drive | Within free tier | **$0** |
| **Total marginal** | | **$0** |

The brain runs on your existing Max subscription via the official
`anthropics/claude-code-action@v1`. No per-token API billing.

---

## Decommission the old Mac LaunchAgents

After the GitHub Actions are running cleanly for 2-3 days, run this on your Mac
to retire the local schedulers:

```bash
launchctl unload ~/Library/LaunchAgents/com.caspar.brief-sync.plist
launchctl unload ~/Library/LaunchAgents/com.caspar.wsr-archive.plist
launchctl unload ~/Library/LaunchAgents/com.caspar.yahoo-grab.plist
launchctl unload ~/Library/LaunchAgents/com.caspar.market-scan.plist
launchctl unload ~/Library/LaunchAgents/com.caspar.daily-tracker.plist

# Optional: archive them
mkdir -p ~/Library/LaunchAgents.archived
mv ~/Library/LaunchAgents/com.caspar.*.plist ~/Library/LaunchAgents.archived/

# IBKR-grab can stay if you want bonus IBKR live data when TWS is on:
# (yahoo_grab via Actions covers when TWS is off)
```

After this point, **the Mac can be off and the entire pipeline keeps running.**
