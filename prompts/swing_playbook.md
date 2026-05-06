# Swing Playbook — Distilled Pattern Logic

A cheat-sheet of the seven open-source TradingView swing-trading patterns
the brain references when synthesizing a thesis. The goal: when a chart
shows one of these patterns, NAME it in the thesis prose and apply the
corresponding rule. Stop the brain from hand-waving "looks healthy" — use
the named pattern instead.

Distilled from the public Pine Script bodies of work behind:
- LuxAlgo's Liquidity Swings + Swing Breakout indicators
- Zeiierman's Anchored VWAP family
- Jazal's Range Filter Buy/Sell
- O'Neil / Minervini Volatility Contraction Pattern (VCP)
- Mark Minervini's Stage 2 / 20EMA pullback rules

These are LOGIC distillations — not the actual Pine code. The brain reads
this file when it synthesizes a thesis and cites the pattern by name. The
named pattern becomes a contract: if observed, the rule applies.

---

## 1. Liquidity Sweep Pattern (LuxAlgo Liquidity Swings)

**What to look for:** Stops are clustering above an obvious resistance
level — old swing high, round number ($100, $50), prior breakout pivot.
Price wicks ABOVE that level in a single candle (the "sweep"), then
reverses HARD to close back inside the range. Volume on the sweep candle
is at least 1.5× the 20-day average. The reversal candle the next session
(or same session for intraday) closes red and gives back the wick.

**Why it works:** Stops above resistance get triggered, providing the fuel
for the immediate reversal. Smart money sells into that liquidity. The
sweep is a fakeout — those who chased the breakout are now trapped.

**Brain rule — DO NOT ENTER LONG AT OBVIOUS RESISTANCE.** If a held name
is approaching a clear horizontal resistance:
- Wait for the SWEEP + reversal candle before adding.
- If we already hold and price is sitting AT resistance with no sweep
  yet, do NOT add. Hold what you have.
- If a sweep occurs and we hold, consider TRIM into the wick.
- For new entries: a confirmed sweep + reversal is a high-probability
  short-side reversal. We don't short, so this becomes a NO-ADD signal,
  not a SHORT signal — the long side waits for the next pullback to
  support.

**Cite as:** "Liquidity sweep at $X — wait for reversal confirmation."

---

## 2. Swing Anchored VWAP (Zeiierman)

**What to look for:** A VWAP anchored to a meaningful pivot (recent swing
high, swing low, earnings date, breakout day) carries more weight than the
session VWAP. The anchor point matters: anchor from the LAST significant
event in the chart's recent history.

**Why it works:** Anchored VWAP integrates volume × price from the anchor
forward — every trader who entered since that pivot is collectively at
that average price. It becomes a magnet AND a battle line: above = bull
control, below = bear control.

**Brain rule — TREAT ANCHORED VWAP AS SOFT SUPPORT/RESISTANCE.**
- For a BUY_DIP candidate: if anchored VWAP from the last earnings
  release is at $X and price is also near $X, that's a high-quality
  entry zone — cite "anchored VWAP from earnings holds at $X" in the
  thesis.
- For a held position drifting down: anchored VWAP from the original
  entry serves as the line of "still in the trade." Below that line on
  high volume = thesis cracked, consider exit.
- For a CSP defending: anchored VWAP near the strike is a meaningful
  support — if it holds, assignment less likely than naive distance
  suggests.

**Cite as:** "Anchored VWAP from [event] holds at $X — soft support."

---

## 3. Swing Breakout Test & Retest (LuxAlgo)

**What to look for:** Price breaks above a clear horizontal resistance on
high volume. Then within 3-7 sessions, it pulls back to retest that
broken resistance from above — the level should now act as SUPPORT.
The retest closes WITHOUT breaking back below the level decisively.

**Why it works:** A breakout that holds on retest is the textbook
high-probability continuation pattern. The retest flushes weak hands and
confirms the level as legitimate support. Without the retest, breakouts
can fail; with it, the trend continuation has higher conviction.

**Brain rule — PREFER BREAKOUT ENTRIES THAT HAVE ALREADY RETESTED.**
- A new BUY_DIP on a name that just broke out yesterday: WATCH, don't
  enter. The breakout might fail without retest.
- A BUY_DIP on a name that broke out 5 days ago and is now retesting
  the breakout level from above: ENTER. This is the textbook setup.
- If price breaks back BELOW the retested level decisively (closes
  below on volume), the breakout is FAILED. Kill the thesis if we
  haven't entered yet, consider exit if we have.

**Cite as:** "Breakout above $X retesting now — high-quality entry."

---

## 4. Range Filter Buy/Sell (Jazal)

**What to look for:** A directional volatility-adjusted moving average
that stays "in" a regime until a TRUE break occurs. Until the filter
flips, the trend is intact regardless of intra-trend pullbacks. Common
implementation: smoothed range × multiplier creates an upper/lower
"acceptable noise" band; only when price closes outside the band does
the regime flip.

**Why it works:** Filters out the daily noise that traps swing traders
into reversing too early. A pullback inside the filter band is just
noise; a close outside is signal.

**Brain rule — DO NOT FIGHT THE RANGE FILTER DIRECTION.**
- If TV daily + weekly are both BUY/STRONG_BUY, the range filter is
  essentially "in" buy mode. BUY_DIPs on pullbacks are valid; SHORTS or
  early TRIMs are fighting the filter.
- If TV daily flips to SELL/STRONG_SELL while weekly stays BUY, the
  filter is potentially flipping. Cite as "watching for filter flip"
  and don't add aggressively.
- If both flip to SELL/STRONG_SELL, the regime has flipped — kill any
  pending BUY_DIPs on this name, consider TRIM if held.

