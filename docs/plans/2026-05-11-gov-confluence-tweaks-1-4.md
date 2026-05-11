# Gov Confluence Strategy — Tweaks #1–#4 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Layer four ROI-ranked tweaks onto the shipped Phase 1 gov confluence strategy, derived from analysis of five QuiverQuant disclosed strategies (Analyst Buys, Congress L/S, House L/S, Homeland Committee, ChatGPT-Enhanced).

**Architecture:** All four tweaks are additive modifications to existing files — primarily `scripts/screen_gov_confluence.py` plus one schema extension and one new sheet reader. No new ingestion crons, no new workflows. Each tweak is independently shippable.

**Tech Stack:** Python 3.12, gspread, existing dataclass schemas, dry-run smoke testing against live Sheets.

---

## Why these four tweaks (from QQ strategy analysis)

| Tweak | Source | Mechanic | Impact |
|---|---|---|---|
| **#1 Congress cluster bonus** | QQ Congress L/S weights by tx size *and* count of distinct buyers — multiple politicians on same name = signal × N | Mirror our existing insider cluster bonus | +20 to congress_score when 3+ unique buyers in 30d |
| **#2 SELL signals as TRIM** | QQ Congress L/S goes SHORT on sells (130/30 leverage). We don't short — but we *do* hold longs, and Congress sells of a held name are TRIM information | Walk congress_trades for `transaction_type=sell`, intersect with active decision_queue longs | TRIM rows auto-appended to decision_queue |
| **#3 Richer thesis text** | QQ ChatGPT-Enhanced strategy publishes 2-3 sentence catalyst justifications per pick (not "Contract 60 · Congress 70") | Template-driven prose generator using TickerStats fields | Daily digest reads like a brief, not a stat dump |
| **#4 Analyst score (4th vector)** | QQ Analyst Buys: 78% win rate, Sharpe 0.92 over 3y by weighting forecasts by analyst track-record | We already have `analyst_consensus` from Finnhub weekly cron — wire as a 4th score component | Rebalance weights to 35/25/25/15 (contract/congress/insider/analyst) |

---

## Pre-flight checks (do these first)

**Step A: Confirm Phase 1 base is healthy.**

```bash
cd /Users/xynkro/Documents/Trading/FinancePWA
git log --oneline -10 | grep -E "gov confluence|Phase 1"
# Expected: see Phase 1 commits (5a27676 through 1e3a565)
```

**Step B: Snapshot current screener behaviour as baseline.**

```bash
.venv/bin/python scripts/screen_gov_confluence.py --dry 2>&1 | tail -30 > /tmp/screener_baseline.txt
cat /tmp/screener_baseline.txt
```

This captures the current top-10 signals so we can verify behavior changes are intentional after each tweak.

---

## Task 1: Congress cluster bonus (~10 LOC, smallest)

**Files:**
- Modify: `scripts/screen_gov_confluence.py:79-99` (extend `TickerStats` with `has_congress_cluster`)
- Modify: `scripts/screen_gov_confluence.py:286-336` (set `has_congress_cluster` in `_build_stats`)
- Modify: `scripts/screen_gov_confluence.py:368-379` (apply bonus in `_score_congress`)

**Why this first:** Smallest change, no schema impact, identical pattern to the existing insider cluster — low risk of breaking anything.

**Step 1: Extend `TickerStats`**

Add field after the existing `has_recent_congress` line:

```python
    has_congress_cluster: bool = False  # 3+ unique politicians in trailing 30d
```

**Step 2: Set the flag in `_build_stats`**

Insert after the existing congress loop (around line 316), mirroring the insider cluster logic:

```python
        # Congress cluster bonus: 3+ unique politicians in trailing 30d
        unique_politicians_30d: set[str] = set()
        for cg in congress_by_ticker.get(ticker, []):
            if _within_days(cg["filing_date"], 30, today):
                name = (cg.get("politician_name") or "").upper()
                if name:
                    unique_politicians_30d.add(name)
        ts.has_congress_cluster = len(unique_politicians_30d) >= 3
```

**Step 3: Apply +20 bonus in `_score_congress`**

Replace the existing function with:

```python
def _score_congress(ts: TickerStats) -> float:
    """Amount + recency + cluster.

    $1M total weighted = score 100 (clipped).
    Recency bonus +20 if any filing in last 14 days.
    Cluster bonus +20 if 3+ unique politicians bought in trailing 30d.
    """
    if not ts.congress_buys:
        return 0.0
    base = min(100.0, ts.congress_amount_total / 10_000.0)  # $1M = 100
    if ts.has_recent_congress:
        base += 20.0
    if ts.has_congress_cluster:
        base += 20.0
    return max(0.0, min(100.0, base))
```

