# Government Spending Confluence Strategy — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship a daily-batch strategy that ingests USAspending contract awards + CapitolTrades Congress filings + existing Finnhub insider data, computes a per-ticker confluence score, surfaces top picks via a new "Insider Trading" Telegram topic + the daily/weekly briefs, and writes BUY_DIP / LONG_CALL / PMCC entries into `decision_queue`.

**Architecture:** Three-layer (data → score → brain+delivery). Daily cadence. Free public APIs only — no LLM API spend. Brain integration via existing daily-brief / WSR crons (free under Claude Code Max OAuth). See `2026-05-10-gov-spending-confluence-strategy-design.md`.

**Tech Stack:** Python 3.12 (matches existing FinancePWA cron pattern). `requests` for HTTP. `BeautifulSoup4` for CapitolTrades scraping (need to add to `requirements.txt`). `gspread` for Sheets I/O (already in deps). `difflib` stdlib for fuzzy recipient matching. GitHub Actions for cron scheduling.

---

### Task 1: Add new schemas to `src/schema.py`

**Files:**
- Modify: `src/schema.py` — append 5 new dataclasses

**Schemas to add:**

```python
@dataclass
class GovContractRow:
    """One row per (award_id, modification) pulled from USAspending."""
    TAB_NAME = "gov_contracts"
    HEADERS = [
        "audit_ts", "award_id", "action_date",
        "recipient_name", "parent_recipient_name", "ticker",
        "award_amount", "tcv",
        "agency", "naics_code", "naics_description",
        "period_start", "period_end",
        "place_of_performance_state",
        "description",
    ]

    audit_ts: str
    award_id: str
    action_date: str
    recipient_name: str
    parent_recipient_name: str
    ticker: str
    award_amount: float
    tcv: float
    agency: str
    naics_code: str
    naics_description: str
    period_start: str
    period_end: str
    place_of_performance_state: str
    description: str

    def to_row(self) -> List[str]:
        return [
            self.audit_ts, self.award_id, self.action_date,
            self.recipient_name, self.parent_recipient_name, self.ticker,
            _num(self.award_amount), _num(self.tcv),
            self.agency, self.naics_code, self.naics_description,
            self.period_start, self.period_end,
            self.place_of_performance_state,
            self.description[:200],
        ]


@dataclass
class CongressTradeRow:
    """One row per CapitolTrades filing."""
    TAB_NAME = "congress_trades"
    HEADERS = [
        "audit_ts", "filing_id",
        "politician_id", "politician_name", "party", "chamber",
        "committees",  # JSON array
        "ticker", "issuer_name",
        "transaction_date", "filing_date",
        "transaction_type",
        "amount_min", "amount_max",
    ]

    audit_ts: str
    filing_id: str
    politician_id: str
    politician_name: str
    party: str
    chamber: str
    committees: str  # JSON-encoded array
    ticker: str
    issuer_name: str
    transaction_date: str
    filing_date: str
    transaction_type: str
    amount_min: float
    amount_max: float

    def to_row(self) -> List[str]:
        return [
            self.audit_ts, self.filing_id,
            self.politician_id, self.politician_name, self.party, self.chamber,
            self.committees,
            self.ticker, self.issuer_name,
            self.transaction_date, self.filing_date,
            self.transaction_type,
            _num(self.amount_min), _num(self.amount_max),
        ]


@dataclass
class RecipientTickerMapRow:
    """Manual seed table: recipient name (normalized) -> publicly-traded ticker."""
    TAB_NAME = "recipient_ticker_map"
    HEADERS = [
        "recipient_name_normalized",  # primary key
        "recipient_name_raw",         # human-readable for review
        "parent_ticker",
        "confidence",                 # high | medium | low
        "notes",
        "updated_at",
    ]

    recipient_name_normalized: str
    recipient_name_raw: str
    parent_ticker: str
    confidence: str
    notes: str
    updated_at: str

    def to_row(self) -> List[str]:
        return [
            self.recipient_name_normalized, self.recipient_name_raw,
            self.parent_ticker, self.confidence, self.notes, self.updated_at,
        ]


@dataclass
class GovUnmappedRecipientRow:
    """Auto-flagged recipient names with award >= $5M not in the map."""
    TAB_NAME = "gov_unmapped_recipients"
    HEADERS = [
        "first_seen_ts", "recipient_name", "recipient_name_normalized",
        "total_award_amount", "contract_count", "biggest_award_id",
        "agency", "last_seen_ts",
    ]

    first_seen_ts: str
    recipient_name: str
    recipient_name_normalized: str
    total_award_amount: float
    contract_count: int
    biggest_award_id: str
    agency: str
    last_seen_ts: str

    def to_row(self) -> List[str]:
        return [
            self.first_seen_ts, self.recipient_name, self.recipient_name_normalized,
            _num(self.total_award_amount), str(self.contract_count),
            self.biggest_award_id, self.agency, self.last_seen_ts,
        ]


@dataclass
class GovConfluenceSignalRow:
    """Per-ticker daily output of the confluence screener."""
    TAB_NAME = "gov_confluence_signals"
    HEADERS = [
        "date", "ticker",
        "confluence_score",
        "contract_score", "congress_score", "insider_score",
        "tier",                              # "A" | "B" | ""
        "recommended_strategy",              # BUY_DIP | LONG_CALL | PMCC
        "recommended_action",
        "thesis_oneliner",
        "contributing_contracts",            # JSON array of award_ids
        "contributing_congress_trades",      # JSON array of filing_ids
        "contributing_insider_buys",         # JSON array of insider tx ids
        "updated_at",
    ]

    date: str
    ticker: str
    confluence_score: float
    contract_score: float
    congress_score: float
    insider_score: float
    tier: str
    recommended_strategy: str
    recommended_action: str
    thesis_oneliner: str
    contributing_contracts: str
    contributing_congress_trades: str
    contributing_insider_buys: str
    updated_at: str

    def to_row(self) -> List[str]:
        return [
            self.date, self.ticker,
            _num(self.confluence_score, 1),
            _num(self.contract_score, 1), _num(self.congress_score, 1), _num(self.insider_score, 1),
            self.tier, self.recommended_strategy, self.recommended_action,
            self.thesis_oneliner,
            self.contributing_contracts, self.contributing_congress_trades, self.contributing_insider_buys,
            self.updated_at,
        ]
```

