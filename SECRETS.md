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
