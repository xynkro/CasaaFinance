# Portfolio PWA — Design Doc

**Date:** 2026-04-15
**Owner:** Caspar
**Status:** Design, pre-scaffold
**Parent:** `portfolio_pwa_handoff-e9973b8e.md` (uploaded 2026-04-15)

---

## 1. Anchor

Single job-to-be-done, prioritised 2026-04-15 session:

1. **C — One-tap morning glance.** Daily Brief verdict + both P&Ls on one screen, no app-switching. (Primary)
2. **B — Decision queue discipline.** Pending/filled/killed cards forcing entry/exit hygiene. (Secondary)
3. **A — Household combined view.** Caspar USD + Sarah SGD-normalised. (Tertiary)
4. **D — Shared surface for Sarah.** (Deferred; nice-to-have)

Design optimises for C. Everything else ships only if C validates (14-day usage gate).

## 2. Architecture

```
[Cowork workflows]                        [Google]                        [Phone / Laptop]
  Daily News Brief ──emits md + sidecar.json──┐
                                              │
                                              ├──► Sheet: daily_brief_latest, macro
                                              │
                                              └──► Telegram push (existing) + PWA URL

  Weekly Strategy Review ──emits ledger.json + .pdf──┐
                                                     │
                                                     ├──► Sheet: snapshot_caspar/sarah,
                                                     │         positions_caspar/sarah,
                                                     │         decision_queue, macro
                                                     │
                                                     ├──► Drive: WSR_Archive/YYYYMMDD_WSR.pdf
                                                     │
                                                     └──► Telegram push + PWA URL

                                         [PWA on GitHub Pages]
                                           Vite + React + Tailwind + vite-plugin-pwa
                                           Fetches CSV via Sheets "publish to web"
                                           Lists Drive folder
                                           Installed to iPhone home screen
```

Glue is `sync.py` — a standalone CLI invoked from the Cowork workflow prompts at end-of-run.

## 3. Repo layout

```
~/Documents/Trading/FinancePWA/
├── README.md
├── docs/plans/2026-04-15-portfolio-pwa-design.md   (this file)
├── src/
│   ├── sync.py                 # CLI: daily | wsr | auth
│   ├── sheets.py               # gspread wrapper + upsert/append helpers
│   ├── drive.py                # pydrive2 upload helper
│   ├── telegram.py             # raw requests POST
│   └── schema.py               # dataclasses mirroring the 7 Sheet tabs
├── pwa/                         # Vite scaffold (populated in S2)
├── .config/
│   ├── client_secret.json      # OAuth desktop client (gitignored)
│   └── .gitignore
└── .state/
    └── authorized_user.json    # OAuth refresh token (gitignored)
```

## 4. Sheet schema — reconciled to pipeline reality

| Tab | Columns | Source of truth | Written by |
|---|---|---|---|
| `snapshot_caspar` | date, net_liq_usd, cash, upl, upl_pct | `analysis_ledger.portfolio` | WSR sync |
| `snapshot_sarah` | date, net_liq_sgd, cash_sgd, upl_sgd, upl_pct | IBKR U16000287 via Chrome (weekly, manual session) | WSR sync |
| `positions_caspar` | date, ticker, qty, avg_cost, last, mkt_val, upl, weight | `analysis_ledger.portfolio.positions` | WSR sync |
| `positions_sarah` | date, ticker, qty, avg_cost, last, mkt_val, upl, weight | IBKR Chrome portfolio page, scraped | WSR sync |
| `decision_queue` | date, account, ticker, bucket, thesis_1liner, conv, entry, target, status | WSR md decision queue section | WSR sync |
| `daily_brief_latest` | date, bullet_1, bullet_2, bullet_3, verdict, sentiment | Daily brief sidecar JSON | Daily sync |
| `macro` | date, vix, dxy, us_10y, spx, usd_sgd | `analysis_ledger.macro` (WSR) / derived Daily | Daily + WSR sync |

Row policy: append with timestamp suffix on re-runs. No upsert. Audit trail preserved.

## 5. Integration points — what changes in Daily / WSR

### Daily News Brief
**New step before "Done":**
1. Emit `~/Documents/Trading/Daily News Brief/{YYYYMMDD}_brief.json`:
   ```json
   {"date":"YYYY-MM-DD","bullets":["...","...","..."],"verdict":"neutral","sentiment":"bullish"}
   ```
