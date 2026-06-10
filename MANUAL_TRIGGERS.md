# Manual Triggers — Run Routines on Demand

All cloud workflows can be triggered manually via the GitHub Actions UI or
`gh` CLI. Use these when you want to refresh data immediately rather than
waiting for the next scheduled fire.

## 🎯 Easiest path — Anthropic Routines

Open <https://claude.ai/code/routines> — 8 pre-built clickable buttons:

- 🟢 Grab Caspar's Portfolio  · 🟢 Grab Sarah's Portfolio  · 🟢 Grab Both Portfolios
- 🔵 Refresh Macro + Options Prices
- 🔭 Daily Options Scan (watchlist)
- 🧠 Generate Daily Brief NOW  · 🧠 Generate WSR Lite NOW  · 🧠 Generate WSR Full NOW

Tap "Run now" on any of them. They survive across sessions, work from
phone or desktop, and bypass the need to remember any commands.

---

## Quick reference (gh CLI from your Mac)

| What you want | Command |
|---|---|
| Refresh BOTH portfolios (yahoo prices) | `gh workflow run yahoo-grab.yml -R xynkro/CasaaFinance` |
| **Grab Caspar's portfolio** | `gh workflow run yahoo-grab.yml -R xynkro/CasaaFinance -f caspar_only=true` |
| **Grab Sarah's portfolio** | `gh workflow run yahoo-grab.yml -R xynkro/CasaaFinance -f sarah_only=true` |
| Refresh macro (VIX/SPX/DXY/10Y/SGD) + options prices | `gh workflow run macro-grab.yml -R xynkro/CasaaFinance` |
| Daily Options Scan (watchlist CSP/CC, no IBKR) | `gh workflow run daily-options-scan.yml -R xynkro/CasaaFinance` |
| Generate today's daily brief NOW | `gh workflow run daily-brief.yml -R xynkro/CasaaFinance -f dry=false` |
| Generate WSR Lite NOW | `gh workflow run wsr-lite.yml -R xynkro/CasaaFinance -f dry=false` |
| Generate WSR Monday NOW | `gh workflow run wsr-full.yml -R xynkro/CasaaFinance -f dry=false` |
| Pick up new WSR/Lite uploads in Drive | `gh workflow run poll-drive-wsr.yml -R xynkro/CasaaFinance` |
| Run market scan for fresh option recommendations | `gh workflow run market-scan.yml -R xynkro/CasaaFinance` |
| Mirror Sheet → Firestore (private read path) NOW | `gh workflow run mirror-firestore.yml -R xynkro/CasaaFinance` |

---

## GitHub Actions UI (clickable buttons)

If you'd rather click buttons than use CLI:
<https://github.com/xynkro/CasaaFinance/actions>

For each workflow on the left sidebar:
1. Click the workflow name
2. Click "Run workflow" dropdown (top right)
3. Set inputs (dry, caspar_only, etc.) → "Run workflow"

---

## When IBKR / TWS is running (Mac-only)

`yahoo-grab` only refreshes prices on KNOWN positions (qty + avg_cost from
the sheet). It can't discover new positions you opened in IBKR.

**To full-sync from IBKR** (when TWS is running on your Mac):

```bash
cd ~/Documents/Trading/FinancePWA
source .venv/bin/activate
python src/ibkr_grab.py
```

This pulls authoritative qty + avg_cost + open options from IBKR and
overwrites the sheet rows. Run it whenever you've opened/closed positions.

---

## Continuing tracking when IBKR is OFF

This is the default state. Without IBKR:

- ✅ **Hourly price refresh** on existing positions (yahoo-grab @ :07)
- ✅ **Hourly macro refresh** (macro-grab @ :17)
- ✅ **Hourly options refresh** on existing option positions (macro-grab @ :17)
- ❌ Cannot detect new positions you opened/closed since last IBKR sync

