# Architecture Strategy Q&A (2026-06-07)

Red-team analysis of three design questions Caspar raised. Tagged per `CLAUDE-INSTRUCTIONS.md`. TL;DR at the top of each.

---

## Q1 — Is Google Sheets the optimal source of truth?

**Answer:** No, not on pure engineering merit — **but keep it anyway, as the *write + hand-edit* layer, and add Firestore as the *private read* layer (already building).** A full migration off Sheets would be over-engineering at 2-user scale and would cost you the one feature no database gives cheaply: opening a tab and fixing data by hand in five seconds. (Synthesis, 0.8)

### Why Sheets is actually there (the real reasons — don't dismiss them)
- **Hand-editability** — you can inspect/correct any row in a familiar UI, instantly, from your phone. This is a *killer* feature for a solo operator and the single strongest argument to keep it. [Hard]
- **Zero infra, zero cost, zero ops** — no server, no DB to patch, no bill. [Hard]
- **Free read API** (gviz CSV) + simple `gspread` writes + Drive for PDFs. [Hard]

### Where it genuinely hurts (from the audit) — and that each flaw is *fixable without leaving Sheets*
| Flaw | Severity | Fix (stay on Sheets) |
|---|---|---|
| **Public-read leak** | 🔴 critical | Firestore serving-mirror (building now) + restrict sharing. The leak is a *sharing-mode artifact*, not inherent to Sheets. |
| **Write-concurrency 429s** | 🟡 | Stagger the cron schedule (audit fix) + existing backoff. |
| **Unbounded tab growth** | 🟡 | Schedule the existing `cleanup_dupes.py` janitor; row-cap history. |
| **Non-atomic `clear()`+rewrite** | 🟡 | Overwrite-in-place helper (audit fix). |
| **Everything is stringly-typed** | 🟢 | The `numeric()` boundary coercion already mitigates; schema dataclasses hold the contract. |

### Alternatives, honestly costed
| Option | Hand-edit | Cost | Write-concurrency | Atomic | Privacy | Solo-maintainability | Migration cost |
|---|---|---|---|---|---|---|---|
| **Sheets (today)** | ✅✅ best | free | ❌ weak | ❌ | ❌ public | ✅ familiar | — |
| **Sheets + Firestore read (plan)** | ✅✅ | free | ❌→ok* | ❌→ok* | ✅ | ✅ | low (in progress) |
| **Firestore as truth** | ❌ (need admin UI) | free→$ | ✅ | ✅ | ✅ | ⚠️ new model | high |
| **SQLite-in-repo / Turso** | ❌ | free | ⚠️ (single-writer / Turso fixes) | ✅ | ✅ | ⚠️ | high |
| **Postgres (Supabase/Neon)** | ❌ | free tier | ✅ | ✅ | ✅ (RLS) | ❌ real infra | high |

\* concurrency/atomicity stop mattering on the read side once the PWA reads Firestore; the write side stays on Sheets where 2-user + staggered cron is fine.

### Verdict
The **hybrid we're already building is the right architecture** (Synthesis, 0.8): Sheets = source of truth + hand-edit + cron-write; Firestore = private, fast, indexed read/serving layer. You keep Sheets' killer feature and neutralise its real flaws. **Don't migrate fully off Sheets** — at 2 users it buys atomicity/typing you can get cheaper with the audit fixes, while costing you hand-editability. Revisit *only* if: (a) you stop hand-editing, (b) write-concurrency keeps breaking *after* staggering, or (c) you onboard many more users. None apply today. (Judgement, 0.8)

**Counter-point / boundary:** if a year from now you find you *never* hand-edit and the cron-write concurrency is a recurring pain, the clean end-state is **Firestore-as-truth + a thin admin screen** — but that's a real build, not warranted now.

---

## Q2 — Justify the principles (and where they're actually wrong)

### "Paper-only — the human executes real trades"
- **Why:** capital protection on an *unproven* system; the hard paper-guard (`alpaca_paper_execute.py` refuses non-paper URLs, exit 2) makes an accidental live order structurally impossible. [Hard]
- **Sound?** Strongly yes. (Judgement, 0.9) Never let an unvalidated automated system touch real money. The `paper_benchmark` / `MF_SLEEVE`-vs-SPY alpha is the *gate*: it earns trust with a measured track record before you'd ever consider relaxing.
- **When to relax:** only after a long, honest paper track record, and even then to **semi-auto** (engine proposes → you one-tap confirm), never full-auto. 
- **Red-team / tension with the Northstar:** the Northstar is to *make money via timely intel* — paper-only can *cost* you money if it makes you slow to act on a good signal. The mitigation is **faster, sharper alerting** (Telegram + actionable deep-links), not auto-execution. So paper-only is correct *provided* the alert→action latency is low. That's the real thing to optimise, not the guard. (Judgement, 0.8)

### "Cron writes / PWA reads"
- **Why:** separation of concerns + security. Heavy, *authenticated* work (API pulls, scoring, sheet writes) runs server-side (GitHub Actions) where secrets live. The PWA is a dumb, cacheable, offline-capable read surface with **no secrets and no write credentials** — so even if the PWA is fully compromised, it can't corrupt your data. [Hard]
- **Sound?** Yes — this is good architecture; the no-write-path property is a *feature*. (Judgement, 0.85)
- **The one real cost (audit-confirmed):** PWA decisions (filled/killed/deferred) are **localStorage-only** — invisible to the engine and lost on cache-clear. So the engine can't learn from your actual choices (e.g. to grade its own signals). That's a deliberate scope cut, not a flaw — but it's the highest-value *future* feature: a private write path (Firestore write behind the auth we're adding) so your decisions feed `signal_feedback`. Gated correctly behind the privacy work happening now.

