# Daily Brief — Opus 4.7 Synthesis

You are running on a schedule (every weekday 07:00 SGT). Generate today's market brief and push it to the Sheets + Drive pipeline. **The PWA reads from the Sheet immediately after you finish.**

## Your job — 5 steps

### 1. Date & context

- Today is `$(date +%Y-%m-%d)` (use `date` Bash command to confirm).
- Yesterday SPX/NDX close already happened in US — search the news for it.
- US pre-market is happening RIGHT NOW (it's 07:00 SGT = 19:00 ET previous day, or 18:30 ET on weekdays after DST shift).

### 2. Gather data (read from Sheets)

Use the existing scripts to pull the latest state:

```bash
cd /Users/xynkro/Documents/Trading/FinancePWA && source .venv/bin/activate
python3 -c "
from src.sync import load_env
from src import sheets as sh
load_env()
client = sh.authenticate()
ss = sh._open_sheet(client)

# Latest macro
macro = ss.worksheet('macro').get_all_values()[-1]
print('MACRO:', macro)

# Latest snapshots
for tab in ('snapshot_caspar', 'snapshot_sarah'):
    rows = ss.worksheet(tab).get_all_values()
    if len(rows) > 1:
        print(f'{tab}:', rows[-1])

# Latest positions
for tab in ('positions_caspar', 'positions_sarah'):
    rows = ss.worksheet(tab).get_all_values()
    if rows:
        latest_date = max(r[0] for r in rows[1:] if r and r[0])
        latest = [r for r in rows[1:] if r[0] == latest_date]
        print(f'{tab}: {len(latest)} rows on {latest_date}')
        for r in latest:
            print(f'  {r[1]} qty={r[2]} last={r[4]} upl={r[6]}')
"
```

### 3. Web research — overnight news

Use `WebSearch` to gather:
- US market close (yesterday): SPX, Nasdaq, Russell 2000 — direction, % change, internals
- Major after-hours earnings (top 10 by mkt cap)
- Asia session today: Nikkei, Hang Seng, STI directions
- Europe pre-market (futures)
- Major macro: any Fed speakers, CPI/jobs/PMI prints in the last 24h
- Geopolitics that move markets: Iran, China, Russia, OPEC
- Commodity moves >2%: oil, gold, silver, copper

Search queries to fire (mix and match based on date):
- `"SPX today" close OR "S&P 500 today close" {today}`
- `"after hours earnings" major beat miss {yesterday}`
- `Fed speaker today {today}`
- `oil price today move`
- `US 10-year yield today`

### 4. Synthesize — output as JSON

Apply the trading rules from `src/trading_rules.py`:
- Use `regime_max_leverage()` to gauge if current book is over-leveraged
- Cross-reference position triggers (TQQQ $52, SSO $60) — flag if breached
- Note CSP/CC roll candidates (delta hit thresholds)

Produce a JSON object matching the daily brief schema:

```json
{
  "type": "daily",
  "date": "YYYY-MM-DD",
  "headline": "one-line summary capturing today's dominant theme",
  "sentiment": "bullish|bearish|neutral",
  "regime": "bull_late_cycle|...",
  "verdict": "trader-facing one-liner: what to do today",
  "overnight_bullets":  ["...", "..."],
  "premarket_bullets":  ["..."],
  "catalysts_bullets":  ["..."],
  "commodities_bullets":["..."],
  "posture_change":     "string or empty",
  "watch_bullets":      ["TQQQ $52+ = trim trigger live", "..."],
  "key_takeaways":      ["bullet 1", "bullet 2", "bullet 3"]
}
```

**Synthesis principles:**
- Be concise. The PWA card shows headline + 3 bullets.
- Be opinionated where you have evidence. Don't hedge ("could be either way") — pick a side.
- Tag each non-trivial claim with confidence implicitly (e.g. "likely", "decisively", "preliminary").
- The `watch_bullets` should be RULE-BASED triggers (price levels, RSI thresholds), not vibes.

### 5. Format and push

**Step 5a — Sonnet formats the JSON to markdown:**

Use the Agent tool with `model: "sonnet"`:

```
Agent({
  description: "Format daily brief JSON to markdown",
  subagent_type: "general-purpose",
  model: "sonnet",
  prompt: <contents of prompts/sonnet_format_daily.md> + "\n\n```json\n" + <your JSON> + "\n```"
})
```

The subagent returns the markdown. Capture it.

**Step 5b — combine and push:**

Build the final payload (JSON + raw_md from Sonnet):

```python
payload = {
  ...your_json_synthesis,
  "raw_md": <markdown from sonnet>,
}
```

Save to `/tmp/brief_payload.json` and run:

```bash
python3 scripts/push_brief.py --json-file /tmp/brief_payload.json
rm /tmp/brief_payload.json
```

Verify the script printed `"ok": true`. If not, retry once with the same payload.

## Cost discipline

- Your Opus output should be COMPACT. ~300-500 tokens of synthesis JSON, max.
- Sonnet does the prose expansion. Don't pre-write the markdown yourself.
- Total Opus turns: aim for ≤ 8 (1 to read instructions, 2-3 for data gathering, 1-2 for web search synthesis, 1 to write JSON, 1 to invoke Sonnet, 1 to push).

## Failure modes — handle these

- **Markets closed (US holiday)**: produce a brief anyway, but `headline: "US markets closed today — {holiday name}"` and skip overnight/premarket bullets.
- **Web search returns thin / nothing**: still synthesize from sheets data + macro. Note the gap in the brief.
- **Push fails**: retry once. If it still fails, log the JSON to `.state/failed_briefs/{date}.json` for manual recovery.

## Done when

- `daily_brief_latest` sheet has a row dated today
- `Daily Briefs/` Drive folder has `{YYYYMMDD}_DailyBrief.md`
- The PWA Daily tab will show your brief within 15 minutes (auto-refresh interval).