2. Shell: `python "~/Documents/Trading/FinancePWA/src/sync.py" daily --json {sidecar_path} --md {md_path}`
3. Existing Telegram push gets one extra line appended: `📱 PWA: https://<gh-pages-url>`

Macro values on Daily: best-effort. If Daily pipeline doesn't produce them natively, sync skips the macro row (WSR fills macro weekly).

### Weekly Strategy Review
**New step after PDF render:**
1. Shell: `python "~/Documents/Trading/FinancePWA/src/sync.py" wsr --ledger {ledger_path} --md {md_path} --pdf {pdf_path}`
2. `sync.py wsr` reads the ledger JSON for snapshot + positions + macro; parses decision queue from md body.
3. **Sarah snapshot** — added as a Pass-1.5 step before sync: Claude reads Sarah's IBKR Chrome portfolio (session pre-authenticated by Caspar on Monday morning), writes `ledger.sarah_portfolio`. Sync reads this alongside `ledger.portfolio` (Caspar).
4. WSR gets a new Telegram ping (none currently):
   ```
   📊 Weekly Strategy {YYYY-MM-DD} ready
   📱 PWA: https://<gh-pages-url>
   ```

### WSR pipeline spec addendum (separate follow-up)
- Extend `pipeline_spec.md` v0.4 → v0.5 to formalise Sarah as in-scope, add `sarah_portfolio` to ledger schema.
- This is required *before* Sheet writes for Sarah work. Blocking dependency for `snapshot_sarah`/`positions_sarah` tabs.

## 6. `sync.py` CLI spec

```
python sync.py auth
  # one-time: OAuth browser consent, cache token to .state/

python sync.py daily --json PATH --md PATH
  # writes daily_brief_latest + macro (best-effort)
  # modifies existing Telegram push to include PWA URL

python sync.py wsr --ledger PATH --md PATH --pdf PATH
  # writes snapshot_caspar, snapshot_sarah (if ledger.sarah_portfolio present),
  #        positions_caspar, positions_sarah, decision_queue, macro
  # uploads PDF to Drive folder
  # pings Telegram

python sync.py dryrun --fixture FIXTURE
  # runs the daily/wsr path against a synthetic fixture without network I/O
  # prints what would be written, for pre-flight verification
```

**Exit codes:** 0 = all sinks OK, 1 = partial failure (stderr lists which), 2 = fatal (auth / unreadable input).

**Config:** environment-based via `~/Documents/Trading/FinancePWA/.env`:
```
SHEET_ID=1N2AAx1GqTi23Qlq6MZkQoYfQOY7An1K0vvPx65YBiQc
DRIVE_FOLDER_ID=1e8WfNB4Je0aGVlm1Y_NThzlyrsYrWiJI
TELEGRAM_BOT_TOKEN=...     # from existing @Tron_shaft_bot
TELEGRAM_CHAT_ID=922547929
PWA_URL=https://<pending>.github.io/<repo>
```

**Idempotency:** append-with-timestamp; re-running Monday's WSR after a crash adds a second row, doesn't overwrite. Dashboard reads `latest row per date` via a view formula in the Sheet.

**Error isolation:** each sink (Sheet / Drive / Telegram) is wrapped independently. A Telegram outage does not block Sheet writes. Failures logged to `~/Documents/Trading/FinancePWA/.state/sync.log`.

## 7. PWA (S2) — skeleton spec

Home route only in v1. Four cards stacked:

1. **Daily Brief card** — date, 3 bullets, verdict chip (🟢/🟡/🔴 based on sentiment), sentiment label, last-updated time
2. **Caspar P&L card** — net liq USD, day change %, WTD/YTD, sparkline (S4)
3. **Sarah P&L card** — net liq SGD + USD-equivalent (via `macro.usd_sgd`), "as of {date}" stamp (weekly cadence)
4. **Household combined card** — Caspar USD + Sarah-USD-normalised, SPY delta YTD

Stack: Vite + React + Tailwind + vite-plugin-pwa. Deploy via GitHub Actions → gh-pages. Manifest installable; service worker caches CSV responses for 24h.

