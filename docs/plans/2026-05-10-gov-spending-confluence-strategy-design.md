# Government Spending Confluence Strategy — Design

Date: 2026-05-10
Status: Approved (sections 1–7) by Caspar
Implementation: in-progress, see `2026-05-10-gov-spending-confluence-strategy-plan.md`

## Goal

Catch tradeable US government spending catalysts before they hit mainstream
financial news, using free public data (USAspending.gov + CapitolTrades.com)
combined with existing Finnhub insider data. Output flows into the daily
brief, weekly strategy reviews, and a new Telegram "Insider Trading" topic
with concrete buy / sell / options recommendations.

## Non-Goals

- **Real-time intraday signals.** v1 is daily-batch. Faster cadence is a
  follow-up if signal quality validates.
- **QuiverQuant API integration.** $300/yr SaaS — we replicate the strategy
  shape with free sources.
- **Per-ping LLM cost.** No Anthropic API spend. Brain layer (daily brief +
  WSR) runs free under Caspar's existing Claude Code Max OAuth.
- **Long-tail recipient coverage.** Manual map covers top 200 contractors
  (~85% of dollar volume). Sub-$5M one-off awards to small private vendors
  fall through.
- **Trading non-US-listed names.** SGX and OTC names are out of scope —
  USAspending is US-only and CapitolTrades is US Congress only.

## Background — what was researched

### USAspending.gov (`api.usaspending.gov`)
Free public REST API operated by Treasury. Open-source backend at
`fedspendingtransparency/usaspending-api`. Endpoints we'll use:
- `POST /api/v2/search/spending_by_award` — filter awards by date / agency /
  type / amount, returns paginated rows with full recipient + contract
  metadata.
- `POST /api/v2/search/transactions` — modification history for a given
  award (used selectively).

No API key required. Soft rate-limits (we'll batch by date and stay well
under). Raw recipient data has no ticker mapping — that's the gap our
manual map fills.

### QuiverQuant strategies (`quiverquant.com/strategies`)
Reviewed leaderboard of 35+ backtested strategies. Relevant data points for
calibration:

| Strategy | All-time | CAGR | Sharpe |
|---|---|---|---|
| Top Gov Contract Recipients | 1,510% | 17.5% | 0.69 |
| Lobbying Spending Growth | 5,626% | 26.5% | 0.86 |
| Sector Weighted DC Insider | 233% | 21.8% | 0.89 |
| Congress Buys | 588% | 37.2% | 1.11 |
| Nancy Pelosi (mirror) | 912% | 21.3% | 0.74 |

Key takeaway: their best gov-contract strategy (passive long on top
recipients) just tracks the defense complex. The real edge is in
**acceleration / change** (Lobbying Spending Growth) and
**multi-signal confluence** (Sector Weighted DC Insider). Quiver does
**not** ship a "Contract Award Catalyst" strategy — that's the gap.

### CapitolTrades (`capitoltrades.com`)
Free scraping target. Pages render server-side (verified via firecrawl).
STOCK Act mandates Congressional disclosures within 45 days; observed lag is
**7–30 days post-trade**. Trade amounts disclosed as ranges (`$1M–$5M`,
`$500K–$1M`, etc.). Implication: Congress trades are a **lagging confluence
signal**, useful as confirmation but never as the primary trigger.

## Decisions locked in

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Trade horizon | Hybrid A+B (3–10 day momentum + 2–6 week swing) | Matches existing swing book |
| 2 | Confluence depth | v2.0 (contracts + insider + Congress) | Full QuiverQuant-shape stack |
| 3 | Ticker mapping | Option 1 — manual seed table | Highest precision, zero API cost |
| 4 | Cadence | Daily | Batch fits brief integration; faster is later |
| 5 | Telegram | New "Insider Trading" topic, daily digest | Topic ID TBD when Caspar creates it |
| 6 | Action types | BUY_DIP / LONG_CALL / PMCC | Matches existing decision_queue schema |
| 7 | Threshold | Tier A ≥1% TTM revenue, Tier B ≥5% multi-year | Catches material moves, ignores noise |

## Architecture

