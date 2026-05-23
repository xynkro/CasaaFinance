# Options Trading Knowledge Base

> Compiled from OptionQuants Fundamentals Course (Sections 1-4), Natenberg, Sinclair (3 books), Bennett, Mack/Sinclair, Ariely, Silver.
> Purpose: Reference for CasaaFinance scoring engine optimization.
> Date: 2026-05-23

---

## 1. FOUNDATIONAL PRINCIPLES

### 1.1 What Options Actually Are

Options are volatility instruments. Direction is secondary.

**Core identity**: "When we trade options, we are fundamentally trading volatility. The directional view on a stock is often secondary to the view on the magnitude of its future price swings." (OQuants S1)

**Premium decomposition**:
```
Option Premium = Intrinsic Value + Extrinsic Value
Extrinsic Value = f(time_remaining, implied_volatility)
```

At expiration, extrinsic value = 0. ATM options have maximum extrinsic value. OTM options are 100% extrinsic.

**Implication for CasaaFinance**: Every CSP/CC we sell is a bet that IV > future RV. The scoring engine should center on this comparison, not on directional technicals alone.

### 1.2 Black-Scholes-Merton: Wrong But Useful

BSM is a translation layer, not a pricing oracle. Modern use: invert BSM to extract IV from market prices, creating a standardized comparison metric.

**Key assumptions that fail in practice**:
- Constant volatility (reality: smile/skew, term structure)
- Continuous trading (reality: overnight gaps, earnings jumps)
- Lognormal returns (reality: fat tails, negative skew)
- No transaction costs (reality: bid-ask eats edge)

**Practical value**: Converts noisy multi-dimensional option prices into single slow-moving parameter (IV). Enables cross-asset, cross-time comparison.

### 1.3 The Two Edges in Options

Every sustainable options strategy is either:

1. **Harvesting Risk Premia** (the insurance company model)
   - Persistent, high-capacity, well-known
   - Primary: Variance Risk Premium (VRP) -- IV > RV on average
   - Business analogy: commercial real estate (consistent rent collection)

2. **Exploiting Inefficiencies** (the detective model)
   - Fleeting, low-capacity, requires discovery
   - Examples: PEAD, index rebalancing, single-name vol mispricing
   - Business analogy: house flipping (opportunistic, not repeatable)

**CasaaFinance implication**: Our harvest scanner = VRP harvesting. Our daily scan should incorporate both. Core business = premium selling (VRP). Opportunistic overlays = PEAD, earnings vol, gov confluence catalysts.

---

## 2. VOLATILITY FRAMEWORK

### 2.1 Realized vs Implied Volatility

| Metric | Definition | Direction | Use |
|--------|-----------|-----------|-----|
| **Realized Volatility (RV)** | Actual historical price fluctuation | Backward-looking | Benchmark for IV comparison |
| **Implied Volatility (IV)** | Market's forecast of future vol, embedded in option prices | Forward-looking | What we're selling/buying |

**The VRP**: IV tends to exceed subsequent RV. This gap = Variance Risk Premium. Well-documented, persistent, rooted in structural demand for portfolio protection.

**Professional trading core**:
- IV > your RV forecast --> SELL options (premium too expensive)
- IV < your RV forecast --> BUY options (premium too cheap)

### 2.2 RV Estimator Hierarchy

From least to most efficient:

| Estimator | Inputs | Efficiency | Notes |
|-----------|--------|-----------|-------|
| Close-to-Close | Close prices only | Lowest | Ignores intraday; what we currently use |
| Parkinson | High, Low | Better | Captures intraday range |
| Garman-Klass | O, H, L, C | Good | Standard professional |
| Yang-Zhang | O, H, L, C + overnight gaps | Best | Handles gaps, most robust |

**CasaaFinance gap**: We use close-to-close HV30 everywhere. Should upgrade to Yang-Zhang for better RV estimates, especially for gap-prone stocks (earnings, biotech).

**Rule of 16**: Daily expected move ~ annualized vol / 16. Quick mental math for position sizing.

**Volatility scaling**: Vol scales with sqrt(time), not linearly.
```
Vol_T_days = sigma_annual * sqrt(T / 252)
```

### 2.3 Volatility Surface

The IV surface has two dimensions:

**Skew (across strikes at fixed expiry)**:
- Equity skew: OTM puts > ATM > OTM calls (downward-sloping smirk)
- Reflects negative skewness + fat-tail crash fear
- Steeper skew = more crash protection demand