**Verify:** `python3 -c "import ast; ast.parse(open('src/schema.py').read())"` exits 0.

**Commit:** `feat: gov confluence strategy schemas (5 new dataclasses)`

---

### Task 2: USAspending API client + fetch script

**Files:**
- Create: `src/usaspending.py` — API client
- Create: `scripts/fetch_gov_contracts.py` — daily cron entry
- Create: `.github/workflows/fetch-gov-contracts.yml`

**`src/usaspending.py`** — client wrapping `POST /api/v2/search/spending_by_award`:
- Function `fetch_awards(start_date, end_date, page_size=100, max_pages=20) -> list[dict]`
- `award_type_codes = ["A", "B", "C", "D", "IDV_A", "IDV_B", "IDV_C", "IDV_D", "IDV_E"]`
- Required `fields` array: `["Award ID", "Recipient Name", "Recipient UEI", "Award Amount", "Total Outlays", "Contract Award Type", "Action Date", "Awarding Agency", "Awarding Sub Agency", "NAICS", "NAICS Description", "Place of Performance State Code", "Description", "Start Date", "End Date", "recipient_id", "Last Modified Date"]`
- Returns normalized list of dicts
- Defensive: catches HTTP errors, retries 3× with exponential backoff
- Pagination: walks pages until empty results or `max_pages` hit

