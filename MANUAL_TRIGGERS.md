# Manual Triggers — Run Routines on Demand

All cloud workflows can be triggered manually via the GitHub Actions UI or
`gh` CLI. Use these when you want to refresh data immediately rather than
waiting for the next scheduled fire.

---

## Quick reference (gh CLI from your Mac)

| What you want | Command |
|---|---|
| Refresh BOTH portfolios (yahoo prices) | `gh workflow run yahoo-grab.yml -R xynkro/CasaaFinance` |
| **Grab Caspar's portfolio** | `gh workflow run yahoo-grab.yml -R xynkro/CasaaFinance -f caspar_only=true` |
| **Grab Sarah's portfolio** | `gh workflow run yahoo-grab.yml -R xynkro/CasaaFinance -f sarah_only=true` |
| Refresh macro (VIX/SPX/DXY/10Y/SGD) + options prices | `gh workflow run macro-grab.yml -R xynkro/CasaaFinance` |
| Generate today's daily brief NOW | `gh workflow run daily-brief.yml -R xynkro/CasaaFinance -f dry=false` |
| Generate WSR Lite NOW | `gh workflow run wsr-lite.yml -R xynkro/CasaaFinance -f dry=false` |
| Generate WSR Monday NOW | `gh workflow run wsr-full.yml -R xynkro/CasaaFinance -f dry=false` |
| Pick up new WSR/Lite uploads in Drive | `gh workflow run poll-drive-wsr.yml -R xynkro/CasaaFinance` |
| Run market scan for fresh option recommendations | `gh workflow run market-scan.yml -R xynkro/CasaaFinance` |

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

| Workflow | Schedule (SGT) | Cron (UTC) |
|---|---|---|
| yahoo-grab | Hourly :07 | `7 * * * *` |
| macro-grab + options-refresh | Hourly :17 | `17 * * * *` |
| poll-drive-wsr | :13 + :43 hourly | `13,43 * * * *` |
| market-scan | Daily 10:33 | `33 2 * * *` |
| daily-brief | Mon-Fri 07:03 | `3 23 * * 0-4` |
| wsr-lite | Wed/Fri 19:33 | `33 11 * * 3,5` |
| wsr-full | Sun 19:37 | `37 11 * * 0` |