**Term Structure (across expiries at fixed moneyness)**:
- **Contango** (normal): Long-term IV > short-term IV
- **Backwardation** (stressed): Short-term IV > long-term IV (acute fear/binary event)

**CasaaFinance gap**: Our `iv_surface_scan.py` fits a polynomial surface but doesn't score contango/backwardation state. Term structure slope is a VRP predictor (contango = better short-vol returns per OQuants S4).

### 2.4 Volatility Regimes & VIX

```
VIX < 15:  Low vol  -- aggressive premium selling OK
VIX 15-25: Standard -- normal parameters
VIX 25-35: Elevated -- reduce size, tighter delta
VIX > 35:  Crisis   -- no new short premium, buy protection only
```

Already implemented in `option_scanner.py` VIX_REGIME_RULES. Aligns with professional practice.

### 2.5 IV Rank / IV Percentile

**IV Rank** = (current_IV - 52w_low) / (52w_high - 52w_low) * 100
- Measures where current IV sits relative to its own range
- IVR > 50 = IV elevated relative to history = rich premium

**IV Percentile** = % of days in past year where IV was below current level
- More robust than rank (not distorted by single extreme)

**VRP Opportunity Predictors** (OQuants S4):
1. Higher IV/RV ratio correlates with better straddle returns
2. **Lower** 1-year IV percentile generally produces superior returns (counterintuitive)
3. Positive term structure slope (contango) predicts better short-vol returns

---

## 3. THE GREEKS -- RISK DASHBOARD

### 3.1 Framework: Dashboard, Not Edge

"Greeks are not predictive tools or trading strategies. They don't offer trading edge." (OQuants S1)

Greeks = car dashboard gauges:
- **Delta** = speedometer (directional exposure)
- **Gamma** = tachometer (exposure acceleration)
- **Vega** = fuel efficiency (volatility exposure)
- **Theta** = fuel tank drain (time cost)

Edge comes from better volatility forecast. Greeks describe the vehicle expressing that view.

### 3.2 Delta

**Definition**: Option price change per $1 underlying move.

**Three functions**:
1. **Equivalent stock position**: Portfolio delta +150 = owning 150 shares
2. **Hedge ratio**: Delta-neutral requires offsetting delta with shares
3. **Probability proxy**: ~probability of finishing ITM (not exact but practical)

**Key behaviors**:
- Calls: 0 (far OTM) to +1.0 (deep ITM)
- Puts: 0 (far OTM) to -1.0 (deep ITM)
- Higher vol/more time --> OTM deltas move toward 0.50, ITM deltas move toward 0.50
- ATM delta stable ~0.50 regardless of vol/time

**CSP delta selection** (literature):
- ArXiv 2508.16598: 25-30 delta optimal risk-adjusted for put writing
- Tastytrade: 20-30 delta for CSP, 10-16 delta for CC
- Our current target: CSP 0.27, CC 0.13 -- aligned with literature

### 3.3 Gamma

**Definition**: Rate of delta change per $1 underlying move. Second derivative.

**Critical insight**: Gamma is the source of convexity risk.

- **Long gamma** (long options): Favorable -- gains accelerate, losses decelerate
- **Short gamma** (short options): Unfavorable -- losses accelerate, gains decelerate

**Behavior**:
- Highest for ATM options
- Spikes dramatically approaching expiration (ATM becomes binary)
- Inversely proportional to underlying price ($50 stock > $200 stock for same delta)
- Higher vol / more time --> ATM gamma decreases (less binary), OTM gamma increases

**Short-gamma implication for CSP/CC sellers**: This is our core risk. We accept negative gamma in exchange for theta. Our scoring should account for gamma magnitude -- high-gamma positions (near-ATM, near-expiry) are more dangerous.

### 3.4 Theta

**Definition**: Daily time decay of option value.

**CRITICAL: THETA IS NOT AN EDGE**

"Theta is not profit/edge source. Theta is the payment for Gamma." (OQuants S1)

If options are fairly priced (IV = future RV), theta collection nets zero expected value. What looks like "theta profit" is actually VRP harvesting.

**"Theta Gang" Fallacy**: Systematic option selling works not because "theta pays you" but because IV > RV on average (VRP). You're implicitly forecasting volatility. If your IV/RV forecast is wrong, theta won't save you.

**Behavior**:
- Largest for ATM options
- Accelerates approaching expiration
- Higher IV --> higher theta (more premium to decay)

**Gamma-Theta relationship**: As expiration nears, gamma rises (more binary risk) but theta also rises (faster premium capture). They're mechanically linked -- you can't have one without the other.