**`scripts/fetch_gov_contracts.py`**:
- Reads yesterday's date in SGT
- Calls `usaspending.fetch_awards(yesterday, yesterday)`
- Resolves `recipient_name` to ticker via `recipient_ticker.resolve()` (Task 8)
- Writes to `gov_contracts` sheet via `sh.append_rows()`
- `--dry` flag for local testing

**Workflow YAML**: cron `0 22 * * 1-5` (06:00 SGT Mon–Fri). Env: `OAUTH_TOKEN_JSON`, `SHEET_ID`. Steps: checkout, setup-python, pip install, run script.

**Smoke test:** `python scripts/fetch_gov_contracts.py --dry` should print yesterday's contracts without writing to Sheets.

**Commit:** `feat: USAspending API client + fetch_gov_contracts cron`

---

### Task 3: CapitolTrades scraper + fetch script

**Files:**
- Create: `src/capitoltrades.py` — HTML scraper
- Create: `scripts/fetch_congress_trades.py` — daily cron entry
- Create: `.github/workflows/fetch-congress-trades.yml`
- Modify: `requirements.txt` — add `beautifulsoup4==4.13.5`

**`src/capitoltrades.py`**:
- Function `fetch_recent_trades(since_date, max_pages=10) -> list[dict]`
- Scrapes `https://www.capitoltrades.com/trades` (lists all politician trades, paginated by `?page=N`)
- Parses table rows: politician (with id from URL), issuer + ticker, transaction_date, filing_date, transaction_type, amount range
- 1 req/sec rate limit (`time.sleep(1)` between page fetches)
- User-Agent: `"FinancePWA/1.0 (research)"`
- Stops paginating when a row's `filing_date` is older than `since_date`
- Returns list of normalized dicts ready for `CongressTradeRow`

**Amount parsing**: CapitolTrades displays buckets like `1K–15K`, `15K–50K`, `50K–100K`, `100K–250K`, `250K–500K`, `500K–1M`, `1M–5M`, `5M–25M`, `25M–50M`, `50M+`. Map to `(min, max)` numeric tuples.

**`scripts/fetch_congress_trades.py`**:
- Computes `since_date` as last filing_date in `congress_trades` sheet (or 14 days ago if empty)
- Calls scraper, dedupes against existing `filing_id`s
- Looks up politician committees from a static map (Task 9 will populate top ~50)
- Writes new rows
- `--dry` flag

**Workflow YAML**: cron `30 22 * * 1-5` (06:30 SGT). Same env as Task 2.

**Smoke test:** Scraper extracts at least 10 rows from page 1 of `/trades`.

**Commit:** `feat: CapitolTrades scraper + fetch_congress_trades cron`

---

### Task 4: Recipient → Ticker resolver + seed map

**Files:**
- Create: `src/recipient_ticker.py` — resolver with fuzzy fallback
- Create: `scripts/init_recipient_map.py` — one-shot to seed `recipient_ticker_map`

**`src/recipient_ticker.py`**:

```python
import re
import json
from difflib import get_close_matches
from functools import lru_cache

_PUNCT_RE = re.compile(r"[^A-Z0-9 ]+")
_SUFFIX_TOKENS = frozenset({
    "CORP", "CORPORATION", "INC", "INCORPORATED", "LLC", "LP", "LTD",
    "LIMITED", "CO", "COMPANY", "COMPANIES", "GROUP", "HOLDINGS",
    "HOLDING", "THE", "OF", "AND", "&",
    # Common gov-specific
    "L", "P", "PA", "USA",
})


def normalize(name: str) -> str:
    """Normalize a recipient name to a stable lookup key.

    Steps:
      1. Uppercase
      2. Strip punctuation (keep alphanumeric + spaces)
      3. Tokenize, drop common corporate suffixes
      4. Sort tokens (so "LOCKHEED MARTIN" == "MARTIN LOCKHEED")
      5. Join with single spaces
    """
    if not name:
        return ""
    upper = name.upper()
    cleaned = _PUNCT_RE.sub(" ", upper)
    tokens = [t for t in cleaned.split() if t and t not in _SUFFIX_TOKENS]
    return " ".join(sorted(tokens))


@lru_cache(maxsize=1)
def _load_map() -> dict[str, str]:
    """Load recipient_ticker_map from Sheet, returns {normalized: ticker}."""
    from src import sheets as sh
    from src import schema as S
    client = sh.authenticate()
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.RecipientTickerMapRow.TAB_NAME)
    except Exception:
        return {}
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {}
    hdr = rows[0]
    try:
        c_norm = hdr.index("recipient_name_normalized")
        c_tk = hdr.index("parent_ticker")
    except ValueError:
        return {}
    out = {}
    for r in rows[1:]:
        if len(r) > max(c_norm, c_tk) and r[c_norm] and r[c_tk]:
            out[r[c_norm]] = r[c_tk].upper()
    return out


def resolve(recipient_name: str, fuzzy: bool = True) -> str:
    """Returns ticker (uppercase) or empty string if not mapped.

    Tries exact normalized match first. If `fuzzy=True` and no exact hit,
    tries `difflib.get_close_matches` with cutoff 0.85.
    """
    if not recipient_name:
        return ""
    key = normalize(recipient_name)
    mapping = _load_map()
    if key in mapping:
        return mapping[key]
    if fuzzy:
        matches = get_close_matches(key, mapping.keys(), n=1, cutoff=0.85)
        if matches:
            return mapping[matches[0]]
    return ""
```

**`scripts/init_recipient_map.py`**: hard-coded list of ~150 entries seeded into the sheet. Sample (full list ~150 in actual file):