**Step 4: Smoke test**

```bash
.venv/bin/python scripts/screen_gov_confluence.py --dry 2>&1 | tail -30
```

Verify (a) no crashes, (b) the top-10 reordering reflects cluster boost where multiple politicians bought, (c) clipping at 100 still holds.

**Step 5: Commit**

```bash
git add scripts/screen_gov_confluence.py
git commit -m "$(cat <<'EOF'
feat: Tweak #1 — Congress cluster bonus (+20 for 3+ politicians/30d)

Mirrors the existing insider cluster bonus pattern. QuiverQuant's
Congress L/S strategy weights by transaction size; the additional
signal we capture here is BUYER DIVERSITY — 3 different politicians
buying the same ticker in a 30d window is materially more meaningful
than one politician with a large position.

Implementation matches insider cluster: new `has_congress_cluster`
flag on TickerStats, set in `_build_stats`, applied as +20 in
`_score_congress`. Final score still clipped to [0, 100].

Source: QuiverQuant Congress L/S strategy disclosed mechanics —
https://www.quiverquant.com/strategies/s/Congress%20Long-Short/

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: SELL signals as TRIM candidates (~50 LOC)

**Files:**
- Modify: `scripts/screen_gov_confluence.py:180-237` (extend `_read_congress_trades` to also keep SELLs in a separate dict)
- Modify: `scripts/screen_gov_confluence.py:521-591` (new `_append_sell_signals_to_queue` helper)
- Modify: `scripts/screen_gov_confluence.py:598-640` (call the new helper from `main()`)

**Why second:** Adds a new output (TRIM rows) but no schema changes. Independent of Task 1.

**Design contract:**
- Read `congress_trades` rows where `transaction_type=sell` in last 30 days
- Group by ticker; require ≥2 unique politicians OR cumulative midpoint ≥ $500K for the SELL signal to fire
- Only emit TRIM rows for tickers that are CURRENTLY held in Caspar's or Sarah's portfolio (intersect with `positions_caspar` + `positions_sarah` latest day)
- TRIM `decision_queue` rows get: `source="gov_confluence_sell"`, `bucket="GOV_CONFLUENCE_TRIM"`, `strategy="TRIM"`, `conv=2` (lower than buys), `thesis_1liner="Congress sells: $X.XM from N politicians in 30d"`, `status="watching"` so brain reviews tomorrow morning

**Step 1: Add helper to read held tickers**

Insert after `_read_insider_buys` (around line 280):

```python
def _read_held_tickers(client) -> set[str]:
    """Set of tickers currently held in either account (latest snapshot)."""
    ss = sh._open_sheet(client)
    held: set[str] = set()
    for tab in ("positions_caspar", "positions_sarah"):
        try:
            ws = ss.worksheet(tab)
        except Exception:
            continue
        rows = ws.get_all_values()
        if len(rows) < 2:
            continue
        hdr = rows[0]
        try:
            c_date = hdr.index("date")
            c_tk = hdr.index("ticker")
        except ValueError:
            continue
        latest = max((r[c_date] for r in rows[1:] if len(r) > c_date and r[c_date]), default="")
        if not latest:
            continue
        for r in rows[1:]:
            if len(r) > max(c_date, c_tk) and r[c_date] == latest and r[c_tk]:
                held.add(r[c_tk].strip().upper())
    return held
```

**Step 2: Add helper to read Congress sells**

Insert before `_read_held_tickers`:

```python
def _read_congress_sells(client, today: date) -> dict[str, list[dict]]:
    """Read congress_trades rows where transaction_type=sell in last 30d,
    grouped by ticker. Mirrors _read_congress_trades but flipped to sells."""
    cutoff_iso = (today - timedelta(days=30)).isoformat()
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.CongressTradeRow.TAB_NAME)
    except Exception:
        return {}
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {}
    hdr = rows[0]
    cols = {h: i for i, h in enumerate(hdr)}
    needed = ["ticker", "filing_date", "transaction_type", "amount_min", "amount_max", "filing_id"]
    if not all(c in cols for c in needed):
        return {}
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for r in rows[1:]:
        ticker = (r[cols["ticker"]] if len(r) > cols["ticker"] else "").upper()
        if not ticker:
            continue
        ttype = (r[cols["transaction_type"]] if len(r) > cols["transaction_type"] else "").lower()
        if ttype != "sell":
            continue
        filing_date = (r[cols["filing_date"]] if len(r) > cols["filing_date"] else "")[:10]
        if not filing_date or filing_date < cutoff_iso:
            continue
        amt_min = _safe_float(r[cols["amount_min"]] if len(r) > cols["amount_min"] else "0")
        amt_max = _safe_float(r[cols["amount_max"]] if len(r) > cols["amount_max"] else "0")
        midpoint = (amt_min + amt_max) / 2.0
        by_ticker[ticker].append({
            "filing_id": (r[cols["filing_id"]] if len(r) > cols["filing_id"] else ""),
            "filing_date": filing_date,
            "midpoint": midpoint,
            "politician_name": (r[cols.get("politician_name", -1)] if cols.get("politician_name", -1) >= 0 and len(r) > cols.get("politician_name", -1) else ""),
        })
    return by_ticker