### 3.5 Vega

**Definition**: Option price change per 1% IV change.

**Arguably most important Greek for professionals** -- direct measure of the primary forecasted variable.

**Behavior**:
- Highest for ATM options
- **Highest for LONGER-dated options** (unlike gamma which peaks at short-term)
- Long-dated options = "vega options" for pure vol plays
- Short-dated options = "gamma options" for convexity plays

**Second-order effects**:
- **Vanna** (dvega/dS): Most significant when slightly in/out of money
- **Volga/Vomma** (dvega/dVol): ATM options have near-zero volga; peaks at ~10 and ~90 delta

**CasaaFinance gap**: We don't track vega exposure at all. For CSP/CC sellers, vega tells us how much we lose if IV spikes (market crash, earnings surprise). Should factor into position sizing.

### 3.6 Greeks Near Expiration

In final days, smooth continuous model breaks down. Standard Greeks lose utility.

**Risk management shift**: From "What is my delta?" to "Will this option exercise?"

**Dominant risks**:
- **Pin Risk**: Stock near strike at expiration -- uncertain exercise
- **Assignment Risk**: Unwanted stock position overnight
- **Gamma explosion**: ATM delta swings 0-1 on slightest tick

Our `wheel_continuation.py` handles this (HOLD/EXPIRING_WORTHLESS/LIKELY_ASSIGNED states). Good architecture.

---

## 4. OPTION STRUCTURES & THEIR GREEKS

### 4.1 Structure != Strategy

Structure = payoff shape + Greek exposures. Strategy = thesis + structure + sizing + timing.

Professional process: (1) Formulate market opinion, (2) Select structure expressing that view.

### 4.2 Key Structures We Use

| Structure | Delta | Gamma | Theta | Vega | Primary Thesis |
|-----------|-------|-------|-------|------|---------------|
| Short Put (CSP) | + | - | + | - | Bullish/neutral, IV overpriced |
| Covered Call (CC) | + (reduced) | - | + | - | Neutral/mild bullish, IV overpriced |
| Long Call | + | + | - | + | Bullish, IV underpriced |
| Long Put | - | + | - | + | Bearish, IV underpriced |
| Short Straddle | ~0 | -- | ++ | -- | Pure short vol (stock stagnant) |
| Short Strangle | ~0 | -- | ++ | -- | Short vol with wider range |
| Iron Condor | ~0 | - | + | - | Short vol, defined risk |
| Credit Spread (PCS) | + | - | + | - | Directional + vol view, defined risk |
| Credit Spread (CCS) | - | - | + | - | Directional + vol view, defined risk |

### 4.3 Put-Call Parity

```
C - P = S - PV(K)
```

**Key insight**: Covered call and cash-secured put have identical payoff profiles at equivalent strikes/expirations. If someone rejects CSPs as "too risky" but sells covered calls, they don't understand their actual exposure.

**Synthetic positions**:
- Long call + short put = synthetic long stock
- Long put + short call = synthetic short stock

### 4.4 Iron Condor vs Short Straddle Edge Tradeoff (OQuants S4)

Wings reduce edge because:
1. Short-vol thesis assumes vol overpriced -- buying wings means paying overpriced protection
2. Volatility skew: OTM put IV higher than ATM, so you pay more for downside wing

**Edge on Margin comparison** (OQuants S4 live trades):
- IC typically better return-on-margin under rule-based margining
- Straddle captures more IV edge but uses much more margin
- Choice depends on margin type and willingness to delta hedge

---

## 5. PROFESSIONAL TRADING FRAMEWORK

### 5.1 Market Efficiency Reality

Markets are highly efficient by default but NOT perfectly efficient.

**Where retail traders find edge**:
1. **Risk premia harvesting** (VRP) -- getting paid to warehouse risk
2. **Longer time horizons** -- HFT edge dissipates at days/weeks/months
3. **Niche/less-liquid markets** -- too small for institutional capital
4. **Unique events** -- spinoffs, rebalancing, regulatory changes
5. **Behavioral exploitation** -- retail over-buying puts after crashes, OTM calls as lottery tickets

### 5.2 Expected Value Framework

```
EV = (P(Win) * Amount_Won) - (P(Lose) * Amount_Lost)
```

**Win rate is irrelevant in isolation**. A 20% win-rate strategy with large winners and small losers can be highly +EV. A 95% win-rate strategy can be -EV if the 5% losses are catastrophic.