```python
# (raw_name, ticker, confidence, notes)
SEED_DATA = [
    # Defense majors
    ("LOCKHEED MARTIN CORPORATION", "LMT", "high", "parent"),
    ("LOCKHEED MARTIN AERONAUTICS COMPANY", "LMT", "high", "subsidiary"),
    ("LOCKHEED MARTIN MISSILES AND FIRE CONTROL", "LMT", "high", "subsidiary"),
    ("LOCKHEED MARTIN ROTARY AND MISSION SYSTEMS", "LMT", "high", "subsidiary"),
    ("LOCKHEED MARTIN SPACE", "LMT", "high", "subsidiary"),
    ("RTX CORPORATION", "RTX", "high", "parent (formerly Raytheon Technologies)"),
    ("RAYTHEON COMPANY", "RTX", "high", "subsidiary of RTX"),
    ("RAYTHEON MISSILES & DEFENSE", "RTX", "high", "subsidiary of RTX"),
    ("PRATT & WHITNEY", "RTX", "high", "subsidiary of RTX"),
    ("COLLINS AEROSPACE", "RTX", "high", "subsidiary of RTX"),
    ("NORTHROP GRUMMAN CORPORATION", "NOC", "high", "parent"),
    ("NORTHROP GRUMMAN SYSTEMS CORPORATION", "NOC", "high", "subsidiary"),
    ("NORTHROP GRUMMAN SPACE & MISSION SYSTEMS", "NOC", "high", "subsidiary"),
    ("GENERAL DYNAMICS CORPORATION", "GD", "high", "parent"),
    ("GENERAL DYNAMICS LAND SYSTEMS", "GD", "high", "subsidiary"),
    ("GENERAL DYNAMICS INFORMATION TECHNOLOGY", "GD", "high", "subsidiary"),
    ("GENERAL DYNAMICS MISSION SYSTEMS", "GD", "high", "subsidiary"),
    ("GENERAL DYNAMICS NASSCO", "GD", "high", "subsidiary"),
    ("ELECTRIC BOAT CORPORATION", "GD", "high", "subsidiary"),
    ("BOEING COMPANY", "BA", "high", "parent"),
    ("THE BOEING COMPANY", "BA", "high", "parent"),
    ("BOEING DEFENSE, SPACE & SECURITY", "BA", "high", "subsidiary"),
    ("L3HARRIS TECHNOLOGIES INC", "LHX", "high", "parent"),
    ("L3HARRIS TECHNOLOGIES, INC.", "LHX", "high", "parent"),
    ("AEROJET ROCKETDYNE", "LHX", "medium", "acquired by L3Harris 2023"),
    ("HUNTINGTON INGALLS INDUSTRIES INC", "HII", "high", "parent"),
    ("HUNTINGTON INGALLS INCORPORATED", "HII", "high", "parent"),
    ("KBR INC", "KBR", "high", "parent"),
    ("KBR, INC.", "KBR", "high", "parent"),
    ("CACI INTERNATIONAL INC", "CACI", "high", "parent"),
    ("CACI, INC. - FEDERAL", "CACI", "high", "subsidiary"),
    ("LEIDOS HOLDINGS INC", "LDOS", "high", "parent"),
    ("LEIDOS, INC.", "LDOS", "high", "subsidiary"),
    ("LEIDOS INNOVATIONS CORPORATION", "LDOS", "high", "subsidiary"),
    ("BWX TECHNOLOGIES INC", "BWXT", "high", "parent"),
    ("BWX TECHNOLOGIES, INC.", "BWXT", "high", "parent"),
    ("BOOZ ALLEN HAMILTON INC", "BAH", "high", "parent"),
    ("BOOZ ALLEN HAMILTON INC.", "BAH", "high", "parent"),
    ("SAIC INC", "SAIC", "high", "Science Applications International"),
    ("SCIENCE APPLICATIONS INTERNATIONAL CORP", "SAIC", "high", "parent"),
    ("TRANSDIGM GROUP INCORPORATED", "TDG", "high", "parent"),
    # Defense small/mid
    ("AEROVIRONMENT INC", "AVAV", "high", "parent"),
    ("KRATOS DEFENSE & SECURITY SOLUTIONS", "KTOS", "high", "parent"),
    ("MERCURY SYSTEMS INC", "MRCY", "high", "parent"),
    ("CURTISS-WRIGHT CORPORATION", "CW", "high", "parent"),
    ("HEICO CORPORATION", "HEI", "high", "parent"),
    ("TRIUMPH GROUP INC", "TGI", "high", "parent"),
    ("STURM, RUGER & CO., INC.", "RGR", "high", "parent"),
    ("PALANTIR TECHNOLOGIES INC", "PLTR", "high", "parent"),
    ("PALANTIR USG, INC.", "PLTR", "high", "subsidiary"),
    ("PARSONS CORPORATION", "PSN", "high", "parent"),
    ("V2X INC", "VVX", "high", "parent (formerly Vectrus + Vertex)"),
    ("CACI N.V.", "CACI", "medium", "European arm"),
    # Cloud / IT services
    ("ORACLE CORPORATION", "ORCL", "high", "parent"),
    ("ORACLE AMERICA INC", "ORCL", "high", "subsidiary"),
    ("MICROSOFT CORPORATION", "MSFT", "high", "parent"),
    ("AMAZON WEB SERVICES, INC.", "AMZN", "high", "subsidiary"),
    ("AMAZON.COM SERVICES LLC", "AMZN", "high", "subsidiary"),
    ("AMAZON WEB SERVICES", "AMZN", "high", "subsidiary"),
    ("GOOGLE LLC", "GOOGL", "high", "parent"),
    ("ALPHABET INC", "GOOGL", "high", "parent"),
    ("ACCENTURE FEDERAL SERVICES LLC", "ACN", "high", "subsidiary"),
    ("ACCENTURE LLP", "ACN", "high", "subsidiary"),
    ("INTERNATIONAL BUSINESS MACHINES CORP", "IBM", "high", "parent"),
    ("IBM CORPORATION", "IBM", "high", "parent"),
    ("COGNIZANT TECHNOLOGY SOLUTIONS U.S. CORPORATION", "CTSH", "high", "parent"),
    ("HEWLETT PACKARD ENTERPRISE", "HPE", "high", "parent"),
    ("DXC TECHNOLOGY COMPANY", "DXC", "high", "parent"),
    ("DXC TECHNOLOGY SERVICES LLC", "DXC", "high", "subsidiary"),
    ("CISCO SYSTEMS INC", "CSCO", "high", "parent"),
    ("AT&T INC.", "T", "high", "parent"),
    ("AT&T CORP.", "T", "high", "parent"),
    ("VERIZON COMMUNICATIONS INC", "VZ", "high", "parent"),
    ("DELL FEDERAL SYSTEMS L.P.", "DELL", "high", "subsidiary"),
    ("DELL TECHNOLOGIES INC", "DELL", "high", "parent"),
    ("HEWLETT-PACKARD COMPANY", "HPQ", "medium", "split from HPE"),
    # Healthcare / pharma
    ("HUMANA INC", "HUM", "high", "parent (Medicare)"),
    ("HUMANA GOVERNMENT BUSINESS, INC.", "HUM", "high", "subsidiary"),
    ("MCKESSON CORPORATION", "MCK", "high", "parent"),
    ("CARDINAL HEALTH 200, LLC", "CAH", "high", "subsidiary"),
    ("CARDINAL HEALTH INC", "CAH", "high", "parent"),
    ("CENTENE CORPORATION", "CNC", "high", "parent"),
    ("BRISTOL-MYERS SQUIBB COMPANY", "BMY", "high", "parent"),
    ("JOHNSON & JOHNSON", "JNJ", "high", "parent"),
    ("PFIZER INC", "PFE", "high", "parent"),
    ("PFIZER INC.", "PFE", "high", "parent"),
    ("MERCK & CO INC", "MRK", "high", "parent"),
    ("ELI LILLY AND COMPANY", "LLY", "high", "parent"),
    ("MODERNA TX, INC.", "MRNA", "high", "subsidiary"),
    ("MODERNA, INC.", "MRNA", "high", "parent"),
    # Industrial / energy
    ("GENERAL ELECTRIC COMPANY", "GE", "high", "parent"),
    ("HONEYWELL INTERNATIONAL INC", "HON", "high", "parent"),
    ("HONEYWELL INTERNATIONAL INC.", "HON", "high", "parent"),
    ("3M COMPANY", "MMM", "high", "parent"),
    ("EMERSON ELECTRIC CO", "EMR", "high", "parent"),
    ("CATERPILLAR INC", "CAT", "high", "parent"),
    ("DEERE & COMPANY", "DE", "high", "parent"),
    ("FORD MOTOR COMPANY", "F", "high", "parent (gov vehicles)"),
    ("GENERAL MOTORS LLC", "GM", "high", "parent"),
    ("OSHKOSH CORPORATION", "OSK", "high", "parent"),
    ("OSHKOSH DEFENSE LLC", "OSK", "high", "subsidiary"),
    ("AECOM", "ACM", "high", "parent"),
    ("AECOM TECHNICAL SERVICES, INC.", "ACM", "high", "subsidiary"),
    ("FLUOR ENTERPRISES, INC.", "FLR", "high", "subsidiary"),
    ("FLUOR CORPORATION", "FLR", "high", "parent"),
    ("JACOBS ENGINEERING GROUP INC", "J", "high", "parent"),
    ("BECHTEL NATIONAL INC", "", "low", "private — no ticker"),
    # Foreign/ADR (mapped to ADR)
    ("BAE SYSTEMS PLC", "BAESY", "medium", "ADR"),
    ("BAE SYSTEMS LAND & ARMAMENTS L P", "BAESY", "medium", "subsidiary"),
    ("BAE SYSTEMS INFORMATION AND ELECTRONIC", "BAESY", "medium", "subsidiary"),
    ("AIRBUS DEFENSE AND SPACE INC", "EADSY", "medium", "ADR"),
    # Energy/Utilities
    ("EXELON GENERATION COMPANY", "EXC", "high", "parent"),
    ("DUKE ENERGY CORPORATION", "DUK", "high", "parent"),
    # Misc
    ("FEDEX CORPORATE SERVICES, INC.", "FDX", "high", "subsidiary"),
    ("FEDEX CORPORATION", "FDX", "high", "parent"),
    ("UNITED PARCEL SERVICE INC", "UPS", "high", "parent"),
    # ... extends to ~150 entries total
]
```

