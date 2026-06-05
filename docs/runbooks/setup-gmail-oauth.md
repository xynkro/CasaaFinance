# ☀️ Morning checklist — turn on the Bloomberg email pipeline

Everything's built and committed; it's **inert until you do this once**. ~10–15 min, only the
parts that genuinely need *your* Google login. I can't do these for you (OAuth = your identity).

## Part 1 — Google Cloud (one-time, ~10 min)
1. Go to **console.cloud.google.com** → create a project (e.g. "casaa-gmail").
2. **APIs & Services → Library →** search **Gmail API → Enable**.
3. **APIs & Services → OAuth consent screen →** External → fill the minimum (app name, your email) →
   **Add yourself as a Test user** (your gmail). Save. (No verification needed for test users.)
4. **APIs & Services → Credentials → Create credentials → OAuth client ID →** type **Desktop app** →
   Create → **Download JSON** (call it `client_secret.json`).

## Part 2 — Mint the token (~2 min)
```bash
cd ~/Documents/Trading/FinancePWA
.venv/bin/pip install google-auth-oauthlib        # setup-only dep
.venv/bin/python scripts/gmail_oauth_setup.py ~/Downloads/client_secret.json
```
Your browser opens → pick your account → **Allow** (read-only Gmail). The terminal prints three lines:
```
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...
GMAIL_REFRESH_TOKEN=...
```

## Part 3 — Wire them in (~3 min)
- **Local:** paste the three lines into `.env` (gitignored — never commit).
- **CI:** GitHub repo → Settings → Secrets and variables → Actions → add the three as repository secrets.
- Tell me "token's in" and I'll add the three `GMAIL_*` env lines to the news/alerts workflow and flip it on.

## Verify
```bash
.venv/bin/python -c "from src import gmail_client as g; print(len(g.search('from:news.bloomberg.com newer_than:2d')), 'Bloomberg emails reachable')"
```
Non-zero = it's reading your inbox. Then the next cron pulls Bloomberg briefings into the macro "so what"
+ daily plan + PWA, and MF new-rec emails fire a "refresh" nudge.

---
### Prefer the 2-minute path instead?
If the Cloud-Console setup is annoying, there's a simpler alternative: a Gmail **App Password** + IMAP
(needs 2FA on your account; ~2 min, no Cloud project). Slightly broader scope (mail read+send vs read-only),
so I defaulted to the read-only OAuth you chose. Say the word and I'll swap the reader to IMAP.