This rule synergizes with the multi-timeframe confluence check: TV's
1d + 1W consensus IS a range filter approximation.

**Cite as:** "Range filter direction = [BULLISH/BEARISH/FLIPPING]."

---

## 5. Pullback to 20EMA (Minervini-style Stage 2 add)

**What to look for:** A name in an established uptrend (Stage 2 by
O'Neil/Minervini definition: price > 50EMA > 200EMA, all rising) pulls
back to its rising 20EMA on light volume. The 20EMA holds as support.
RSI typically dips into the 40-50 zone but doesn't break 30.

**Why it works:** In strong uptrends, the first pullback to the rising
20EMA is the highest-quality continuation entry. Strong hands buy the dip
to 20EMA; weak hands shake out. Volume should be LIGHT on the pullback
(not heavy distribution).

**Brain rule — 20EMA TOUCH IN UPTREND IS NOT DEFENSIVE, IT IS
OPPORTUNITY.**
- If a held position pulls back to its rising 20EMA in a Stage 2 trend,
  this is NOT a moment to TRIM — it's a moment to consider ADDING.
- For a new BUY_DIP candidate: 20EMA in an established uptrend is
  textbook entry. Cite "Pullback to 20EMA, Stage 2 intact."
- If 20EMA breaks decisively (closes 2%+ below on volume), Stage 2 may
  be ending — re-evaluate.
- TV's EMA20 column in tv_signals tells you the level directly. Distance
  from EMA20 (close vs EMA20) is the dip depth.

**Cite as:** "Pullback to 20EMA — Stage 2 intact, add candidate."

---

## 6. VCP (Volatility Contraction Pattern)

**What to look for:** A multi-week base where each subsequent pullback is
SHALLOWER than the previous, and volume DECLINES through the base. A
"tight handle" forms at the right edge — multiple sessions of tight
range with low volume. Then the breakout out of the handle on >1.5×
average volume marks the entry trigger.

**Why it works:** Sequential contraction = supply being absorbed.
Declining volume = sellers exhausted. The breakout candle is the
convergence of patient buyers stepping in once the right edge is set.

**Brain rule — VCP IS THE TEXTBOOK BREAKOUT ENTRY.**
- The vcp-screener feeds names already in this pattern. When proposing
  a BUY_DIP from screen_candidates with source=vcp, cite "VCP" in
  the thesis prose.
- Entry trigger: the pivot price (top of the handle). Entering before
  pivot is premature; entering above pivot on >1.5× volume is the
  textbook breakout.
- Stop: typically the bottom of the handle; never wider than 7-8% from
  pivot.
- If the breakout candle has weak volume (< 1× average), the breakout
  is suspect — demote to status=watching.

**Cite as:** "VCP base — pivot $X, entry on >1.5× volume breakout."

---

## 7. Multi-Timeframe Confluence (MTF)

**What to look for:** The 1d and 1W signals POINT THE SAME WAY. When
they align — both BUY, both STRONG_BUY, both NEUTRAL, etc. — the trade
has the wind at its back. When they diverge — daily BUY, weekly SELL —
the trade is fighting one timeframe.

**Why it works:** The market trend on 1W is the dominant force; 1d is
the tactical entry trigger. Trading WITH the weekly direction has higher
expectancy than trading against it.

**Brain rule — ENTRY ONLY VALID WHEN 1D AND 1W ALIGN DIRECTIONALLY.**
- Both BUY/STRONG_BUY → BUY_DIP on pullback is valid.
- Daily BUY + Weekly NEUTRAL → marginal, prefer waiting for weekly to
  flip BUY before adding.
- Daily BUY + Weekly SELL → DIVERGENCE. Do NOT propose new BUY_DIP.
  The weekly is bearish, the daily is just a counter-trend bounce.
  Cite "TF divergence — daily BUY but weekly SELL, no new entry."
- Daily SELL + Weekly BUY → also DIVERGENCE. Held positions on this
  pattern are at risk; consider trim.
- Both SELL/STRONG_SELL → regime is bearish on this name. Kill pending
  BUY_DIPs, consider TRIM on held positions.

This rule is enforced mechanically in the brain pipeline — see the
"TradingView consensus" section in `cron_wsr_full.md` and `cron_wsr_lite.md`.

**Cite as:** "MTF: daily=[X], weekly=[Y] — [aligned/divergent]."

---

## Brain reference checklist

When synthesizing a thesis, run through this checklist:

| Pattern | When to invoke | What to cite |
|---|---|---|
| Liquidity Sweep | Price approaching obvious resistance | "Wait for sweep + reversal" |
| Anchored VWAP | Significant pivot in recent history (earnings, swing low/high) | "Anchored VWAP from [event] at $X" |
| Breakout Retest | Recent breakout pulling back to broken level | "Breakout retest at $X" |
| Range Filter | Direction question on current trend | "Filter direction: [BULL/BEAR/FLIPPING]" |
| Pullback to 20EMA | Stage 2 uptrend with rising 20EMA | "Pullback to 20EMA, Stage 2 intact" |
| VCP | Multi-week base with declining volatility | "VCP base, pivot $X" |
| MTF Confluence | EVERY decision_queue entry | "MTF: daily=[X], weekly=[Y]" |

The MTF check should be on EVERY emission — it's the cheap sanity-check.
The other six are pattern-specific; cite them when observed, not by
default.

---

## What this playbook is NOT

- It is NOT a backtested system. It's distilled trader logic.
- It is NOT a replacement for the regime + exposure constraints. Those
  are the GATE; the playbook is the SHAPE of the entry inside the gate.
- It is NOT prescriptive. The brain still has discretion. The playbook
  just gives it named vocabulary so the user can audit the reasoning.
