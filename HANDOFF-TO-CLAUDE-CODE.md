# Handoff — Cowork → Claude Code

**Date:** 2026-04-15
**From:** Cowork session (scaffolded S1)
**To:** Claude Code session (owning S1 gate + S2 PWA build)

---

## What's already done

- Design doc: `docs/plans/2026-04-15-portfolio-pwa-design.md`
- S1 sync layer scaffolded: `src/sync.py` + helpers + fixtures
- `.env` populated with Sheet ID, Drive folder ID, Telegram token, chat ID
- `.config/client_secret.json` — OAuth Desktop client
- Dryruns pass against both fixtures (Cowork sandbox verified)

## What Claude Code needs to do

### 1. Close S1 gate (~15 min)

```bash
cd "~/Documents/Trading/FinancePWA"
bash setup.sh
```

`setup.sh`:
- creates `.venv`
- installs `gspread pydrive2 python-dotenv requests`
- runs both dryruns as sanity check
- opens browser for OAuth consent (Caspar approves, token cached to `.state/authorized_user.json`)

Then verify live writes:

```bash
source .venv/bin/activate
python src/sync.py daily --json fixtures/daily_sample.json
```

Expected:
- new row in `daily_brief_latest` tab of Sheet `1N2AAx1GqTi23Qlq6MZkQoYfQOY7An1K0vvPx65YBiQc`
- new row in `macro` tab
- Telegram message "📰 Daily Brief 2026-04-15 ready" in `@Tron_shaft_bot`

If all three sinks fire, **S1 gate closed**.

### 2. S1.5 — WSR spec v0.5 addendum (~30 min)

Edit `~/Documents/Trading/Weekly Strategy Review/_templates/pipeline_spec.md`:

- Change scope line: "Wife's account is a planned phase-2 extension — not in scope" → remove, replace with: "Dual-portfolio: Caspar U6773281 + Sarah U16000287. Caspar via IBKR MCP automated; Sarah via IBKR Chrome session snapshot (user pre-authenticates Monday morning)."
- Add to ledger schema: `sarah_portfolio: {net_liq, cash, positions: [...same shape as portfolio.positions]}`
- Add to Pass 1 prompt: step "1.5 — Sarah snapshot. Caspar keeps IBKR Chrome session live. Read Sarah's portfolio page, extract net_liq, cash, positions. Write to ledger.sarah_portfolio."
- Add to Pass 2 end: `python "~/Documents/Trading/FinancePWA/src/sync.py" wsr --ledger "$LEDGER_PATH" --md "$MD_PATH" --pdf "$PDF_PATH"`

### 3. S1.6 — Daily prompt addendum (~10 min)

Edit `~/Documents/Trading/Daily News Brief/_templates/daily_news_brief_prompt.md`:

- Before "Done" section, add:

  ```
  ## Emit sidecar JSON
  Write `~/Documents/Trading/Daily News Brief/{YYYYMMDD}_brief.json`:
  ```json
  {
    "date": "{YYYY-MM-DD}",
    "bullets": ["...", "...", "..."],
    "verdict": "{one-liner verdict}",
    "sentiment": "bullish|neutral|bearish"
  }
  ```

  ## Sync to dashboard
  Run:
  ```bash
  python "~/Documents/Trading/FinancePWA/src/sync.py" daily \
    --json "~/Documents/Trading/Daily News Brief/{YYYYMMDD}_brief.json" \
    --md "~/Documents/Trading/Daily News Brief/{YYYYMMDD}_NewsBrief.md"
  ```
  ```

### 4. S2 — PWA scaffold

Git remote already provisioned: `https://github.com/xynkro/CasaaFinance.git` (private).

```bash
cd "~/Documents/Trading/FinancePWA/pwa"
npm create vite@latest . -- --template react-ts
npm install
npm install -D tailwindcss postcss autoprefixer vite-plugin-pwa
npm install papaparse recharts lucide-react
npx tailwindcss init -p
```

Then follow design doc §7 — single Home route, four cards stacked. Publish-to-web CSV fetch per tab.

Deploy workflow: GitHub Actions → `gh-pages` branch. Once deployed, set `PWA_URL` in `.env`.

Design decisions locked (from Cowork session):
- Verdict chip: emoji + word ("🟢 bullish" / "🟡 neutral" / "🔴 bearish")
- Household SPY delta: YTD only
- Household currency: USD primary, SGD in brackets w/ conversion rate (small text)
- Repo: private, gh-pages public

## Open items

- `PWA_URL` stays blank in `.env` until S2 deploys
- Sarah's IBKR MCP status — if we add a second IBKR connection, daily Sarah snapshots become automatable (Phase 3+)
- Decision queue md→JSON parser — currently WSR ledger must carry `decisions[]` directly; parser from md is Phase 3 if needed

## Files to read first in Claude Code

1. `README.md` — repo overview
2. `docs/plans/2026-04-15-portfolio-pwa-design.md` — full design
3. `src/sync.py` — the CLI you're closing the gate on
4. This handoff doc