Script normalizes each name then upserts to the sheet (key on `recipient_name_normalized`).

**Smoke test:** `python3 -c "from src.recipient_ticker import normalize, resolve; print(normalize('Lockheed Martin Corporation')); print(normalize('LOCKHEED-MARTIN, CORP.'))"` — both should produce identical normalization.

**Commit:** `feat: recipient->ticker resolver + 150-entry seed map`

---

### Task 5: Confluence screener

**Files:**
- Create: `scripts/screen_gov_confluence.py`
- Create: `.github/workflows/screen-gov-confluence.yml`

Per design doc Section 3 confluence formula. Single Python file, ~400 LOC.

Reads:
- `gov_contracts` — last 30 days, filter to non-empty `ticker`
- `congress_trades` — last 60 days, filter to `transaction_type=buy`
- `insider_transactions` — last 90 days, filter to purchases (transaction_code=P)
- `wsr_summary` (or fallback Finnhub fundamentals) — for TTM revenue

Writes:
- `gov_confluence_signals` — one row per ticker with score ≥ 60
- `decision_queue` — append rows for tier A/B picks with appropriate strategy

**Workflow YAML**: cron `0 23 * * 1-5` (07:00 SGT). Env: `OAUTH_TOKEN_JSON`, `SHEET_ID`, `FINNHUB_API_KEY`.