```

**Step 3: Add TRIM emitter**

Insert after `_append_to_decision_queue` (around line 591):

```python
# Thresholds for SELL → TRIM emission
TRIM_MIN_POLITICIANS = 2
TRIM_MIN_AMOUNT = 500_000.0


def _append_sell_signals_to_queue(
    client,
    sells_by_ticker: dict[str, list[dict]],
    held_tickers: set[str],
    today_iso: str,
    logger: logging.Logger,
) -> int:
    """Emit TRIM rows to decision_queue for currently-held tickers with
    cluster of Congress sells. Conservative gate to avoid noise."""
    candidates: list[tuple[str, list[dict]]] = []
    for ticker, sells in sells_by_ticker.items():
        if ticker not in held_tickers:
            continue
        unique_politicians = {(s.get("politician_name") or "").upper() for s in sells if s.get("politician_name")}
        total_midpoint = sum(s["midpoint"] for s in sells)
        if len(unique_politicians) >= TRIM_MIN_POLITICIANS or total_midpoint >= TRIM_MIN_AMOUNT:
            candidates.append((ticker, sells))

    if not candidates:
        logger.info("  · no Congress-sell TRIM candidates among held tickers")
        return 0

    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.DecisionRow.TAB_NAME)
    except Exception:
        sh.ensure_headers(client, S.DecisionRow.TAB_NAME, S.DecisionRow.HEADERS)
        ws = ss.worksheet(S.DecisionRow.TAB_NAME)
    existing = ws.get_all_values()
    today_existing: set[tuple[str, str]] = set()
    if len(existing) > 1:
        hdr = existing[0]
        try:
            c_date = hdr.index("date")
            c_tk = hdr.index("ticker")
            c_src = hdr.index("source") if "source" in hdr else -1
        except ValueError:
            c_date = c_tk = c_src = -1
        if c_date >= 0 and c_tk >= 0:
            for r in existing[1:]:
                if len(r) > max(c_date, c_tk):
                    src_ok = (c_src < 0) or (len(r) > c_src and r[c_src] == "gov_confluence_sell")
                    if src_ok:
                        today_existing.add((r[c_date], r[c_tk]))

    new_rows = []
    for ticker, sells in candidates:
        if (today_iso, ticker) in today_existing:
            continue
        n_pol = len({(s.get("politician_name") or "").upper() for s in sells if s.get("politician_name")})
        total = sum(s["midpoint"] for s in sells)
        thesis = f"Congress sells: ${total/1e6:.2f}M from {n_pol} politicians/30d"
        d = S.DecisionRow(
            date=today_iso,
            account="caspar",  # brain assigns to actual holder
            ticker=ticker,
            bucket="GOV_CONFLUENCE_TRIM",
            thesis_1liner=thesis,
            conv=2,
            entry=0.0,
            target=0.0,
            status="watching",
            strategy="TRIM",
            right="", strike=0.0, expiry="",
            premium_per_share=0.0, delta=0.0, annual_yield_pct=0.0,
            breakeven=0.0, cash_required=0.0, iv_rank=0.0,
            thesis_confidence=0.5,
            thesis=thesis,
            source="gov_confluence_sell",
            qty=0, accumulation_plan="", gates="[]",
        )
        new_rows.append(d.to_row())

    if not new_rows:
        logger.info(f"  · {len(candidates)} TRIM candidates all already in decision_queue today")
        return 0

    sh.append_rows(client, S.DecisionRow.TAB_NAME, new_rows)
    logger.info(f"  ✓ appended {len(new_rows)} TRIM rows to {S.DecisionRow.TAB_NAME}")
    return len(new_rows)
```

**Step 4: Wire into `main()`**

Insert after `_append_to_decision_queue` call (around line 639):

```python
    sells = _read_congress_sells(client, today)
    held = _read_held_tickers(client)
    trim_appended = _append_sell_signals_to_queue(client, sells, held, today_iso, logger)
