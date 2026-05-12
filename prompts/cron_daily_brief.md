# Daily Brief — Opus 4.7 Synthesis

You are running on a schedule (every weekday 07:00 SGT). Generate today's market brief and push it to the Sheets + Drive pipeline. **The PWA reads from the Sheet immediately after you finish.**

## Your job — 5 steps

### 1. Date & context

- Today is `$(TZ=Asia/Singapore date +%Y-%m-%d)` (use `TZ=Asia/Singapore date` to confirm — the runner is UTC, you need SGT).
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
import datetime, zoneinfo
load_env()
client = sh.authenticate()
ss = sh._open_sheet(client)
_sgt = zoneinfo.ZoneInfo('Asia/Singapore')
today = datetime.datetime.now(_sgt).strftime('%Y-%m-%d')

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
end_7d = (datetime.datetime.now(_sgt).date() + datetime.timedelta(days=7)).isoformat()
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
seven_d = (datetime.datetime.now(_sgt).date() - datetime.timedelta(days=7)).isoformat()
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

# Government Spending Confluence — ALL signals, not just high-scoring
# The brain decides what's actionable, not the rules engine.
print()
print('GOV CONFLUENCE ALL SIGNALS (brain decides, rules-score is advisory):')
try:
    gc = ss.worksheet('gov_confluence_signals').get_all_values()
    today_str = today
    gc_hdr = gc[0] if gc else []
    cols = {h: i for i, h in enumerate(gc_hdr)}
    today_signals = []
    for r in gc[1:]:
        if r and len(r) > cols.get('date', 0) and r[cols['date']] == today_str:
            today_signals.append(r)
    today_signals.sort(key=lambda r: float(r[cols['confluence_score']] or 0), reverse=True)
    for r in today_signals[:15]:
        score = r[cols['confluence_score']]
        tk = r[cols['ticker']]
        tier = r[cols['tier']] or '-'
        strat = r[cols['recommended_strategy']] or 'WATCH'
        thesis = r[cols['thesis_oneliner']]
        action = r[cols['recommended_action']]
        contract_usd = r[cols.get('contract_dollars', len(r))] if 'contract_dollars' in cols and cols['contract_dollars'] < len(r) else ''
        congress_usd = r[cols.get('congress_dollars', len(r))] if 'congress_dollars' in cols and cols['congress_dollars'] < len(r) else ''
        print(f'  {tk:6} score={score:>5} tier={tier:1} strat={strat:10} contracts=${contract_usd} congress=${congress_usd} | {thesis} | {action[:80]}')
    if not today_signals:
        print('  (no signals today)')
except Exception as e:
    print(f'  (gov_confluence_signals not available: {e})')

# Recent Capitol Trades (Congress filings) — last 3 days
print()
print('CAPITOL TRADES (filings last 3 days, top by amount):')
try:
    ct = ss.worksheet('congress_trades').get_all_values()
    three_d = (datetime.datetime.now(_sgt).date() - datetime.timedelta(days=3)).isoformat()
    ct_hdr = ct[0] if ct else []
    ct_cols = {h: i for i, h in enumerate(ct_hdr)}
    recent = []
    for r in ct[1:]:
        if r and len(r) > ct_cols.get('filing_date', 0):
            if r[ct_cols['filing_date']][:10] >= three_d:
                try:
                    amt_max = float(r[ct_cols['amount_max']] or 0)
                except ValueError:
                    amt_max = 0
                recent.append((amt_max, r))
    recent.sort(key=lambda x: -x[0])
    for amt_max, r in recent[:8]:
        pol = r[ct_cols['politician_name']][:22]
        party = r[ct_cols['party']][:1]
        chamber = r[ct_cols['chamber']][:5]
        tk = r[ct_cols['ticker']]
        ttype = r[ct_cols['transaction_type']]
        amt_min = float(r[ct_cols['amount_min']] or 0)
        print(f'  {pol:22} ({party}-{chamber:5}) {tk:6} {ttype:5} \${amt_min/1e3:>5.0f}K-\${amt_max/1e3:>6.0f}K')
    if not recent:
        print('  (no filings in last 3 days)')
except Exception as e:
    print(f'  (congress_trades not available: {e})')
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
  "insider_alert":      ["NVDA Huang sold 50k @ $213 = $10.6M", "..."],
  "gov_confluence":     ["AVAV score 87 Tier-A → BUY_DIP — $35M Army contract + Pelosi $250-500K + CFO $180K", "..."]
}
```

**`gov_confluence` field guidance** — YOU are the decision-maker, not the
rules engine. The `gov_confluence_signals` tab shows ALL scored signals
(the rules-based score is advisory context, not a filter). Read every
signal and decide independently what's actionable based on:
  - Contract $ size relative to company revenue (a $50M contract is huge
    for a $2B company, irrelevant for MSFT)
  - Congress trade patterns (cluster buys by multiple politicians >
    single filing)
  - Insider buying conviction (CEO/CFO buys > director sales)
  - Technical setup (is the stock at support? breaking out? overbought?)
  - Macro context (earnings imminent? FOMC blackout? sector rotation?)

For each signal you deem noteworthy (regardless of rules-score), format:
  `<TICKER> score <N> → <YOUR_STRATEGY> — <your reasoning>`

Your strategy options: BUY_DIP, LONG_CALL, PMCC, CSP, WATCH, SKIP
You are NOT limited to Tier A/B. A score-25 signal with a compelling
thesis is worth more than a score-70 signal in a broken chart.

Include up to 5 picks. If ALL signals are genuinely uninteresting, say so
with a brief reason ("all defense primes, no edge vs priced-in").

**IMPORTANT**: Gov confluence is ONE indicator among many — not a standalone
decision. When you write to `decision_queue`, your thesis MUST blend
gov data with the full indicator stack:
  - Technical: RSI, SMA50/200, EMA, %K/%D stochastics, price action
  - Fundamental: P/E, EBITDA, revenue growth, analyst consensus
  - Volatility: WVF (Williams VIX Fix), IV rank, HV30
  - Gov/insider: contract size, Congress trades, insider buys (from
    gov_confluence_signals)

A good thesis: "AVAV BUY_DIP — $35M Army drone IDIQ (5% rev), RSI 42
at SMA50 support, Congress cluster buy (Pelosi+Scott), P/E 28 vs
sector 35. Entry $215 dip."

A BAD thesis: "Congress sells: $0.02M from 2 politicians/30d" ← this
is worthless without technicals. Never write gov-only thesis.

To update `decision_queue`, use `push_decisions.py` (pass JSON via stdin)
or modify existing rows via Bash:
```bash
python -c "
from src.sync import load_env; from src import sheets as sh
load_env(); client = sh.authenticate(); ss = sh._open_sheet(client)
ws = ss.worksheet('decision_queue')
rows = ws.get_all_values()
hdr = rows[0]
# ... locate row by source+date+ticker, update strategy/status fields
"
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