**Implication for CSP selling**: Our ~85% win rate looks great but the tail losses (assignment at much lower prices) can overwhelm cumulative credits. Must size for tail risk.

### 5.3 Risk Management: Lifeline, Not Engine

"Risk management is your lifeline. But it is not the engine. Edge is the engine." (OQuants S3)

Risk management can't turn -EV into +EV. It preserves capital while edge plays out.

**Roulette fallacy**: Perfect risk management on American roulette (-$5.26 EV per $100 bet) just means slow, disciplined loss instead of fast one.

### 5.4 Adverse Selection

"Getting filled is information." If your "cheap" option limit order fills instantly, counterparty likely has better information.

**CasaaFinance gap**: Our scanners don't account for fill quality. Wide bid-ask spreads on harvest picks indicate adverse selection risk.

### 5.5 Edge Decay

Edges are not permanent. Markets adapt. What worked in 2022 may not work in 2026.

**Implications**:
- Continuously monitor strategy performance
- Don't assume historical VRP levels persist unchanged
- Single-name vol mispricing edges are the most fleeting

---

## 6. REAL TRADING MECHANICS (OQuants S4)

### 6.1 Account Management

| Metric | Definition | Target |
|--------|-----------|--------|
| Net Liquidity (NLV) | Mark-to-market liquidation value | -- |
| Maintenance Margin | Minimum equity to maintain positions | ~30% NLV for vol books |
| Excess Liquidity | Equity - maintenance margin | Buffer before forced liquidation |

**Margin guidelines**:
- General vol books (short options): ~30% of NLV
- Well-diversified, hedged: 35-45% of NLV
- De-risk threshold: ~50% of NLV

### 6.2 Position Sizing: Fractional Kelly

Full Kelly maximizes terminal wealth but produces 50%+ drawdowns. Real distributions have fatter tails than GBM assumes.

**Practical rule**: Use **5-10% of full Kelly** for VRP/short-vol trades.

Example:
```
Full Kelly suggests 30% of account
Applied: 5% * 30% = 1.5% of account per position
$110K account * 1.5% = ~$1,700 premium target
At $4.50 credit per contract = ~4 lots
```

**CasaaFinance alignment**: Our `option_scanner.py` uses Half-Kelly (50% of full Kelly). OQuants says 5-10% of Kelly for VRP trades. We may be oversized. Should evaluate.

### 6.3 Trade Selection Process

1. **Assess VRP opportunity**: IV/RV ratio, IV percentile, term structure slope
2. **Forecast RV**: What will realized vol actually be over option life?
3. **Size via Kelly**: Based on forecasted edge and its uncertainty
4. **Select structure**: IC vs straddle vs credit spread based on margin efficiency
5. **Execute with fill discipline**: Track effective fill IV, don't chase
6. **Monitor exit triggers**: RV spikes to approach sold IV; IV drops to baseline RV; sustained drift

### 6.4 Effective Fill IV

**Critical tool**: Prevents "chasing fills" by showing the IV actually sold.

Example from OQuants S4 live trades:
- GME IC filled at $0.99 credit --> effective fill IV = 35.23%
- Market IV was ~38.5%, RV forecast 32.5%
- Edge remaining: only ~2.7% above RV forecast
- If chased to $0.85 credit --> fill IV = 32.2% (BELOW RV forecast = negative edge)

**Lesson**: Walking orders down erodes edge. Set fill IV floor before execution.

### 6.5 Exit Triggers

1. **RV spikes** to approach sold IV (trade thesis invalidated)
2. **IV drops** to baseline RV (edge realized, take profit)
3. **Sustained drift** in one direction (loss despite low RV from delta exposure)
4. **DTE threshold** (mechanical close at 14-21 DTE)
5. **Profit target** (50% of max credit -- standard Tastytrade)

---

## 7. SINCLAIR'S 10 TRADING EDGES (Positional Option Trading)

### 7.1 Primary Edges for Our System

1. **IV forward curve predicting VRP returns**: Term structure slope = predictive. Contango = favorable for short vol. We should score this.

2. **Fundamental factors predicting cross-sectional option returns**: Fama-French factors correlate with option returns. Quality/value stocks tend to have better VRP characteristics.

3. **Post-Earnings Announcement Drift (PEAD)**: Stocks with large earnings surprises drift in that direction for days/weeks. Trade with vertical spreads.

4. **Volatility around earnings**: IV crush post-earnings is well-documented. But selling into earnings = binary event risk. Sinclair's nuance: trade the POST-earnings vol, not pre-earnings.