```
USAspending API ─────► fetch_gov_contracts (06:00 SGT) ─┐
CapitolTrades scrape ─► fetch_congress_trades (06:30)   │
Finnhub insider (existing) ────────────────────────────┤
                                                        ▼
                          ┌─────────────────────────────┐
                          │ recipient_ticker_map (Sheet)│
                          │ + gov_unmapped_recipients   │
                          └──────────────┬──────────────┘
                                         ▼
                    screen_gov_confluence (07:00 SGT, daily)
                                         │
                contract·40% + congress·30% + insider·30% → 0–100
                                         │
                          ┌──────────────┴───────────────┐
                          ▼                              ▼
              gov_confluence_signals             telegram digest
              (sheet, brain reads)               (07:15 SGT)
                          │                              │
              ┌───────────┴────────────┐                 ▼
              ▼                        ▼          📢 "Insider Trading"
        daily_brief                WSR Lite/Full     topic in Finance &
        (07:43 SGT, brain          (existing crons,   Trading supergroup
         narrates + may upgrade    add new section)
         strategy recommendation)
                          │
                          ▼
                   decision_queue
                   (BUY_DIP / LONG_CALL / PMCC
                    with strike/expiry/delta/premium)
```

## Components

### 1. Data layer

Three new sheets + one mapping table. Existing `insider_transactions`
(Finnhub feed) is consumed read-only.

#### `gov_contracts`
One row per (award_id, modification). Daily snapshot fetched from
USAspending. Source: `POST /api/v2/search/spending_by_award` with filter on
yesterday's `action_date` and `award_type_codes` covering Contracts (`A`,
`B`, `C`, `D`) and IDVs (`IDV_A`–`IDV_E`).

| Column | Description |
|---|---|
| `audit_ts` | SGT-anchored, audit timestamp |
| `award_id` | Primary key from USAspending |
| `action_date` | When the contract was awarded |
| `recipient_name` | Raw, normalized to UPPER |
| `parent_recipient_name` | Rolls up subsidiaries |
| `ticker` | Resolved via mapping table; empty if unmapped |
| `award_amount` | `federal_action_obligation` USD |
| `tcv` | Total contract value (multi-year sum) |
| `agency` | e.g. "DEPT OF THE NAVY" |
| `naics_code` + `naics_description` | Sector |
| `period_start` / `period_end` | Multi-year flag derived from delta |
| `place_of_performance_state` | Geographic |
| `description` | Truncated 200 chars |

#### `congress_trades`
One row per filing. Daily scrape of CapitolTrades `/trades?txnTo=<yesterday>`.
1 req/sec rate-limit, paginated until reaching dates already seen.

| Column | Description |
|---|---|
| `audit_ts`, `filing_id` | Audit + primary key |
| `politician_id`, `politician_name` | e.g. P000197 / Nancy Pelosi |
| `party`, `chamber` | "D"/"R" / "House"/"Senate" |
| `committees` | JSON array of committee names |
| `ticker`, `issuer_name` | Mapped + raw |
| `transaction_date`, `filing_date` | Filing lag = days between |
| `transaction_type` | "buy" / "sell" |
| `amount_min`, `amount_max` | `$1M–$5M` → 1000000 / 5000000 |

