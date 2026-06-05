# Email → News Pipeline (Bloomberg briefings + MF nudge) — Design

**Date:** 2026-06-06
**Status:** Built overnight for review — **inert until Caspar completes the one-time Gmail auth** (see runbook).

## Goal
Feed **Bloomberg email briefings** (paywall-free, content-rich, headless-readable) into the
existing `news_aggregator` pipeline, and fire a **Telegram nudge when Motley Fool emails a new
recommendation** (their emails are login-teasers — no ticker — so the nudge says "refresh MF in-session").
Engine input, never auto-signal — same guardrail as the rest of the system.

## Why email (recap)
- Bloomberg's *website* is hard-paywalled and the *RSS* is headlines-only. The **email briefings carry the
  actual content** ("Morning/Evening Briefing", "Five Things") and Gmail is readable headlessly.
- MF emails are teasers ("See the 10 Foundational Stocks →" + login link) — verified. So MF email can only
  *trigger a refresh nudge*, not deliver picks.
- NYT email is general news (The Morning/Evening) — skipped; the existing NYT Business RSS already covers markets.

## Access decision (chosen)
**Headless OAuth, `gmail.readonly` refresh token in CI.** Caspar does the one-time Google consent himself
(it's his account login — I can't). Env contract (CI secrets + `.env`, gitignored, never logged):
```
GMAIL_CLIENT_ID      GMAIL_CLIENT_SECRET      GMAIL_REFRESH_TOKEN
```
The whole feature is a **no-op when these are unset** — exactly like `fetch_newsdata()` without `NEWSDATA_API_KEY`.
So committing it tonight changes nothing until Caspar adds the token. (A simpler App-Password + IMAP path exists
as a ~2-min alternative if the Cloud-Console setup is annoying — see runbook note.)

## Architecture
```
scripts/gmail_oauth_setup.py   (one-time, local, Caspar runs → prints refresh token)
        │  GMAIL_* env
        ▼
src/gmail_client.py            (refresh token → access token → Gmail REST, raw requests, no new deps)
        │  reads recent mail
        ▼
news_aggregator.fetch_email_news()   →  Bloomberg emails → normalised news items
        │                                (id/datetime/headline/summary/source/url/category — same shape as RSS)
        ├─→ aggregate_rss() merges them in (called like fetch_newsdata) → macro "so what" + daily_plan + PWA
        └─→ MF new-rec email detected → telegram nudge "refresh MF in-session"
```

## Components
1. **`src/gmail_client.py`** — `_access_token()` (POST refresh_token → oauth2.googleapis.com/token),
   `search(query, max)` (Gmail `users.messages.list`), `get_plaintext(id)` (`users.messages.get` → decode
   text/plain). All via `requests` (already a dep). Returns `[]` and logs if `GMAIL_*` unset or any call fails
   (isolated, cron-safe). **`gmail.readonly` only.**
2. **`news_aggregator.fetch_email_news()`** — `gmail_client.search("from:news.bloomberg.com newer_than:1d")`,
   one news item per email: `headline=subject`, `summary=` first ~200 chars of meaningful plaintext (strip the
   `‌ ‌ ‌` spacer runs + "View in browser" boilerplate), `source="Bloomberg Email"`, `category="bloomberg-email"`,
   `datetime=` the email Date header, `id=_stable_id(msgid, subject)`. Wired into `aggregate_rss()` after `fetch_newsdata()`.
3. **MF nudge** — `mf_new_rec_emails(messages)` pure matcher: `from:fool.com` AND subject matches a
   rec pattern (`new recommendation`, `buy alert`, `new stock advisor pick`, `our next recommendation`) AND NOT
   marketing (`epic`, `order`, `password`, `% off`, `upgrade`). Fires `telegram.ping_curated_pick("refresh", ...)`
   (new kind: "🔔 New MF rec emailed — refresh in-session"). Runs in the `trigger_alerts` cron; dedupe by Gmail msg-id
   via the existing `news:{id}` sheet-key mechanism.

## Data flow & error handling
- No creds → every entrypoint returns `[]` / no-op. Zero behavioural change until the token exists.
- One bad email / API hiccup is isolated (try/except per message), same philosophy as `fetch_rss`.
- Dedup: `_stable_id` + the existing trigger_alerts `news:{id}` key → reruns idempotent.
- Freshness: `newer_than:1d` window; the 10-min cron catches each briefing within one cycle.

## Security
- `gmail.readonly` scope — cannot send mail, cannot touch Drive/Calendar.
- Token lives only in CI secrets + local `.env` (gitignored). Never logged, never committed, never echoed.
- Inert without creds, so the committed code carries no secret and no live access.

## Testing (no live Gmail)
- Pure `fetch_email_news` parser test: a captured Bloomberg email dict → expected news item (subject→headline,
  boilerplate stripped, category set).
- Pure `mf_new_rec_emails` matcher: real-rec subjects → matched; marketing/order/password subjects → not matched.
- `gmail_client` returns `[]` when env unset (no network in tests).

## Out of scope (YAGNI)
- Per-story parsing of a briefing (one item per email is enough for macro mood; revisit if needed).
- NYT email, WSJ email (RSS already covers; WSJ "What's News" could be a later add).
- Sending/labelling mail (readonly only).
