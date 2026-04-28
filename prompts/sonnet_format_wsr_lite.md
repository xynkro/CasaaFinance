# Sonnet 4.6 — WSR Lite Formatter

Expand Opus 4.7's compressed JSON synthesis into the 6-section WSR Lite markdown that the PWA Mid-Week Pulse card and `wsr_lite_md_parser.py` both expect. **No new judgement** — formatting only.

## Input JSON

```json
{
  "date": "YYYY-MM-DD",
  "regime": "bull_late_cycle|...",
  "regime_unchanged": true|false,
  "regime_drift_text": "1-2 paragraph judgement on regime",
  "trigger_audit": [
    {"ticker": "TQQQ", "price": "$58.59", "status": "HIT|CLOSE|DORMANT",
     "trigger_value": "$52", "action": "Trim 5 shares on next bounce"}
  ],
  "options_book": [
    {"ticker": "AAPL", "strategy": "CSP", "strike": "$225", "dte": 21,
     "underlying": "$270", "proximity": "16% OTM",
     "flag": "🟢|🟡|🔴", "note": "Safe — collect to expiry"}
  ],
  "decision_queue": [
    {"rank": 1, "ticker": "SCHD", "entry": "$30.40", "last": "$31.10",
     "distance_pct": "+2.3%", "status": "ACTIONABLE|CLOSE|WAIT",
     "status_note": "always accumulating"}
  ],
  "catalysts": [
    {"day": "Mon Apr 28", "bullets": ["NFLX earnings", "Consumer confidence"]}
  ],
  "bottom_line": {
    "text": "1-3 sentence synthesis of the week",
    "confidence": 0.85,
    "tag": "Synthesis|Judgement|Opinion"
  }
}
```

## Output Format — exact template

Output ONLY the markdown below, no preamble, no code fences:

```
# WSR Lite — {date} ({day-of-week})

## Trigger Audit
{For each entry in trigger_audit:}
- **{ticker}** {price} — **{status}** (trigger {trigger_value}). {action}
{If empty: "- _no triggers active_"}

## Options Book Traffic Lights

| Ticker | Strategy | Strike | DTE | Underlying | Proximity | Flag | Note |
|--------|----------|--------|-----|------------|-----------|------|------|
{For each in options_book:}
| {ticker} | {strategy} | {strike} | {dte} | {underlying} | {proximity} | {flag} | {note} |

## Regime Drift

{regime_drift_text}

{If regime_unchanged is true and the text doesn't already say so, append:
"**REGIME UNCHANGED.** Label remains `{regime}`."}

## Decision Queue Status

| Rank | Ticker | Entry | Last | Distance % | Status |
|------|--------|-------|------|------------|--------|
{For each in decision_queue:}
| {rank} | {ticker} | {entry} | {last} | {distance_pct} | {status} — {status_note} |

## Catalyst Calendar — Next 3 Trading Days

{For each day in catalysts:}
- **{day}:** {Join bullets with ". "; if no bullets: "No major catalysts on the radar."}

## Bottom Line

{bottom_line.text} ({bottom_line.tag}) Confidence: {bottom_line.confidence}.
```

## Rules

1. **Do not invent rows.** If `trigger_audit` is empty, the section says "_no triggers active_".
2. **Tickers in CAPS, no $ prefix.** TSLA not $TSLA.
3. **Status keywords** must match exactly: `HIT`, `CLOSE`, `DORMANT`, `ACTIONABLE`, `WAIT`.
4. **Flag emojis** must be the exact unicode: 🟢 🟡 🔴 (no text equivalents).
5. **Currency / percent formatting** preserved verbatim from input.
6. **Bottom Line** must end with the exact phrase `Confidence: 0.85.` (with period, no extra text after).
7. **Section headers** must be H2 (`##`) and use the exact section names — `wsr_lite_md_parser.py` matches on these.

## Output Now
