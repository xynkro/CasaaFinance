# Wheel Alpha Trial — pre-registration

> **STATUS: RETIRED BEFORE START, 2026-09-28.** Precondition 1 failed. The
> pre-registered gate does not predict the outcome bucket, so H1 is refuted and
> the RETIRE rule below fires without a single position being opened. Details in
> "Precondition 1 result". The document is kept intact — the gates were written
> before the test and the test was run against them unchanged.

**Written 2026-09-26, BEFORE the trial runs. Do not edit the gates after the
first position opens.** Amendments go in the log at the bottom, dated, with a
reason. Changing a threshold after seeing results is how a losing strategy
survives its own evidence.

---

## Why this document exists, and why it is not the trial I first proposed

On 2026-09-26 the monthly `policy_audit` reported CSP at 81% win / +1.3% and CC
at 62% / +2.8%, holding almost exactly against the 2026-08-20 baseline. I read
that as "the wheel has an edge" and proposed a wheel-only paper trial.

Two checks killed that reading.

**1. The audit reports the wrong column.** `policy_audit.py:97` averages
`fwd_return_pct`, which is the *underlying stock's* move between scan and eval.
The realised option P&L lives in a different column, `outcome_pnl_pct`, written
by `csp_settle_pct` / `cc_settle_pct`. The win rates come from the P&L path and
the average returns come from the stock path, so the two columns of that table
describe different quantities. Corrected figures:

| leg | n | option P&L / cycle | sd | positive |
|---|---|---|---|---|
| CSP | 9,534 | **+1.01%** | 6.30 | 81% |
| CC  | 7,079 | **+1.78%** | 9.64 | 64% |

**2. Against SPY the edge disappears.** Pairing every evaluation with SPY's
total return over that position's *own* hold window (median 36 days):

| leg | alpha vs SPY | t |
|---|---|---|
| CSP | **-0.44% / cycle** | -6.78 |
| CC  | **+0.09% / cycle** | +0.76 |

The wheel made money because the market rose. Over this window SPY rose 6.9%,
and the wheel captured less of that than the index did. `paper_benchmark` says
the same thing from the other direction: -$1,232 realised against +$1,469 for
SPY-equivalent capital, 11 of 45 positions beating the index.

**A trial of the unconditional wheel would be pre-registering a known loser.**

## The finding the trial is actually built on

Bucketing by what SPY did over each hold:

| leg | SPY < -1% | SPY -1..+1% | SPY > +1% |
|---|---|---|---|
| **CSP** | alpha **+0.84%** (n=1513, t +4.13) | **+0.24%** (n=3878, t +2.49) | **-1.55%** (n=4143, t -17.01) |
| **CC**  | alpha **+1.27%** (n=1036, t +4.86) | **+0.61%** (n=3703, t +4.64) | **-1.27%** (n=2340, t -5.18) |

This is the structural signature of selling upside for premium: the wheel beats
the index when the index goes nowhere or falls, and loses when it rallies. The
aggregate -0.44% is an artifact of measuring across a window in which 43% of
CSP holds sat in rising tapes.

**The catch that defines the whole trial:** those buckets are cut on what the
market *did*, which is not knowable at entry. The table describes a property of
the strategy, not a tradeable rule. It becomes tradeable only if a signal
available at scan time predicts which bucket a position will land in.

## Primary hypothesis — the gate, not the P&L

**H1: the entry-time regime gate selects hold windows that resolve flat-or-down
more often than the unconditional base rate.**

Unconditional base rate across graded CSP evaluations: **57%** flat-or-down
(16% down, 41% flat, 43% up). H1 claims the gate lifts that to **>= 75%**.

H1 is primary because it is the necessary condition for everything else, and
because it is the only claim this account can actually test (see Power).

**Gate definition** — evaluated from the `regime_signals` and
`exposure_posture` rows carrying the scan date, both of which are already
written daily. Enter only when BOTH hold:
- `market_breadth` score < 50, **and**
- `exposure_posture.recommendation` != `RISK_ON`

The predicate is frozen here. If the fields turn out to carry values these
terms do not match, that is an amendment, logged and dated, made before any
position opens.

**H2 (secondary): mean paired alpha over gated positions > 0.**
Alpha per position = option P&L as % of collateral, minus SPY total return over
the identical hold window. Paired, so market beta cancels.

## Power — stated up front so nobody mistakes a small win for proof

Alpha sd in the favourable buckets is 6.0-8.5; take 7.5 blended.

| n | smallest alpha detectable at 80% power |
|---|---|
| 25 | +3.7% / cycle |
| 50 | +2.6% / cycle |
| 100 | +1.9% / cycle |

The alpha being hunted is +0.2% to +1.3%. Detecting +1.0% needs **n ~ 350**; at
8 concurrent positions on 36-day cycles that is roughly **four years**.

**So H2 cannot be confirmed by this trial and the trial does not attempt it.**
H2 exists to be *refuted* — a large negative is detectable quickly, a small
positive is not. Any read of an interim H2 number as vindication is a
misreading of this document.

H1 is different. Against a 57% base rate, detecting a lift to 75% needs
**n ~ 47**. That is reachable, which is why it is primary.

## Gates

Evaluated at **n = 50 gated positions closed**, and not before. No peeking
decisions; interim numbers may be looked at but may not trigger an action.

