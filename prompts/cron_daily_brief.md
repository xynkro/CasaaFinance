# Daily Brief — Opus 4.7 Synthesis

You are running on a schedule (every weekday 07:00 SGT). Generate today's market brief and push it to the Sheets + Drive pipeline. **The PWA reads from the Sheet immediately after you finish.**

## Your job — 5 steps

### 1. Date & context

- Today is `$(date +%Y-%m-%d)` (use `date` Bash command to confirm).
- Yesterday SPX/NDX close already happened in US — search the news for it.
- US pre-market is happening RIGHT NOW (it's 07:00 SGT = 19:00 ET previous day, or 18:30 ET on weekdays after DST shift).

### 2. Gather data (read from Sheets)

Use the existing scripts to pull the latest state. **NEW** in this prompt:
the brain now reads three Finnhub-powered tabs (earnings_calendar,
economic_calendar, news_sentiment) + insider_transactions before doing
any web search. Web search becomes a SUPPLEMENT, not the primary source —
this is what makes the brief reliable instead of vibes.

```bash
cd /Users/xynkro/Documents/Trading/FinancePWA && source .venv/bin/activate
python3 -c "
from src.sync import load_env
from src import sheets as sh
import datetime
load_env()
client = sh.authenticate()
ss = sh._open_sheet(client)
today = datetime.date.today().isoformat()

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

# Today's earnings — companies reporting BMO/AMC/DMH today (filter our tickers only)
ec = ss.worksheet('earnings_calendar').get_all_values()
print('TODAY EARNINGS:')
for r in ec[1:]:
    if r and r[0] == today:
        print(f'  {r[1]:6} {r[2]} eps_est={r[5]} eps_act={r[6]} surprise%={r[9]}')

# Earnings within 7 days — flag any portfolio ticker with ER inside option DTE
print('EARNINGS NEXT 7 DAYS:')
end_7d = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
for r in ec[1:]:
    if r and today <= r[0] <= end_7d:
        print(f'  {r[0]} {r[1]:6} {r[2]} (est {r[5]})')

# Today's macro events (medium+high impact only)
ec2 = ss.worksheet('economic_calendar').get_all_values()
print('TODAY MACRO:')
for r in ec2[1:]:
    if r and r[0] == today:
        print(f'  {r[1]} {r[2]} [{r[4].upper():6}] {r[3]} (est {r[5]} prev {r[7]})')

# News sentiment — yesterday + today, flag any rows with score <= -0.4 (negative)
ns = ss.worksheet('news_sentiment').get_all_values()
print('NEGATIVE NEWS LAST 24H (sentiment <= -0.4):')
for r in ns[1:]:
    if r and r[1][:10] >= today and len(r) > 7:
        try:
            score = float(r[7])
            if score <= -0.4:
                print(f'  {r[1]} {r[2]:6} score={score:+.2f} {r[3][:80]}')
        except ValueError:
            pass

# Insider unusual activity — last 7 days, |value| > \$1M
import datetime as dt
seven_d = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
it = ss.worksheet('insider_transactions').get_all_values()
print('INSIDER LAST 7 DAYS (|value| > \$1M):')
for r in it[1:]:
    if r and len(r) > 9 and r[1] >= seven_d:
        try:
            value = float(r[9] or 0)
            if abs(value) > 1_000_000:
                print(f'  {r[1]} {r[3]:6} {r[7]:8} sh={r[5]:>10} @${r[8]} value=${value:>12,.0f} ({r[4]})')
        except ValueError:
            pass
"
```

### 3. Web research — supplement only

The Finnhub tabs above already provide structured data. Use `WebSearch`
to fill in the **narrative gaps** the structured data can't carry:

- US market close color (was the move broad-based or narrow leadership?)
- Geopolitics that move markets: Iran, China, Russia, OPEC (rarely in
  the macro calendar but matters)
- Commodity moves >2% if not already implied by macro (oil, gold,
  silver, copper)
- Any narrative theme that explains today's tape

**Do NOT** web-search for:
- Earnings dates (already in earnings_calendar)
- CPI/NFP/FOMC dates (already in economic_calendar)
- Insider buying/selling (already in insider_transactions)
- Per-ticker headlines (already in news_sentiment)

Search queries to fire (mix and match based on date):
- `"SPX today" close OR "S&P 500 today close" {today}`
- `Asia close Hang Seng Nikkei {today}`
- `oil price today move`
- `US 10-year yield today`

### 4. Synthesize — output as JSON

Apply the trading rules from `src/trading_rules.py`:
- Use `regime_max_leverage()` to gauge if current book is over-leveraged
- Cross-reference position triggers (TQQQ $52, SSO $60) — flag if breached
- Note CSP/CC roll candidates (delta hit thresholds)

Produce a JSON object matching the daily brief schema. NEW fields
`earnings_today`, `macro_today`, `negative_news`, `insider_alert` carry
the Finnhub-derived structured data so the PWA can render them as
distinct chips.

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
  "key_takeaways":      ["bullet 1", "bullet 2", "bullet 3"],
  "earnings_today":     ["NVDA AMC est $1.79", "WIX BMO est $1.26"],
  "earnings_next_7d":   ["MDT 6/3 AMC", "..."],
  "macro_today":        ["13:30 US CPI MoM est 0.3%", "Fed Cook 09:45 ET"],
  "negative_news":      ["BYND -0.7 'Restructuring talks fail'", "..."],
  "insider_alert":      ["NVDA Huang sold 50k @ $213 = $10.6M", "..."]
}
```

**Synthesis principles:**
- Be concise. The PWA card shows headline + 3 bullets.
- Be opinionated where you have evidence. Don't hedge ("could be either way") — pick a side.
- Tag each non-trivial claim with confidence implicitly (e.g. "likely", "decisively", "preliminary").
- The `watch_bullets` should be RULE-BASED triggers (price levels, RSI thresholds), not vibes.
- The new structured fields (`earnings_today`, `macro_today`, etc.) should
  be **terse one-liners** the PWA renders as chips — don't repeat them in
  the prose bullets above.
- `negative_news` should ONLY include items where (a) ticker is a
  current portfolio holding OR active decision_queue entry AND (b)
  sentiment_score ≤ -0.4. This filters noise.
- `insider_alert` should ONLY include filings >$1M absolute value in last
  7 days for portfolio + watchlist tickers. Heavy insider BUYING (side=buy)
  is a bullish flag; heavy SELLING is a yellow flag.

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