```

And update the final log line to include `trim_appended`.

**Step 5: Smoke test**

```bash
.venv/bin/python scripts/screen_gov_confluence.py --dry 2>&1 | tail -40
```

Expected: log line showing how many held tickers + Congress sells were found, and either "no TRIM candidates" or "would emit N TRIM rows".

**Step 6: Commit**

```bash
git add scripts/screen_gov_confluence.py
git commit -m "$(cat <<'EOF'
feat: Tweak #2 — Congress SELL signals → TRIM candidates

We don't short (book is long-only), but Congress sells of a CURRENTLY
HELD name carry trim information. Cluster-gated to avoid noise: only
fires when 2+ politicians sold OR cumulative midpoint >= $500K within
30d, AND the ticker is in positions_caspar/positions_sarah latest.

Emits TRIM rows to decision_queue with:
- bucket=GOV_CONFLUENCE_TRIM
- strategy=TRIM
- source=gov_confluence_sell
- conv=2 (lower than buys; brain reviews before action)
- status=watching

Brain reviews in next-morning daily brief; may upgrade to act_now
or downgrade to skip based on portfolio context (e.g. recent earnings,
new contract that cancels the sell signal, etc.).

Source: QuiverQuant Congress L/S strategy — the 130/30 leverage on
shorts captures negative info in Congress sells; we approximate the
long-only equivalent by trimming existing positions.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Richer thesis text (~60 LOC)

**Files:**
- Modify: `scripts/screen_gov_confluence.py:435-450` (rewrite `_build_thesis` with prose templates)
- Modify: `scripts/screen_gov_confluence.py:419-432` (refine `_build_action_text` to complement, not duplicate)

**Why third:** No data shape changes, no new readers — purely text-template work. Independent of Tasks 1 & 2 but benefits from both (cluster flags become quotable).

**Step 1: Rewrite `_build_thesis` as prose**

Replace lines 435-450:

```python
def _build_thesis(ts: TickerStats, contract_score: float, congress_score: float, insider_score: float) -> str:
    """Multi-sentence thesis in WSJ/Bloomberg-style.

    Mirrors the QuiverQuant ChatGPT-Enhanced format: 1-2 concise sentences
    citing the strongest catalyst(s) per signal, not a stat dump. Brain
    may rewrite/expand this at brief time; this is the rules-based default
    used for Telegram digests that fire BEFORE the brain runs.
    """
    sentences: list[str] = []

    # Contract sentence — lead with the strongest contract fact
    if ts.contracts:
        n = len(ts.contracts)
        total_m = ts.contract_total_30d / 1e6
        max_m = ts.contract_max_single / 1e6
        flavor = ""
        if ts.has_multi_year:
            flavor += " multi-year IDIQ"
        if ts.has_priority_naics:
            flavor += " in a top federal-spending sector"
        if ts.has_recent_award:
            recency = "in the last 7 days"
        else:
            recency = "in the trailing 30 days"
        if n == 1:
            sentences.append(
                f"Captured a ${max_m:.1f}M{flavor} contract {recency}."
            )
        else:
            sentences.append(
                f"Stacked {n} contracts totaling ${total_m:.1f}M (largest ${max_m:.1f}M){flavor} {recency}."
            )

    # Confluence sentence — Congress + insider together
    conf_bits: list[str] = []
    if ts.congress_buys:
        n_cg = len(ts.congress_buys)
        amt_m = ts.congress_amount_total / 1e6
        if ts.has_congress_cluster:
            conf_bits.append(f"{n_cg} Congress buys from 3+ distinct members totaling ${amt_m:.2f}M/30d")
        elif ts.has_recent_congress:
            conf_bits.append(f"{n_cg} Congress buys (${amt_m:.2f}M) with filings in last 14d")
        else:
            conf_bits.append(f"{n_cg} Congress buys totaling ${amt_m:.2f}M")
    if ts.insider_buys:
        n_ib = len(ts.insider_buys)
        ival_m = ts.insider_value_total / 1e6
        if ts.has_insider_cluster:
            conf_bits.append(f"insider cluster ({ts.insider_unique_count} unique buyers, ${ival_m:.2f}M)")
        else:
            conf_bits.append(f"{n_ib} insider buys worth ${ival_m:.2f}M")
    if conf_bits:
        sentences.append("Aligned " + " and ".join(conf_bits) + ".")

    # Score footer for transparency (kept terse)
    sentences.append(
        f"Score breakdown — contract {contract_score:.0f} / congress {congress_score:.0f} / insider {insider_score:.0f}."
    )

    return " ".join(sentences)
```