**Smoke test:** `python scripts/screen_gov_confluence.py --dry` runs end-to-end on whatever data is in the sheets. Should print ranked signals without writing.

**Commit:** `feat: gov confluence screener with 40/30/30 weighting`

---

### Task 6: Insider Trading Telegram topic + daily digest

**Files:**
- Modify: `src/telegram.py` — add topic constant + `ping_insider_pulse()`
- Create: `scripts/insider_pulse_digest.py`
- Create: `.github/workflows/insider-pulse-digest.yml`

**`src/telegram.py` additions:**

```python
INSIDER_TRADING_TOPIC = int(os.environ.get("TELEGRAM_INSIDER_TRADING_TOPIC", "0")) or None


def ping_insider_pulse(
    date: str,
    confluence_picks: list[dict],     # top N from gov_confluence_signals
    capitol_filings: list[dict],      # top N from congress_trades
    unmapped: list[dict] = None,      # gov_unmapped_recipients to flag
    pwa_url: str | None = None,
) -> dict:
    """
    Daily 'Insider Trading' topic digest. Format:

        📊 INSIDER PULSE · YYYY-MM-DD
        🎯 CONFLUENCE PICKS
        1. AVAV — score 87 · Tier A
           $35M Army drone contract (5-yr IDIQ, 8.2% TTM rev)
           + Pelosi bought 250K-500K filed 5d ago
           + CFO bought $180K open-market
           → 🟢 BUY_DIP @ $215 OR LONG_CALL Jun20 $230
        ...
        🏛 CAPITOL TRADES (top 3 by amount)
        ...
        ⚠ UNMAPPED RECIPIENTS (review)
        ...

    No-op (returns {"skipped": "no topic id"}) if INSIDER_TRADING_TOPIC is unset.
    """
    if INSIDER_TRADING_TOPIC is None:
        return {"skipped": "INSIDER_TRADING_TOPIC not configured"}
    # build body
    ...
    return send(body, parse_mode="HTML",
                message_thread_id=INSIDER_TRADING_TOPIC,
                disable_web_page_preview=True)
```

