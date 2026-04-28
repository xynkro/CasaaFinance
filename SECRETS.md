# GitHub Secrets Setup

The cloud-native pipeline replaces all Mac LaunchAgents with GitHub Actions.
For these workflows to authenticate, you need to add **4 repository secrets**
at <https://github.com/xynkro/CasaaFinance/settings/secrets/actions>.

---

## Required Secrets

| Secret Name | What It Is | How to Get It |
|---|---|---|
| `ANTHROPIC_API_KEY` | API key for the brain (Opus 4.7 + Sonnet 4.6) | <https://console.anthropic.com/settings/keys> → Create Key |
| `SHEET_ID` | Google Sheets ID (the long alphanumeric in your sheet URL) | Open your sheet → URL is `docs.google.com/spreadsheets/d/{SHEET_ID}/edit` |
| `DRIVE_FOLDER_ID` | Root Drive folder ID (parent of `Daily Briefs/`, `WSR Lite/`, etc.) | Open the folder in Drive → URL is `drive.google.com/drive/folders/{ID}` |
| `OAUTH_TOKEN_JSON` | Full JSON of your cached OAuth user creds | See **OAUTH_TOKEN_JSON setup** below |

### Optional repository **variables** (not secrets, just config)

These let you bump model versions without redeploying. Set them at
*Settings → Secrets and variables → Actions → Variables tab*:

| Variable | Default | Purpose |
|---|---|---|
| `MODEL_OPUS` | `claude-opus-4-7` | Synthesis model |
| `MODEL_SONNET` | `claude-sonnet-4-6` | Formatting model |

If unset, the workflows use the defaults above.

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
| `market-scan.yml` | Daily 10:33 | Options screener across LunarCrush + WSB + quality watchlist |
| `poll-drive-wsr.yml` | :13, :43 every hour | Pick up any .md you upload manually to Drive |

---

## Cost estimate (per month, all workflows running)

| Service | Usage | Cost |
|---|---|---|
| GitHub Actions (public repo) | Unlimited | **$0** |
| Anthropic API — daily briefs | ~22 × $0.15 | **~$3.30** |
| Anthropic API — WSR Lite (×2/wk) | ~9 × $0.30 | **~$2.70** |
| Anthropic API — WSR Full (×1/wk) | ~4 × $1.20 | **~$4.80** |
| Google Sheets/Drive | Within free tier | **$0** |
| **Total** | | **~$11/month** |

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