5. **Overnight volatility risk premium concentration**: VRP concentrates in overnight sessions. Day session vol may be priced differently.

6. **Pre-FOMC SPX drift**: SPX tends to drift up before FOMC announcements. Sell vol at announcement.

7. **Non-trading day mispricing**: Markets tend to underprice theta for weekends/holidays. Options decay 7 days/week but only trade 5.

8. **VVIX extremes**: When VIX-of-VIX (VVIX) is extremely high, subsequent VRP tends to be rich.

9. **Post-earnings reversal on large-move stocks**: Stocks that gap dramatically on earnings tend to mean-revert.

10. **Pre-announcement drift in late-reporting stocks**: Stocks reporting earnings after peers in same sector tend to drift in direction of sector's results.

### 7.2 Edges Relevant to CasaaFinance

| Edge | Currently Implemented? | Integration Path |
|------|----------------------|-----------------|
| VRP (IV > RV) | Partially (IVR gate in scanner) | Add IV/RV ratio comparison, term structure slope |
| PEAD | No | Could add to daily scan for long-call candidates |
| Earnings vol | Partially (vol_regime earnings_approaching) | Improve: sell AFTER earnings, not avoid entirely |
| Term structure slope | No | Add contango/backwardation scoring to technical_score |
| Weekend theta | No | Consider expiry selection favoring weekend capture |
| VVIX extremes | No | Add as VRP timing signal |
| Fundamental factors | No | Quality/value filters already exist in harvest gates |

---

## 8. BEHAVIORAL FINANCE INSIGHTS (Ariely + OQuants)

### 8.1 Cognitive Biases Exploitable in Options

- **Disposition Effect**: Traders sell winners too early, hold losers too long. Creates PEAD.
- **Availability Heuristic**: Over-buying puts after recent crash (IV spike above fair value = sell opportunity).
- **Herding**: Retail piling into OTM calls on meme stocks inflates call-side IV (good CC selling environment).
- **Overconfidence**: Traders underestimate tail risk, under-price OTM options in calm markets.

### 8.2 Our Own Behavioral Risks

- **Theta Gang fallacy**: Confusing theta collection with genuine edge
- **Anchoring**: Using historical VRP levels that may no longer apply
- **Overtrading**: Entering "No Trade Zone" positions (correctly-priced options = negative EV after costs)

---

## 9. SIGNAL & NOISE CONCEPTS (Silver)

### 9.1 Key Principles for Trading Systems

- **Overfitting danger**: More parameters != better prediction. Complex models that fit historical data perfectly fail out-of-sample.
- **Base rate neglect**: Must consider prior probability, not just current signal strength.
- **Calibration**: Forecasts should match reality in aggregate (if you say 70% probability, should be right ~70% of the time).
- **Foxes vs Hedgehogs**: Aggregators of many weak signals outperform single-thesis experts.

### 9.2 Implications for Scoring Engine

Our `technical_score.py` aggregates 14 signals with per-strategy weights. This is a "fox" approach -- good. But:
- Need to validate that signal weights are calibrated (not just intuitive)
- Should track prediction accuracy to detect regime changes
- Avoid adding more signals without backtested evidence they add value

---

## 10. NATENBERG CORE PRINCIPLES

### 10.1 Volatility-Centered Trading

"All other factors being equal, in a high implied volatility market a hedger should buy as few options as possible and sell as many options as possible. Conversely, in a low implied volatility market a hedger should buy as many options as possible and sell as few options as possible."

### 10.2 Dynamic Hedging

Constant portfolio rebalancing using Greeks. Key: maintain delta at optimal level for your thesis. For CSP/CC sellers: don't need to delta-hedge every tick, but should monitor portfolio delta for gross directional exposure.

### 10.3 Risk Management

"What separates the successful options trader from the unsuccessful one is the ability to survive such occurrences." -- Natenberg on tail events

Position sizing, stop-losses, and psychological resilience are survival tools, not edge generators.

---

## 11. GAP ANALYSIS: WHAT CASAAFINANCE IS MISSING

### Critical Gaps (High Impact)

| Gap | Current State | What Research Says | Priority |
|-----|--------------|-------------------|----------|
| IV/RV comparison | Not computed | Core of VRP edge -- must know if IV > RV | P0 |
| Term structure scoring | Not scored | Contango predicts better short-vol returns | P1 |
| Yang-Zhang RV estimator | Using close-to-close HV30 | 3-5x more efficient than close-to-close | P1 |
| Effective fill IV tracking | Not tracked | Chasing fills can eliminate edge entirely | P2 |
| Fractional Kelly sizing | Using half-Kelly | Literature says 5-10% of Kelly for VRP | P2 |
| Per-ticker earnings gating | Only macro-level blackouts | #1 blowup risk for retail CSP sellers | P0 |