**Step 2: Trim `_build_action_text` to one line**

Replace lines 419-432:

```python
def _build_action_text(ts: TickerStats, score: float, strategy: str) -> str:
    """One-line actionable summary for ping subject lines.

    Distinct from `_build_thesis` (which writes prose): this is the
    Telegram subject-line / log-line view — single line, dense stats.
    """
    parts = []
    if ts.contracts:
        parts.append(f"${ts.contract_total_30d/1e6:.1f}M contracts ({len(ts.contracts)})")
    if ts.congress_buys:
        parts.append(f"${ts.congress_amount_total/1e6:.2f}M Congress ({len(ts.congress_buys)})")
    if ts.insider_buys:
        parts.append(f"${ts.insider_value_total/1e6:.2f}M insider ({len(ts.insider_buys)})")
    body = " · ".join(parts)
    label = strategy or "WATCH"
    return f"{label} · score {score:.0f} · {body}" if body else f"{label} · score {score:.0f}"
```

**Step 3: Smoke test with synthetic input**

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from scripts.screen_gov_confluence import _build_thesis, TickerStats
ts = TickerStats(
    ticker='AVAV',
    contracts=[{'award_amount': 35_000_000}],
    contract_total_30d=35_000_000,
    contract_max_single=35_000_000,
    has_multi_year=True,
    has_recent_award=True,
    has_priority_naics=True,
    congress_buys=[{'midpoint': 375_000}],
    congress_amount_total=375_000,
    has_recent_congress=True,
    has_congress_cluster=False,
    insider_buys=[{'value_usd': 180_000}],
    insider_value_total=180_000,
    insider_unique_count=1,
    has_insider_cluster=False,
)
print(_build_thesis(ts, 80, 60, 30))
"
```

Expected: 3 sentences, reads like prose, mentions IDIQ + top sector + last-7-days + Congress + insider + score breakdown.

**Step 4: Full dry run**

```bash
.venv/bin/python scripts/screen_gov_confluence.py --dry 2>&1 | tail -30
```

Verify thesis lines in top-10 output now read as prose, not stat dumps.

**Step 5: Commit**

```bash
git add scripts/screen_gov_confluence.py
git commit -m "$(cat <<'EOF'
feat: Tweak #3 — richer thesis prose (replaces stat-dump format)

Replaces "Contract 60 · Congress 70 · Insider 50 (flags)" with 2-3
sentence WSJ-style prose mirroring QuiverQuant's ChatGPT-Enhanced
format. Each sentence cites concrete facts (dollar values, counts,
specific flags) — no boilerplate.

Example before:
  Contract 80 · Congress 60 · Insider 30 (multi-yr IDIQ, fresh award <7d, Congress <14d)

Example after:
  Captured a $35.0M multi-year IDIQ contract in a top federal-spending
  sector in the last 7 days. Aligned 1 Congress buys ($0.38M) with
  filings in last 14d and 1 insider buys worth $0.18M.
  Score breakdown — contract 80 / congress 60 / insider 30.

The action_text helper now produces a true one-liner subject (with
score), distinct from the thesis prose. Brain may still rewrite/expand
at brief time; this is the rules-based default that fires in the
07:15 SGT Telegram digest before the brain runs.

Source: QuiverQuant ChatGPT-Enhanced strategy's "Latest AI Picks"
table format — 2-3 sentence catalyst-cited justifications per pick.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Analyst score as 4th confluence vector (~150 LOC + schema)

**Files:**
- Modify: `src/schema.py` (extend `GovConfluenceSignalRow` with `analyst_score` column)
- Modify: `scripts/screen_gov_confluence.py:57-60` (re-balance weights to 35/25/25/15)
- Modify: `scripts/screen_gov_confluence.py:79-99` (extend `TickerStats` with analyst fields)
- Modify: `scripts/screen_gov_confluence.py:101-117` (add `_read_analyst_consensus` reader)
- Modify: `scripts/screen_gov_confluence.py:286-336` (wire analyst data into `_build_stats`)
- Add: `_score_analyst` function
- Modify: `scripts/screen_gov_confluence.py:457-510` (use new weights + write `analyst_score` column)

**Why last:** Largest change with a schema bump. Done after the other three so a regression here doesn't block them.

**Design:** Use `analyst_consensus.consensus_score` (range [-2, +2]) as the input.
- consensus_score in [-2, +1.0): analyst_score = 0 (strong sell to lukewarm hold — no boost)
- consensus_score in [1.0, 2.0]: analyst_score = 50 + 50 * (consensus_score - 1.0)
  - 1.0 (buy) → 50
  - 1.5 (mid buy/strong-buy) → 75
  - 2.0 (strong buy) → 100