#### `recipient_ticker_map`
Manual seed sheet. Initial seed: top ~150 contractors covering ~85% of
dollar volume, including parent-subsidiary mappings (e.g. "LOCKHEED MARTIN
AERONAUTICS COMPANY" → LMT). Bake into a one-shot
`scripts/init_recipient_map.py` Caspar runs once.

| Column | Description |
|---|---|
| `recipient_name_normalized` | UPPER, punctuation-stripped, sorted |
| `parent_ticker` | The publicly-traded parent's ticker |
| `confidence` | "high" / "medium" / "low" |
| `notes` | Free text — provenance, edge cases |

Sibling sheet **`gov_unmapped_recipients`** auto-populated by the screener
when it sees a `recipient_name` not in the map AND `award_amount ≥ $5M`.
Caspar reviews weekly and adds to the map or ignores.

#### `gov_confluence_signals`
Output of the daily screener. Read by daily-brief brain. One row per
(date, ticker) where the signal fired (score ≥ 60).

| Column | Description |
|---|---|
| `date`, `ticker` | Composite key |
| `confluence_score` | 0–100 |
| `contract_score` / `congress_score` / `insider_score` | Sub-components |
| `tier` | "A" or "B" |
| `recommended_strategy` | "BUY_DIP" / "LONG_CALL" / "PMCC" |
| `recommended_action` | One-line text for Telegram |
| `thesis_oneliner` | One-line trade thesis |
| `contributing_contracts` | JSON array of award_ids |
| `contributing_congress_trades` | JSON array of filing_ids |
| `contributing_insider_buys` | JSON array of insider transaction ids |

### 2. Mapping layer

**Normalization**: `_normalize_recipient(s) = s.upper().translate(strip_punct).split()` → sorted set
of words → joined string. Handles "Lockheed Martin Corporation" vs
"LOCKHEED MARTIN CORP." vs "LOCKHEED-MARTIN, CORPORATION" → all normalize
to the same key `"CORP CORPORATION LOCKHEED MARTIN"` (after sort) — well,
actually we don't sort, we just strip punct + spaces normalization. Use:
```
def normalize(s): return re.sub(r'[^A-Z0-9]+', '', s.upper())
```
"LOCKHEEDMARTINCORPORATION", "LOCKHEEDMARTINCORP" — these don't match. So
we need a fuzzy approach. Use **token set ratio** via Python's `difflib`:
- Strip punctuation, uppercase
- Split into tokens, drop common suffixes (`CORP`, `INC`, `LLC`, `LTD`,
  `CO`, `COMPANY`, `CORPORATION`, `LP`, `THE`)
- Sort tokens, join → key
- Lookup as exact match first; if miss, use `difflib.get_close_matches`
  with ratio ≥ 0.85

Map sheet uses the post-normalization key as the lookup column.

**Initial seed list (~150 entries)**: top contractors by FY2024 obligations,
including subsidiaries:
- Defense majors: LMT, RTX, NOC, GD, BA, LHX, HII, KBR, CACI, LDOS, BWXT,
  TDG, BAH, SAIC
- Defense small/mid: AVAV, KTOS, MRCY, CW, HEI, TGI, RGR, AJRD (now LHX-owned),
  PLTR
- Cloud / IT services with gov contracts: ORCL, MSFT, AMZN, GOOGL, ACN,
  IBM, CTSH, HPE, DXC, CSCO, T (AT&T)
- Healthcare / pharma: HUM, MCK, CAH, CNC, BMY, JNJ, PFE
- Industrial / energy: GE, HON, MMM, EMR, CAT, DE, F (Ford gov vehicles)

**Unmapped flagging**: when screener encounters `recipient_name` not in
map with award ≥ $5M, append to `gov_unmapped_recipients` for weekly review.

### 3. Confluence scoring (40 / 30 / 30)

Per-ticker score for the most recent N=30 days of activity. All
sub-components clipped to 0–100 then weighted.

#### Contract score (40% weight)

```
single_contract_impact_pct = max(award_amount in last 30d) / TTM_revenue
rolling_impact_pct = sum(award_amount in last 30d) / TTM_revenue

base_score = 100 * (rolling_impact_pct / 0.20)        # 20%+ → 100
base_score = clip(base_score, 0, 100)

multi_year_bonus = 15 if any contract is multi-year (period > 365d) else 0
recency_bonus = 10 if any contract in last 7d else 0
sector_bonus = 5 if NAICS ∈ {541512, 541330, 336411, 541715, 928110}
              # IT/engineering/aerospace mfg/R&D/national security

contract_score = clip(base_score + multi_year_bonus + recency_bonus + sector_bonus, 0, 100)
```

`TTM_revenue` is sourced from existing `wsr_full` brain runs (we already
maintain financial fundamentals per ticker) or fallback to a Finnhub
basic-financials call. If unavailable, default to 0 contract score and
fire only if Congress + insider signals are exceptional.

#### Congress score (30% weight)

```
recent_buys = filter(congress_trades,
                     ticker = X,
                     filing_date >= today - 60 days,
                     transaction_type = "buy")

# Use midpoint of disclosed range
amount_total = sum( (amount_min + amount_max) / 2 for trade in recent_buys )

# Committee relevance: trades by politicians on relevant committees count more
# Defense-focused committees:
#   House Armed Services, Senate Armed Services, House Appropriations
#   (Defense subcommittee), Senate Appropriations, Intelligence committees
# General relevance:
#   Energy & Commerce, Financial Services, Ways & Means

committee_weight = 1.0 if politician on relevant committee for ticker's sector
                 = 0.6 otherwise

weighted_amount = sum(midpoint * committee_weight)

# Score: $250K total weighted = 50, $1M = 100
congress_score = clip(weighted_amount / 10000, 0, 100)
                 # 10000 chosen so $1M weighted = score 100

# Recency: extra +20 if any trade in last 14 days (still fresh news)
if any trade.filing_date >= today - 14 days:
    congress_score += 20
    congress_score = clip(congress_score, 0, 100)
```

#### Insider score (30% weight)

```
recent_buys = filter(insider_transactions,
                     ticker = X,
                     transaction_date >= today - 90 days,
                     transaction_code = "P")  # P = open-market purchase

# Role weighting from insider_transactions.officer_title
role_weight = {
    "CEO": 1.0, "CFO": 1.0, "President": 0.9, "COO": 0.8,
    "EVP" / "SVP": 0.7,
    "Director": 0.6,
    "10% Owner": 0.7,
    "Other": 0.4,
}

weighted_value = sum(transaction_value * role_weight)

# Score: $500K weighted = 50, $2M = 100
insider_score = clip(weighted_value / 20000, 0, 100)

# Cluster bonus: +20 if 3+ insiders bought in same 30-day window
if cluster_count >= 3:
    insider_score = clip(insider_score + 20, 0, 100)
```

#### Final confluence score

```
confluence_score = (
    0.40 * contract_score +
    0.30 * congress_score +
    0.30 * insider_score
)
```

#### Tier assignment

```
tier_A: confluence_score >= 70 AND contract_impact_pct >= 1.0%
tier_B: confluence_score >= 80 AND any_contract_multi_year AND contract_impact_pct >= 5.0%
```

### 4. Action recommendation rules (rules-based, brain may override)

| Score | Strategy | Spec |
|---|---|---|
| 70–79 + Tier A | `BUY_DIP` | Cash buy. Position sized at 1% NLV. |
| 80–89 | `LONG_CALL` | 0.50Δ, 30–45 DTE, position sized at 0.5% NLV in premium |
| 90+ | `LONG_CALL` (default) or `PMCC` | 0.60Δ for LONG_CALL; PMCC if IV rank > 60 to capture skew |
| Pure Congress sells | flag for brain review | No auto-sell — politicians sell for unrelated reasons |

LONG_CALL strike/expiry are computed at signal time using yfinance option
chains (already used in `market_scan.py`). The brain can override the
strategy choice during daily-brief generation if it spots signals the rules
miss (high IV → switch to PMCC; earnings within 7d → downgrade to wait;
clear technical breakdown → skip entirely).

### 5. Decision queue extension

Existing `decision_queue` schema already supports `LONG_CALL`, `LONG_PUT`,
`PMCC` strategy types with `strike`, `expiry`, `premium_per_share`,
`delta`, `cash_required` fields. No schema change needed.

The screener appends rows to `decision_queue` with:
- `status = "watching"`
- `source = "gov_confluence"`
- `strategy` set per recommendation rules above
- `thesis_1liner` set from `recommended_action`
- `thesis_confidence` set from `confluence_score / 100`
- `entry`, `target`, options fields populated

The daily brief brain may modify these (status → "act_now", strategy →
different type, thesis enriched).

The existing `trigger_alerts` evaluator handles BUY_DIP price-cross alerts.
For LONG_CALL we don't need a price-cross — signal generation IS the entry
trigger. So `trigger_alerts.py` will treat `strategy=LONG_CALL` rows as
"alert at signal write time, then mark as alerted" rather than waiting for
a price match.

### 6. Telegram routing — new "Insider Trading" topic

**Setup**: Caspar creates the topic manually in the Finance & Trading
supergroup. We discover the thread ID via `getUpdates` after he posts the
first message in it, the same flow used for Multi Day Swing (3) and Macro
News (6). Until ID is known, code uses `INSIDER_TRADING_TOPIC = None` and
the digest workflow is a no-op (graceful skip).

**Daily digest at 07:15 SGT** (after screener, before daily brief). Single
message format:

```
📊 INSIDER PULSE · 2026-05-09

🎯 CONFLUENCE PICKS (top 3)

1. AVAV — score 87 · Tier A
   $35M Army drone contract (5-yr IDIQ, 8.2% of TTM rev)
   + Pelosi bought 250K-500K filed 5d ago
   + CFO bought $180K open-market (90d)
   → 🟢 BUY_DIP @ $215 OR LONG_CALL Jun20 $230 ($4.20 premium, 0.50Δ)

2. PLTR — score 79 · Tier A
   $40M USSOCOM AI contract
   + 2 directors bought $400K total (45d)
   → 🟢 BUY_DIP @ $19 (1% NLV)

3. ...

🏛 CAPITOL TRADES (top 3 by amount)

• Pelosi → AVAV BUY $250K-500K (filed yesterday)
• Mullin → LMT BUY $50K-100K
• ...

⚠ UNMAPPED RECIPIENTS (review)
  · "BAE SYSTEMS LAND & ARMAMENTS L P" — $87M — likely BAE / BAESY
```

**Why not multiple pings**: with daily cadence, batching into one digest
is cleaner than spamming the topic with 5–10 separate pings at 07:15 SGT.
If we go faster cadence in v2, we'd switch to per-event pings.

### 7. Brain integration

#### Daily brief (`prompts/cron_daily_brief.md`)
New section "**Government & Insider Pulse**" inserted between the macro
read and the swing-book section. Brain prompt extended to:
- Read `gov_confluence_signals` for today
- Read `gov_contracts` for context (top contracts in last 7d)
- Read `congress_trades` for fresh filings
- Narrate the top 3 confluence signals with editorial perspective
- Possibly **override** the rules-based strategy (e.g. "rules say LONG_CALL
  but I'd skip — earnings in 4 days").

The brain's edits write back to `decision_queue` (status: `watching` →
`act_now` for high-conviction picks).

#### WSR Lite (`prompts/cron_wsr_lite.md`)
New section "**Confluence Leaderboard**" — top 5 by 7-day rolling
confluence score. Brief commentary on which sectors the data is pointing
at this week.

#### WSR Full (`prompts/cron_wsr_full.md`)
New deep-dive section. Brain picks 1–3 highest-confluence names from the
week, writes full thesis (catalyst, comparables, position sizing, options
chain analysis, exit criteria). Goes into the WSR markdown that lands in
Drive + the wsr_summary sheet.

## Cron schedule

| Time (SGT) | Workflow | Job |
|---|---|---|
| 06:00 Mon–Fri | `fetch-gov-contracts.yml` | Pull yesterday's USAspending awards |
| 06:30 Mon–Fri | `fetch-congress-trades.yml` | Scrape CapitolTrades new filings |
| 07:00 Mon–Fri | `screen-gov-confluence.yml` | Score + write `gov_confluence_signals` + append to `decision_queue` |
| 07:15 Mon–Fri | `insider-pulse-digest.yml` | Send daily Telegram digest |
| 07:43 Mon–Fri | `daily-brief.yml` (existing) | Brain reads gov data, narrates |
| Sunday 06:00 | `wsr-lite.yml` (existing) | Adds Confluence Leaderboard |
| Sunday 12:00 | `wsr-full.yml` (existing) | Adds Confluence Deep Dive |

## Implementation phases

**Phase 1 (this PR — autonomous overnight build)**
- Schemas added to `src/schema.py`
- `src/usaspending.py` + `scripts/fetch_gov_contracts.py`
- `src/capitoltrades.py` + `scripts/fetch_congress_trades.py`
- `scripts/init_recipient_map.py` (one-shot seed of ~150 entries)
- `src/recipient_ticker.py` (resolver with fuzzy fallback)
- `scripts/screen_gov_confluence.py`
- `src/telegram.py` extended with `ping_insider_pulse()` + topic constant
- `scripts/insider_pulse_digest.py`
- 4 new GitHub Actions workflows
- Brain prompt updates (daily, WSR Lite, WSR Full)

**Phase 2 (next session)**
- PWA card showing confluence signals
- Backtest harness against historical data
- Real-time pings (4h cadence) once signal quality validates

**Phase 3 (future)**
- Lobbying spend acceleration as 4th confluence signal (free SEC LD-2)
- Cross-reference with options unusual activity
- Sector ETF momentum overlay (XLDEF for defense, etc.)

## Testing strategy

- **USAspending fetcher**: live smoke-test against the public API. Verify
  we get yesterday's contracts. No assertions on count (varies day-to-day).
- **CapitolTrades scraper**: live smoke-test. Verify parser handles the
  Pelosi page (known shape).
- **Recipient resolver**: unit-test against ~30 known mappings (LMT
  variants, Boeing aerospace subsidiaries, etc.).
- **Screener scoring**: synthetic-data unit tests for each sub-component
  + integration test for combined formula.
- **Telegram digest**: use existing `--dry` flag pattern from
  `trigger_alerts.py` to render the message without sending.
- **Workflows**: `workflow_dispatch` triggers for manual runs.

## Open questions / future work

1. **TTM revenue source**: Currently planned to read from existing brain
   runs. If gaps exist, fall back to Finnhub basic-financials. May need a
   small `revenue_cache` sheet.
2. **Fuzzy matching threshold (0.85)** may need tuning. Track false
   positive rate via the `gov_unmapped_recipients` review.
3. **Position sizing**: defaults are 1% NLV (BUY_DIP) and 0.5% NLV in
   premium (LONG_CALL). Brain may adjust per signal.
4. **Cross-listing handling**: BAESY / BAE Systems as ADR vs primary
   listing on LSE. For now treat ADR as the primary mapping.
5. **Earnings proximity gate**: hard filter at 14d. Could relax to 7d if
   we see strategies miss good signals near earnings.