Data fetching: Sheets "publish to web" per tab → CSV URL. One fetch per tab, parsed client-side.

## 8. Staged roadmap + kill gates

| Stage | Where | Effort | Gate to advance |
|---|---|---|---|
| S0 Prereqs | — | Done ✓ | Sheet + Drive + OAuth + Sarah consent |
| S1 Sync layer | Cowork | 1 evening | Dry-run → Sheet tabs + Drive + Telegram verified |
| S1.5 WSR spec v0.5 | Cowork | 30 min | `pipeline_spec.md` updated; Sarah ledger schema locked |
| S2 Home PWA MVP | Claude Code | 1 weekend | Installed on iPhone home screen, opened ≥3×/week for 14 days |
| S3 Decisions tab | Claude Code | 1 evening | ≥1 decision state change logged in real WSR cycle |
| S4 History tab | Claude Code | 1 evening | Chart referenced in ≥1 weekly review |
| S5 Archive tab | Claude Code | 1 evening | (Cheap — ship if S4 clears) |
| S6 Polish | Claude Code | optional | Only if S2–S5 habitualised |

Kill criteria — if any gate fails by its own timeline, stop. Don't compound sunk cost.

## 9. Watch-outs

- **(Judgement, 0.8)** iOS PWA cache evicts after ~7 days idle. Telegram pings are the survival mechanism. If pings stop, cache dies, reinstall friction, behaviour dies.
- **(Judgement, 0.85)** Phone-first = font ≥16px, tap targets ≥44×44, no hover states. Tailwind mobile-first defaults handle this if not fought.
- **(Judgement, 0.7)** Google Sheets "publish to web" has prior deprecation history. 0.7 confidence of survival in 2 years. Fallback: Sheets API v4 with API key (still no OAuth for public tabs).
- **(Judgement, 0.75)** Sarah IBKR via Chrome is a weekly manual step. If the session expires mid-week, WSR Sarah snapshot fails silently — design has graceful degrade (skip Sarah row, surface warning in Telegram ping).
- **(Opinion)** The biggest failure mode is *not* technical. It is the PWA becoming a third artefact competing with Telegram + IBKR app for the same morning glance. If the Telegram message is already sufficient, the PWA is dead weight. Mitigate: keep Telegram body minimal — headline + link, no duplicated bullets.

## 10. Open decisions — resolved 2026-04-15

1. ~~Sarah consent~~ → full $ values (resolved, user)
2. ~~Service account vs OAuth~~ → OAuth user creds via `gspread.oauth()` (resolved, GCP org policy blocks SA key creation)
3. ~~Pipeline path for amendments~~ → Cowork workflow prompts, not Python files (resolved on discovery)
4. ~~Daily PDF to Drive~~ → No. Daily is md-only; Drive holds WSR PDFs only (auto-memory rule)
5. ~~Sarah daily snapshot cadence~~ → Weekly only (WSR). Daily snapshot is Caspar only.
6. ~~Dupe rows on re-run~~ → Append with timestamp suffix

## 11. Open decisions — still outstanding

1. **Verdict chip style** — emoji traffic-light vs sentiment word vs both?
2. **Household SPY delta** — YTD only, or also WTD/MTD?
3. **GitHub repo name and visibility** — public OK given Sarah consent + Caspar acceptance of public URL? Or private repo + public gh-pages?
4. **Currency display on household card** — always USD, or toggle USD / SGD?

These are S2 UI decisions. Don't block S1.

## 12. Confidence ledger

| Claim | Confidence |
|---|---|
| Architecture works end-to-end | 0.85 |
| S1 dry-run passes on first attempt | 0.7 |
| S2 ships in a weekend if focused | 0.7 |
| User opens PWA ≥3×/week past week 2 | 0.55 (down from 0.6 — adding Telegram PWA URL increases pass-through but risks Telegram being sufficient on its own) |
| Sheets publish-to-web survives 2 years | 0.7 |

---

## Next step

On approval: scaffold `FinancePWA/src/` with `sync.py`, `sheets.py`, `drive.py`, `telegram.py`, `schema.py`, `.env.example`, `README.md`, `.gitignore`. Then run `python sync.py dryrun --fixture ...` to verify Sheet/Drive/Telegram plumbing before the first real Daily or WSR run.