- Tickers missing from analyst_consensus: analyst_score = 0 (no penalty, just no boost)

New weights — derived from QQ's Analyst Buys having stronger Sharpe (0.92) than Congress Buys (1.11 but smaller universe) and Insider studies (varied):
- contract: 0.35 (down from 0.40 — primary signal but rebalanced)
- congress: 0.25 (down from 0.30)
- insider: 0.25 (down from 0.30)
- analyst: 0.15 (new)

Total still sums to 1.00 → 100 max score → no other constants change.

**Step 1: Extend `GovConfluenceSignalRow` schema**

In `src/schema.py:1972-2027`, add `analyst_score` to HEADERS (after `insider_score`) and to the dataclass + `to_row()`:

```python
    HEADERS = [
        "date", "ticker",
        "confluence_score",
        "contract_score", "congress_score", "insider_score", "analyst_score",  # ← new
        "tier",
        "recommended_strategy",
        "recommended_action",
        "thesis_oneliner",
        "contributing_contracts",
        "contributing_congress_trades",
        "contributing_insider_buys",
        "updated_at",
    ]
```

And the field + `to_row` rendering, with explicit default 0.0 so existing call sites that don't pass it (none currently exist outside the screener — verify with grep first) still work, and so older sheet rows missing the column are safe to read.

Add field:
```python
    insider_score: float
    analyst_score: float = 0.0  # ← new (default for backward read compatibility)
    tier: str
```

Add to `to_row()` after `_num(self.insider_score, 1)`:
```python
            _num(self.analyst_score, 1),
```

**Step 2: Update weights at top of screener**

Replace lines 57-60:

```python
# Weights (sum to 1.00). Re-balanced from 40/30/30 to add analyst as
# the 4th vector. Inspired by QuiverQuant's Analyst Buys strategy
# (78% win rate, Sharpe 0.92 over 3y) showing weighted analyst signal
# adds real alpha when combined with cluster/insider data.
W_CONTRACT = 0.35
W_CONGRESS = 0.25
W_INSIDER  = 0.25
W_ANALYST  = 0.15
```

**Step 3: Extend `TickerStats`**

Add fields after the insider section (around line 98):

```python
    # Analyst data
    analyst_consensus_score: float = 0.0  # [-2..+2] raw from analyst_consensus
    analyst_total_count: int = 0
    analyst_label: str = ""  # STRONG_BUY|BUY|HOLD|SELL|STRONG_SELL|""
```

**Step 4: Add `_read_analyst_consensus` reader**

Insert after `_read_insider_buys` (around line 280):

```python
def _read_analyst_consensus(client) -> dict[str, dict]:
    """Per-ticker latest analyst consensus from the weekly Finnhub cron.

    No date filter — `analyst_consensus` is upserted by ticker, so
    every row is current. Maps ticker → {consensus_score, label, total_count}.
    """
    ss = sh._open_sheet(client)
    try:
        ws = ss.worksheet(S.AnalystConsensusRow.TAB_NAME)
    except Exception:
        log.warning("analyst_consensus worksheet missing — analyst vector will be zero for all tickers")
        return {}
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {}
    hdr = rows[0]
    cols = {h: i for i, h in enumerate(hdr)}
    needed = ["ticker", "consensus_score", "consensus_label", "total_count"]
    if not all(c in cols for c in needed):
        log.warning("analyst_consensus schema mismatch — skipping analyst vector")
        return {}

    out: dict[str, dict] = {}
    for r in rows[1:]:
        ticker = (r[cols["ticker"]] if len(r) > cols["ticker"] else "").upper()
        if not ticker:
            continue
        out[ticker] = {
            "consensus_score": _safe_float(r[cols["consensus_score"]] if len(r) > cols["consensus_score"] else "0"),
            "label": r[cols["consensus_label"]] if len(r) > cols["consensus_label"] else "",
            "total_count": int(_safe_float(r[cols["total_count"]] if len(r) > cols["total_count"] else "0")),
        }
    log.info(f"analyst_consensus: {len(out)} tickers loaded")
    return out
```

**Step 5: Wire analyst data into `_build_stats`**

Update the function signature and walk:

```python
def _build_stats(
    contracts_by_ticker: dict[str, list[dict]],
    congress_by_ticker: dict[str, list[dict]],
    insider_by_ticker: dict[str, list[dict]],
    analyst_by_ticker: dict[str, dict],  # ← new
    today: date,
) -> dict[str, TickerStats]:
    all_tickers = set(contracts_by_ticker) | set(congress_by_ticker) | set(insider_by_ticker)
    # Note: analyst data alone doesn't qualify a ticker for a signal —
    # must have at least one of contract/congress/insider activity.
    out: dict[str, TickerStats] = {}

    for ticker in all_tickers:
        ts = TickerStats(ticker=ticker)

        # ... existing contract/congress/insider loops ...

        # Analyst data (look up, no aggregation)
        ac = analyst_by_ticker.get(ticker)
        if ac:
            ts.analyst_consensus_score = ac["consensus_score"]
            ts.analyst_total_count = ac["total_count"]
            ts.analyst_label = ac["label"]

        out[ticker] = ts
    return out
```

**Step 6: Add `_score_analyst`**

Insert after `_score_insider`:

```python
def _score_analyst(ts: TickerStats) -> float:
    """Map analyst_consensus_score [-2..+2] → [0..100].

    Below +1.0 (i.e. weaker than "buy" consensus) contributes nothing —
    consensus has to be at least Buy to count as a confluence vector.
    Tickers with <5 analyst total count are dampened to half-weight
    (small sample bias).
    """
    s = ts.analyst_consensus_score
    if s < 1.0:
        return 0.0
    base = 50.0 + 50.0 * (s - 1.0)  # 1.0 → 50, 2.0 → 100
    base = max(0.0, min(100.0, base))
    if ts.analyst_total_count < 5:
        base *= 0.5
    return base
```

**Step 7: Update `_build_signal_rows` to use new weights + write `analyst_score`**

Replace the scoring block (around line 463):

```python
        contract_score, impact_pct = _score_contract(ts, ttm_revenue=None)
        congress_score = _score_congress(ts)
        insider_score = _score_insider(ts)
        analyst_score = _score_analyst(ts)
        score = (
            W_CONTRACT * contract_score
            + W_CONGRESS * congress_score
            + W_INSIDER  * insider_score
            + W_ANALYST  * analyst_score
        )
        if score < MIN_SCORE_TO_PERSIST:
            continue
        tier = _classify_tier(score, impact_pct, ts.has_multi_year)
        strategy = _recommend_strategy(score, tier)
        out.append(S.GovConfluenceSignalRow(
            date=today_iso,
            ticker=ticker,
            confluence_score=score,
            contract_score=contract_score,
            congress_score=congress_score,
            insider_score=insider_score,
            analyst_score=analyst_score,  # ← new
            tier=tier,
            recommended_strategy=strategy,
            recommended_action=_build_action_text(ts, score, strategy),
            thesis_oneliner=_build_thesis(ts, contract_score, congress_score, insider_score, analyst_score),
            # ... rest unchanged ...
        ))
```

**Step 8: Update `_build_thesis` signature for analyst mention**

Append to the prose:

```python
def _build_thesis(
    ts: TickerStats,
    contract_score: float,
    congress_score: float,
    insider_score: float,
    analyst_score: float,
) -> str:
    # ... existing logic ...

    # Analyst sentence (only when meaningful — >= consensus BUY)
    if ts.analyst_label in ("STRONG_BUY", "BUY") and ts.analyst_total_count >= 5:
        sentences.insert(
            -1,  # before the score-breakdown footer
            f"Sell-side: {ts.analyst_label.replace('_', ' ').lower()} consensus across {ts.analyst_total_count} analysts.",
        )

    # Update score footer
    sentences[-1] = (
        f"Score — contract {contract_score:.0f} / congress {congress_score:.0f} / "
        f"insider {insider_score:.0f} / analyst {analyst_score:.0f}."
    )
    return " ".join(sentences)
```

**Step 9: Update `main()` to read analyst data**

In `main()` (around line 612):

```python
    contracts = _read_gov_contracts(client, today)
    congress = _read_congress_trades(client, today)
    insider = _read_insider_buys(client, today)
    analyst = _read_analyst_consensus(client)

    if not (contracts or congress or insider):
        logger.info("All three core feeds empty — nothing to score")
        return 0

    stats = _build_stats(contracts, congress, insider, analyst, today)
```

**Step 10: Smoke test**

```bash
.venv/bin/python scripts/screen_gov_confluence.py --dry 2>&1 | tail -40
```

Expected:
- log line: `analyst_consensus: N tickers loaded`
- Score breakdowns in thesis lines now include `/ analyst X`
- Some tickers' scores shift due to re-weighted (35/25/25/15)
- If `analyst_consensus` sheet is empty, all analyst scores are 0 and behavior matches Task 1+2+3 baseline