### Moderate Gaps

| Gap | Current State | What Research Says | Priority |
|-----|--------------|-------------------|----------|
| Vega tracking | Not tracked | Critical for portfolio-level IV spike risk | P2 |
| PEAD integration | Not implemented | Well-documented directional edge | P3 |
| Weekend theta scoring | Not considered | Non-trading day theta consistently mispriced | P3 |
| VVIX timing | Not used | Extreme VVIX predicts rich VRP | P3 |
| Scoring unification | 3 parallel systems | Fragmented scoring loses signal coherence | P1 |

### What We're Doing Right

| Feature | Alignment |
|---------|-----------|
| VIX regime switching | Well-aligned with professional practice |
| CSP delta targets (25-30) | Matches ArXiv + Tastytrade research |
| CC delta targets (10-16) | Matches BXM index construction |
| Macro blackout gating | Correct: avoid FOMC/CPI/NFP |
| Support/resistance entry timing | Good: S/R levels improve CSP entry quality |
| IV rank gating (>30) | Directionally correct, threshold reasonable |

---

## 12. RECOMMENDED IMPLEMENTATION ROADMAP

### Phase 1: Core VRP Engine (Immediate)
1. Add IV/RV ratio computation per ticker
2. Upgrade HV30 to Yang-Zhang estimator
3. Add per-ticker earnings date check (finnhub/yfinance)
4. Wire IV/RV ratio into `technical_score.py` as primary signal

### Phase 2: Surface Intelligence (Week 2)
5. Score term structure slope (contango/backwardation) per ticker
6. Add skew steepness metric
7. Track portfolio-level vega exposure
8. Unify harvest/daily_scan/option_scanner scoring through `technical_score.py`

### Phase 3: Execution Quality (Week 3)
9. Implement effective fill IV calculation
10. Add bid-ask spread quality filter (adverse selection proxy)
11. Recalibrate position sizing to fractional Kelly (5-10%)
12. Add VVIX-based VRP timing signal

### Phase 4: Edge Expansion (Month 2)
13. Add PEAD detection for long-call candidates
14. Implement post-earnings vol selling (sell AFTER earnings, not before)
15. Weekend theta optimization for expiry selection
16. Backtest weight calibration against realized P&L

---

## SOURCES

### Course Material
- [OptionQuants Fundamentals S1](https://oquants.com/courses/options-fundamentals/section-1) -- Contract specs, BSM, Greeks, Structures
- [OptionQuants Fundamentals S2](https://oquants.com/courses/options-fundamentals/section-2) -- Volatility framework, RV estimators, surface, hedging
- [OptionQuants Fundamentals S3](https://oquants.com/courses/options-fundamentals/section-3) -- Market efficiency, EV, risk premia vs inefficiencies
- [OptionQuants Fundamentals S4](https://oquants.com/courses/options-fundamentals/section-4) -- Real trading, account management, position sizing, execution

### Books (Research Summaries)
- Natenberg, "Option Volatility & Pricing" -- [Review](https://kriminiltrading.com/blogs/must-read-economic-market-books/option-volatility-pricing-by-sheldon-natenberg-my-book-summary-review)
- Sinclair, "Volatility Trading" 2e -- [Bookey Summary](https://www.bookey.app/book/volatility-trading)
- Sinclair, "Option Trading: Pricing and Volatility Strategies" -- [Wiley](https://www.wiley.com/en-us/Option+Trading:+Pricing+and+Volatility+Strategies+and+Techniques-p-9780470497104)
- Sinclair, "Positional Option Trading" -- [Review](https://robotwealth.com/positional-option-trading-by-euan-sinclair-a-review/)
- Bennett, "Trading Volatility, Correlation, Term Structure and Skew" -- [Notes](https://moontowermeta.com/notes-on-trading-volatility-correlation-term-structure-and-skew/)
- Mack & Sinclair, "Retail Options Trading" (2024) -- [Amazon](https://www.amazon.com/Retail-Options-Trading-Andrew-Mack/dp/B0DL9YT831)
- Ariely, "Predictably Irrational" -- behavioral biases in trading decisions
- Silver, "The Signal and the Noise" -- forecasting methodology, overfitting, calibration