**`scripts/insider_pulse_digest.py`**: reads top 3 from `gov_confluence_signals` (today), top 3 from `congress_trades` by `amount_max`, recent unmapped recipients flagged in last 24h. Calls `ping_insider_pulse`.

**Workflow YAML**: cron `15 23 * * 1-5` (07:15 SGT). Env: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_INSIDER_TRADING_TOPIC` (when configured), `OAUTH_TOKEN_JSON`, `SHEET_ID`.

**Note for user:** topic must be created manually in Telegram supergroup. Once created, add `TELEGRAM_INSIDER_TRADING_TOPIC=<thread_id>` as a repo secret. Until then, the digest gracefully skips.

**Commit:** `feat: Insider Trading Telegram topic + daily pulse digest`

---

### Task 7: Brain prompt updates

**Files:**
- Modify: `prompts/cron_daily_brief.md`
- Modify: `prompts/cron_wsr_lite.md`
- Modify: `prompts/cron_wsr_full.md`

**Daily brief**: insert "**Government & Insider Pulse**" section between macro read and swing-book section. Brain instructions:
- Read `gov_confluence_signals` for today
- Read `gov_contracts` for context (top 5 contracts in last 7d)
- Read `congress_trades` for fresh filings (last 7d)
- Narrate top 3 confluence picks
- May override `recommended_strategy` (e.g. earnings within 7d → downgrade)
- Update `decision_queue` accordingly (status: `watching` → `act_now` for high conviction)

**WSR Lite**: weekly "Confluence Leaderboard" — top 5 by 7-day rolling confluence score.

**WSR Full**: deep dive on 1–3 highest-confluence picks for the week. Full thesis, options chain, sizing, exits.

**Commit:** `feat: brain prompt updates for gov confluence integration`

---

### Task 8: Smoke test live + final commit

**Steps:**

1. Verify all syntax-check clean: `python3 -c "import ast; [ast.parse(open(p).read()) for p in ['src/usaspending.py', 'src/capitoltrades.py', 'src/recipient_ticker.py', 'src/schema.py', 'src/telegram.py', 'scripts/fetch_gov_contracts.py', 'scripts/fetch_congress_trades.py', 'scripts/screen_gov_confluence.py', 'scripts/insider_pulse_digest.py', 'scripts/init_recipient_map.py']]"`
2. Live smoke USAspending: `.venv/bin/python -c "from src.usaspending import fetch_awards; from datetime import date, timedelta; y = (date.today() - timedelta(days=1)).isoformat(); print(len(fetch_awards(y, y, max_pages=1)), 'awards')"`
3. Live smoke CapitolTrades: `.venv/bin/python -c "from src.capitoltrades import fetch_recent_trades; from datetime import date, timedelta; print(len(fetch_recent_trades((date.today() - timedelta(days=14)).isoformat(), max_pages=1)), 'trades')"`
4. Final commit + push covering anything outstanding.
5. Write summary report at the top of the response in next session.

**Commit:** `feat: smoke-tested gov confluence pipeline end-to-end (Phase 1 ship)`

---

## Risks + watch-outs

- **CapitolTrades may serve a cookie wall or rate-limit aggressive scrapes**. Mitigation: 1 req/sec, polite UA, daily-only cadence, fall back to firecrawl MCP for one-off if blocked.
- **USAspending response shape is verbose**. The `fields` array in the request must match the keys we read out — typo = silent empty data. Verified against API docs in design phase.
- **TTM revenue data**: dependency on either WSR brain runs or Finnhub. If both miss for a small ticker, we fall back to insider+congress signals only (contract_score = 0). This is acceptable for v1.
- **Insider Trading topic ID**: code paths are no-ops until the secret is set. Caspar can ship Phase 1 without the topic and turn it on later.
- **`difflib` performance**: with ~150 entries, `get_close_matches` is fast. If we grow to 1000+, consider switching to `rapidfuzz`.