So the workflow is:
1. You trade in IBKR
2. Open TWS occasionally (e.g., Sunday evening before WSR Monday runs)
3. Run `python src/ibkr_grab.py` to authoritative-sync
4. Cloud workflows track hourly between IBKR syncs

---

## Cadence summary

SGT = UTC + 8. Minutes are deliberately **staggered** so no two
sheet-writing workflows fire on the same exact minute — concurrent writes to
the single Google Sheet trip Sheets API 429s. Keep offsets distinct when
adding/retiming a workflow (the `*/10` `trigger-alerts` spine occupies every
:00/:10/:20/:30/:40/:50 of 13:00-21:00 UTC on weekdays, so daily writers in
that window must avoid those ticks).

| Workflow | Schedule (SGT) | Cron (UTC) |
|---|---|---|
| yahoo-grab (+ tv_price_refresh) | Mon-Fri :07 & :37, 21:00-05:00 next day | `7,37 13-21 * * 1-5` |
| macro-grab | 4×/day :17 (08:17/14:17/22:17/06:17) | `17 0,6,14,22 * * *` |
| options-refresh | Mon-Fri :05 & :35, 21:00-05:30 next day | `5,35 13-21 * * 1-5` |
| trigger-alerts | Mon-Fri every 10 min, 21:00-05:00 next day | `*/10 13-21 * * 1-5` |
| poll-drive-wsr | Daily 14:08 / 20:08 / 02:08 | `8 6,12,18 * * *` |
| market-scan | Daily 10:15 | `15 2 * * *` |
| daily-options-scan | Mon-Fri 10:35 | `35 2 * * 1-5` |
| gex-regime | Mon-Fri 21:02 | `2 13 * * 1-5` |
| iv-surface-scan | Mon-Fri 22:38 (10:38 ET — live quotes) | `38 14 * * 1-5` |
| finnhub-calendars | Daily 21:06 | `6 13 * * *` |
| finnhub-news-insider | Daily 21:08 / 01:08 / 05:08 / 10:08 | `8 13,17,21,2 * * *` |
| build-daily-plan | Mon-Fri 22:03 | `3 14 * * 1-5` |
| alpaca-paper-execute | Mon-Fri 22:33 | `33 14 * * 1-5` |
| unusual-options-scan | Mon-Fri 22:36 | `36 14 * * 1-5` |
| execute-decisions | Mon-Fri 08:00 | `0 0 * * 1-5` |
| regime-signals (+ exposure-posture) | Mon-Fri 06:10 next day | `10 22 * * 1-5` |
| tv-signals | Mon-Fri 06:40 next day | `40 22 * * 1-5` |
| fetch-gov-contracts | Sun-Thu 06:00 next day | `0 22 * * 0-4` |
| fetch-congress-trades | Sun-Thu 06:30 next day | `30 22 * * 0-4` |
| refresh-exit-plans | Daily 06:20 next day | `20 22 * * *` |
| risk-parity-audit (+ recommend) | Mon-Fri 06:45 next day | `45 22 * * 1-5` |
| paper-benchmark | Mon-Fri 05:33 next day | `33 21 * * 1-5` |
| api-usage | Daily 07:30 next day | `30 23 * * *` |
| screen-gov-confluence | Sun-Thu 07:00 next day | `0 23 * * 0-4` |
| daily-brief | Sun-Thu 07:03 next day | `3 23 * * 0-4` |
| tail-hedge | Mon 07:15 next day | `15 23 * * 1` |
| growth-scan | Mon & Thu 20:30 | `30 12 * * 1,4` |
| screen-candidates | Sun 19:00 | `0 11 * * 0` |
| finnhub-analyst | Sun 20:02 | `2 12 * * 0` |
| options-yield | Sun 20:04 | `4 12 * * 0` |
| signal-feedback | Sun 22:00 | `0 14 * * 0` |
| wsr-lite | Wed 19:33 | `33 11 * * 3` |
| wsr-full | Sun 19:37 | `37 11 * * 0` |
| mirror-firestore | Every 15 min (Firestore, not the Sheet) | `*/15 * * * *` |