### "Telegram pushes"
- **Why:** you live on your phone; Telegram is the lowest-friction push channel (free, instant, rich formatting, topic-organised into your 4 forum topics) and *decouples* "engine found something" from "you happen to open the PWA." Push fits the Northstar's **timely** requirement. [Hard]
- **Sound?** Yes as primary. (Judgement, 0.85)
- **Red-team:** (1) single channel = single point of failure; (2) alerts aren't *actionable in-channel* — you still hop to the PWA/broker. **Augment, don't replace:** since we're adding Firebase anyway, **FCM web-push** is nearly free to add (alerts arrive even with the PWA closed), and alerts should **deep-link** straight to the relevant PWA decision to cut the alert→action latency that Q2-paper-only depends on. (Judgement, 0.75)

**Cross-cutting:** all three principles are sound. The two worth *evolving* (not discarding): close the decision-feedback loop (write path), and shrink alert→action latency (deep-linked/FCM alerts). Both compound the Northstar.

---

## Q3 — IBKR sync: why manual + authoritative, and can the new MCP automate it?

**Answer:** Yes — *more* than I'd have said before checking. The MCP exposes a **headless Web API backend** that can break the "needs TWS GUI running on the Mac" constraint. You can climb from "manual" to "mostly automatic," but IBKR's security model keeps a periodic human re-auth floor — that floor is the real reason it's "manual + authoritative," not a tooling gap. (Judgement, 0.75)

### Why it's manual + authoritative today
- **Authoritative:** IBKR is ground truth for what you *actually* hold — especially **new positions you opened that the cloud never saw**. So `ibkr_grab.py` *overwrites* the sheet rows (IBKR wins over stale cloud data). [Hard]
- **Manual:** the cloud (GitHub Actions) physically cannot reach your local TWS; discovery of new positions needs TWS running + IBKR auth on your Mac (the `com.caspar.ibkr-grab` LaunchAgent at 05:30 SGT, needing TWS). [Hard, from memory + audit]

### What I found probing the MCP (empirical, 2026-06-07)
`ibkr_check_status` → both backends down right now (you're asleep), but it revealed the MCP supports **two** backends and **three** connection paths:
1. **TWS Desktop** (port 7497 = *paper*; consistent with paper-only) — needs the GUI app running + daily login. *This is today's constraint.*
2. **Client Portal Gateway** (`IB_WEB_API_URL`) — a **headless** local/server process; no GUI. Still needs periodic re-auth (~daily), but can run on the Mac or a tiny VPS unattended between auths.
3. **Direct `api.ibkr.com`** (`IB_WEB_API_TOKEN`) — **fully headless, token-based** (IBKR OAuth Web API). No TWS, no GUI. *This is the real automation unlock* — if your account tier has Web API access enabled.

### The automation ladder (pick your rung)
| Rung | Setup | Autonomy | Remaining manual |
|---|---|---|---|
| **0 (today)** | TWS GUI + LaunchAgent | low | open TWS, daily login, Mac on |
| **1** | Migrate `ibkr_grab.py` → IBKR MCP calls | low-med | same, but cleaner code + on-demand sync from a session |
| **2** | **IB Gateway** (headless) + `IB_WEB_API_URL` + LaunchAgent | **med-high** | re-auth ~weekly; Mac/VPS on |
| **3** | `IB_WEB_API_TOKEN` → `api.ibkr.com` | **high (cloud-capable)** | enable Web API on the account; token lifecycle |

### The honest verdict
- **Can the MCP automate the sync?** Meaningfully, yes — rungs 2–3 get you from "manual, TWS+Mac" to "mostly automatic, periodic re-auth," and rung 3 could even let a *cloud* job sync (closing the original "cloud can't reach IBKR" gap). (Judgement, 0.75)
- **Can it be *fully* unattended forever?** No. IBKR deliberately forces periodic human re-auth (2FA) — that's the irreducible floor, and it's *why* "authoritative + a periodic human touch" is the correct design, not a defect. (Judgement, 0.8)
- **Recommendation (right-sized):**
  1. **Migrate `ibkr_grab.py` to the IBKR MCP** for cleaner reads + on-demand sync (I can pull positions when you ask, if a backend is up). Low effort, real win.
  2. If you want less manual: stand up **IB Gateway + `IB_WEB_API_URL`** (rung 2) on the Mac with auto-restart — drops you to ~weekly auth.
  3. Only pursue **rung 3 (`api.ibkr.com` token)** if you confirm your account has Web API/OAuth access — that's the path to true cloud-headless, but verify eligibility first; don't build for it speculatively. (Judgement, 0.7)
- **Keep IBKR authoritative regardless** — whatever the transport, IBKR data should still overwrite the sheet for position truth.

**Uncertainty flag:** I couldn't test live (backends down, you're asleep, and I won't connect/trade unattended). Rung-3 eligibility depends on your IBKR account type — confirm in Client Portal before I build toward it.

---

### Net actions for the morning
1. **Q1:** no migration — the Firestore-read hybrid we're building *is* the answer; just land it + the audit's cheap Sheets fixes (stagger cron, schedule janitor, atomic upsert).
2. **Q2:** principles stand; queue two evolutions — decision write-back (feedback loop) + FCM/deep-linked alerts (cut alert→action latency).
3. **Q3:** migrate `ibkr_grab.py` to the MCP; decide if IB Gateway (rung 2) is worth ~weekly-auth autonomy; check rung-3 Web API eligibility before building for it.
