# Runbook — Refresh Motley Fool picks (in-session, ~monthly)

The Motley Fool **read** is the one step the headless crons can't do (the data is
behind a JS + login wall). So it's a deliberate **in-session, Claude-driven** refresh,
run roughly monthly (MF publishes ~1 new rec/month; Stock Advisor picks are 5-yr holds).

## Steps

1. **Open MF in Chrome MCP** (you're already logged in there):
   `https://www.fool.com/premium/my-services/stock-advisor`
   Then read the **Scorecard** tab; also visit **Foundational Stocks**, **New Recs**, **Rankings**.
   Use `read_page` / the structured DOM — do NOT `fetch()` authenticated endpoints
   (the Chrome-MCP safety layer blocks returning cookie-bearing responses).

2. **Emit `picks.json`** in this shape (Claude assembles it from what it read):

   ```json
   {
     "as_of": "2026-06-05",
     "foundational": ["AMZN", "INTC", "DDOG"],
     "new_recs": ["FPS"],
     "rankings": ["GLW", "MSFT"],
     "scorecard": [
       {"ticker":"FPS","price":64.04,"rec_date":"2026-06-05","type":"",
        "market_cap":"19.66B","adj_rec_price":64.59,"return_since_rec":null,
        "return_vs_sp":null,"div_rate":null,"moneyball":null},
       {"ticker":"GLW","price":197.70,"rec_date":"2026-05-22","type":"Cautious",
        "market_cap":"170.15B","adj_rec_price":191.60,"return_since_rec":3.19,
        "return_vs_sp":1.27,"div_rate":1.12,"moneyball":null}
     ]
   }
   ```

3. **Ingest → sheet:**
   ```bash
   .venv/bin/python scripts/ingest_curated_picks.py --from-json /abs/path/picks.json --dry   # preview
   .venv/bin/python scripts/ingest_curated_picks.py --from-json /abs/path/picks.json          # write
   ```
   This classifies every name into roles (core / watchlist / overlay / reference),
   writes the `curated_picks` tab, and fires **new-rec + overlay** Telegram pings for
   anything new vs the prior `curated_picks`.

4. **Verify:**
   - `curated_picks` tab populated (roles look right; `source=motley_fool`).
   - PWA: Home "Motley Fool" card, Decisions watchlist strip, Options overlay targets.
   - The **core-add** Telegram ping fires on the next `build_daily_plan` run when a
     Foundational name newly enters the equal-weight `mf_core` sleeve.
   - `paper_benchmark` shows an `MF_SLEEVE` row once an MF name is held in the paper book.

## Guardrails (don't break these)
- **Engine input, never auto-signal** — MF never triggers a trade by itself.
- **Equal-weight, capped** — the core sleeve is `MF_CORE_CAP` names, equal %.
- **Separate SPY benchmark** — the `MF_SLEEVE` row keeps it honest.
- **Paper only.**

## Why no cron
A headless GitHub Action can't log into MF. Cookie-replay expires in days for ~zero
benefit on monthly data. Chrome-MCP-in-session is the chosen path (see the design doc).
The crons DO consume the `curated_picks` sheet once it's written (plan sizing, PWA, pings).