**Step 11: Commit**

```bash
git add src/schema.py scripts/screen_gov_confluence.py
git commit -m "$(cat <<'EOF'
feat: Tweak #4 — analyst consensus as 4th confluence vector

Adds analyst_score (0-100) derived from the existing weekly Finnhub
analyst_consensus feed (consensus_score in [-2, +2] → 50 at BUY, 100
at STRONG_BUY, 0 below BUY). <5 analyst total count is half-weighted
to avoid small-sample bias.

Re-balanced weights from 40/30/30 → 35/25/25/15
(contract/congress/insider/analyst). Total still sums to 1.00 and max
score is still 100, so MIN_SCORE_TO_PERSIST and tier thresholds are
unchanged.

Schema bump: GovConfluenceSignalRow gains an analyst_score column.
Backward-compatible (default 0.0 in dataclass, append to HEADERS).
Thesis prose now mentions sell-side consensus when ticker has BUY or
STRONG_BUY with >=5 analysts covering.

No new ingestion cron needed — analyst_consensus is already populated
weekly by scripts/finnhub_analyst.py. Tickers missing from the sheet
score 0 on the analyst vector (no penalty, just no boost).

Inspired by QuiverQuant's Analyst Buys strategy: 78% win rate, Sharpe
0.92 over 3 years. The QQ recipe weights individual analyst forecasts
by historical track-record accuracy — we use Finnhub's aggregate
consensus as a free approximation. v1.5 could add per-analyst track
record scoring if Finnhub exposes the data.

Source: https://www.quiverquant.com/strategies/s/Analyst%20Buys/

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Final verification (after all 4 tasks)

**Step 1: Full dry run end-to-end**

```bash
.venv/bin/python scripts/screen_gov_confluence.py --dry 2>&1 | tee /tmp/screener_after.txt
diff /tmp/screener_baseline.txt /tmp/screener_after.txt | head -40
```

Confirm: ranking changes are explainable (cluster-boosted tickers move up, analyst-rated tickers shift), no exceptions, log output looks healthy.

**Step 2: Syntax + import check**

```bash
.venv/bin/python -c "from scripts import screen_gov_confluence; import src.schema; print('imports OK')"
```

**Step 3: Push all four commits**

```bash
git log --oneline -5
git push
```

**Step 4: Update the shipped summary doc**

Add a section to `docs/plans/2026-05-10-gov-spending-confluence-strategy-shipped.md` (or create a new `2026-05-11-tweaks-1-4-shipped.md`) summarising the four tweaks, before/after metrics, and links to the QQ source strategies.

---

## What's deliberately out of scope (v1.5+)

- **Per-analyst track-record scoring** (true QQ Analyst Buys recipe). Free tier of Finnhub doesn't expose individual analyst hit-rates; we use aggregate consensus as a proxy.
- **Real shorts** (LONG_PUT / SHORT_CALL on Congress sells). Caspar's book is long-only; Task 2 captures sell-side info as TRIM-on-held only.
- **Portfolio-level allocation cap** (Tweak #5). Defer to v1.5 once we see whether v1 over-concentrates.
- **House-only vs full-Congress weighting** (House L/S had better Sharpe than full Congress). Could add a `chamber_weight` parameter but the chamber field needs to be reliably populated by the CapitolTrades scraper first — separate cleanup task.
- **Lobbying-spend vector**. The QQ "Lobbying Spending Growth" strategy had the highest CAGR (26.5%) — adding LD-2 disclosure ingestion is its own multi-day project.

---

## Risk register

| Risk | Mitigation |
|---|---|
| Cluster bonus over-boosts a popular Pelosi name into Tier B mistakenly | Cluster bonus capped at +20 (final score still clipped to 100); Tier B still requires multi-year IDIQ + impact_pct >= 5% |
| TRIM rows trigger on a benign Congress sell (annual rebalance, etc.) | Conservative gate (2+ politicians OR $500K+); brain reviews next morning; conv=2 (lower than buys) |
| Richer thesis breaks Telegram preview rendering | Plain text, no HTML — Telegram client renders normally; sentences capped at natural length |
| Analyst weight shift drops a previously-Tier-A signal below 70 | Acceptable — the rebalance is intentional; signals that lose Tier A on the new weighting were marginal anyway |
| `analyst_consensus` sheet has stale data | _score_analyst returns 0 for missing/old; no penalty, just no boost |
| `analyst_score` column not yet present in existing sheet | New column appends to right of existing data; older rows show empty in the new column which Sheets handles fine |