| outcome | condition | action |
|---|---|---|
| **RETIRE** | flat-or-down rate <= 57% (gate adds nothing over no gate) | Stop. The gate does not predict regime; the wheel stays unconditional and therefore stays beta-capped. |
| **RETIRE** | mean alpha < -2.1% / cycle (~2 se below zero — a break, not noise) | Stop regardless of H1. |
| **INVESTIGATE** | flat-or-down rate 58-74% | Gate has signal but misses the bar. Re-fit the predicate on the accumulated data, then re-register a fresh trial. No continuation under the old gates. |
| **CONTINUE** | flat-or-down rate >= 75% and mean alpha >= -2.1% | Keep accumulating toward n = 350 for H2. This is a continuation, not a pass. |
| **SCALE** | n >= 350 and mean alpha > 0 with t > 2 | The only condition under which real capital is discussed. Not reachable inside this trial. |

## Execution rules — frozen

- **Paper only.** Alpaca paper, `casaa-` prefixed. IBKR stays read-only. No
  change to either guardrail is in scope.
- **Legs:** CSP and CC only. `DISABLED_SPREAD_STRATS` stays as it is.
- **Ranking:** `annual_yield_pct`. `composite_score` is not used — it re-tested
  at correlation -0.089 on 2026-09-26, its third consecutive inverted reading.
- **Exits:** existing `src.paper_exits` discipline, unchanged (50% take, 2x
  stop, 21-DTE roll).
- **The GROWTH leg must stop minting positions.** It is what the paper book is
  actually full of today, and its momentum ranking is the same family as the
  measured-inverted composite. Leaving it running contaminates the sample.
- **Sizing:** equal notional per position, so no position can dominate the mean.
- **A cycle with no gate-passing candidate counts as a cycle.** Alpha is averaged
  over gated *opportunities*, not over trades taken, so a gate that fires rarely
  cannot flatter itself by selecting only its best days.

## Preconditions — the trial does not start until these are true

1. **Gate predicate verified** against real `regime_signals` /
   `exposure_posture` values, with the observed unconditional flat-or-down base
   rate recomputed and recorded here.
2. **GROWTH leg stopped.**
3. **`policy_audit` reports `outcome_pnl_pct`**, not `fwd_return_pct`, so the
   monthly number and this trial measure the same thing.
4. **The $2,321 NLV disagreement resolved.** Position sizing reads NLV; two
   writers currently disagree by ~21%.

---

## Precondition 1 result — 2026-09-28 — FAILED

**The pre-registered gate is partly vacuous.** `exposure_posture.bias` is
`NEUTRAL` on all 106 rows ever written, and `recommendation` only ever takes
`CASH_PRIORITY` (83) or `REDUCE_ONLY` (23). It has never been `RISK_ON`, so the
clause `recommendation != RISK_ON` is true on every day in history. The gate
reduces to `market_breadth score < 50`.

**The honest sample is 47 days, not 12,971 evaluations.** `regime_signals`
starts 2026-05-06, and the graded evaluations that overlap it collapse to **47
distinct scan dates**. The 12,971 evaluations are ~130 correlated observations
per day; t-statistics computed on them are inflated by roughly the square root
of that ratio. Everything below is computed at day level, one observation per
scan date.

**Result, against the RETIRE condition as written:**

| | flat-or-down | vs base | z |
|---|---|---|---|
| base rate (47 days) | 63.8% | — | — |
| **gate: breadth < 50** (23 days) | **60.9%** | **-3.0pp** | **-0.30** |

RETIRE reads "flat-or-down rate <= base rate (gate adds nothing over no gate)".
The gate scores *below* the base rate. **H1 is refuted; the trial does not run.**

**Exploratory predicates** — seven were tested, so read them as hypothesis
generation and nothing more:

| predicate | days | flat-or-down | z |
|---|---|---|---|
| posture == REDUCE_ONLY | 20 | 90.0% | +2.44 |
| breadth == Healthy | 17 | 88.2% | +2.09 |
| distribution in {SEVERE,HIGH} | 33 | 54.5% | -1.11 |
| breadth == Weakening | 17 | 47.1% | -1.44 |
| posture == CASH_PRIORITY | 27 | 44.4% | -2.10 |
| distribution == SEVERE | 17 | 17.6% | -3.96 |

Two clear the bar nominally, and neither survives scrutiny. Seven tests put a
Bonferroni-adjusted p on z=+2.44 at roughly 0.05 — borderline, on 20 days, in a
single five-month window. More damning is the direction: **Healthy** breadth
precedes *more* flat-or-down tape and **SEVERE** distribution precedes *less*,
both backwards from what the labels mean. A layer whose labels invert against
the next month is not a gate; it is the same failure mode already documented for
`composite_score` at correlation -0.089.

Re-registering REDUCE_ONLY as the gate would be selecting a predicate on its
outcome across seven tries. That is the practice this file exists to prevent.

**What would revive this.** A gate built from something with more than 47 days
behind it and a mechanism that is not this system's own scoring layer — realised
volatility, term structure, or SPY against its own moving average are all
computable from price history going back years. That is a new hypothesis and
needs its own pre-registration, written before it is tested.

## Amendment log

| date | change | reason |
|---|---|---|
| 2026-09-26 | Created. | — |
| 2026-09-28 | Status set to RETIRED BEFORE START. No gate edits. | Precondition 1 failed on the gate exactly as registered. |
