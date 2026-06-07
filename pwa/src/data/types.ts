/**
 * data/types.ts — all row/shape interfaces and derived types for the data layer.
 *
 * Split out of the original monolithic ``src/data.ts``. Every type here is
 * re-exported from ``../data`` (data/index.ts) so existing
 * ``import { XxxRow } from "../data"`` statements keep resolving unchanged.
 *
 * These are pure type declarations (no runtime code) describing the CSV/Firestore
 * row shapes (strings, since both sources hand back strings) plus the client-side
 * derived shapes (summaries, trigger evaluation, the aggregate DashboardData).
 */

// ---------- typed rows ----------

export interface DailyBriefRow {
  date: string;
  bullet_1: string;
  bullet_2: string;
  bullet_3: string;
  verdict: string;
  sentiment: string;
  // Rich sections (optional — older rows may be blank)
  headline?: string;
  overnight?: string;   // pipe-separated bullets
  premarket?: string;
  catalysts?: string;
  commodities?: string;
  posture?: string;
  watch?: string;
  raw_md?: string;      // full original markdown brief
  // Structured chip fields (pipe-separated, from Finnhub + gov data)
  earnings_today?: string;
  macro_today?: string;
  negative_news?: string;
  insider_alert?: string;
  gov_confluence?: string;
}

export interface SnapshotRow {
  date: string;
  net_liq: string;
  cash: string;
  upl: string;
  upl_pct: string;
}

export interface PositionRow {
  date: string;
  ticker: string;
  qty: string;
  avg_cost: string;
  last: string;
  mkt_val: string;
  upl: string;
  weight: string;
}

export interface MacroRow {
  date: string;
  vix: string;
  dxy: string;
  us_10y: string;
  spx: string;
  usd_sgd: string;
}

export interface OptionRow {
  date: string;
  account: string;
  ticker: string;
  right: string;        // "C" | "P"
  strike: string;
  expiry: string;       // "YYYYMMDD"
  qty: string;
  credit: string;       // premium per share
  last: string;
  mkt_val: string;
  upl: string;
  underlying_last: string;
  moneyness: string;    // "ITM" | "ATM" | "OTM"
  dte: string;
  assignment_risk: string; // "LOW" | "MED" | "HIGH"
  wheel_leg: string;    // "CC" | "CSP" | "LONG_CALL" | "LONG_PUT"
  adj_cost_basis: string;
  momentum_5d: string;  // 5-day rate of change %
  trend_risk: string;   // "SAFE" | "DRIFTING" | "CONVERGING" | "BREACHING"
  confidence_pct: string;        // 0-100 probability of assignment
  confidence_reasoning: string;  // multi-factor explanation
  volatility_annual: string;
  rsi_14: string;
  sma_20: string;
  sma_50: string;
}

export interface WsrSummaryRow {
  date: string;
  source: string;
  verdict: string;
  confidence: string;
  regime: string;
  macro_read: string;
  action_summary: string;
  options_summary: string;
  redteam_summary: string;
  week_events: string;
  raw_md: string;
}

export interface OptionsDefenseRow {
  date: string;
  account: string;
  ticker: string;
  right: string;
  strike: string;
  severity: string;    // CRITICAL | HIGH | MEDIUM | INFO
  title: string;
  description: string;
  action: string;
  delta_info: string;
}

export interface ExitPlanRow {
  date: string;
  account: string;
  ticker: string;
  position_type: string;       // "STOCK" | "OPTION_CSP" | "OPTION_CC" | "OPTION_OTHER"
  category: string;            // "blue_chip" | "etf_broad" | "etf_commodity" | "etf_leveraged" | "speculative" | "option"
  is_blue_chip: string;
  entry: string;
  current: string;
  qty: string;
  upl_pct: string;
  stop_loss: string;
  stop_key: string;
  target_1: string;
  target_2: string;
  time_stop_days: string;
  days_held: string;
  profit_capture_pct: string;  // option: % of credit captured
  target_close_at: string;     // option: target close price
  status: string;              // HEALTHY/WARNING/STOP_TRIGGERED/T1_HIT/T2_HIT/BAG/TIME_STOP/PROFIT_TARGET_HIT/ROLL_OR_ASSIGN/STOP_ROLL/LET_EXPIRE/BREACH_WARNING/CATALYST_WARNING
  recommendation: string;
  reasoning: string;
}

export interface TechnicalScoreRow {
  date: string;
  ticker: string;
  close: string;
  trend: string;
  rsi_14: string;
  stoch_k: string;
  stoch_d: string;
  macd_hist: string;
  macd_cross: string;
  bb_pct_b: string;
  bb_squeeze: string;
  wvf: string;
  wvf_bottom: string;
  sma_20: string;
  sma_50: string;
  sma_200: string;
  support: string;
  resistance: string;
  fib_0236: string;
  fib_0382: string;
  fib_050: string;
  fib_0618: string;
  fib_0764: string;
  vol_ratio: string;
  vol_spike_type: string;
  candle_pattern: string;
  divergence: string;
  momentum_5d: string;
  momentum_20d: string;
  volatility_annual: string;
  catalyst_flag: string;
  vol_regime: string;
  earnings_date: string;
  earnings_days_away: string;
  score_buy: string;
  score_csp: string;
  score_cc: string;
  score_long_call: string;
  score_long_put: string;
  entry_exit_signal: string;
  top_drivers: string;
}

export interface WheelNextLegRow {
  date: string;
  account: string;
  ticker: string;
  current_right: string;
  current_strike: string;
  current_expiry: string;
  current_dte: string;
  current_status: string;
  next_action: string;
  next_strategy: string;
  next_right: string;
  next_strike: string;
  next_expiry: string;
  next_dte: string;
  next_delta: string;
  next_premium: string;
  next_yield_pct: string;
  next_breakeven: string;
  recommendation: string;
  reasoning: string;
  confidence: string;
}

export interface DecisionRow {
  date: string;
  account: string;
  ticker: string;
  bucket: string;
  thesis_1liner: string;
  conv: string;
  entry: string;
  target: string;
  status: string;
  strategy?: string;
  right?: string;
  strike?: string;
  expiry?: string;
  premium_per_share?: string;
  delta?: string;
  annual_yield_pct?: string;
  breakeven?: string;
  cash_required?: string;
  iv_rank?: string;
  thesis_confidence?: string;
  thesis?: string;
  source?: string;
  // Phase 5b — accumulation/tranche plan extension. `qty` is the total
  // planned share/contract count (string from sheet, parse to int). The
  // brain or risk_parity_recommend emits a pipe-separated tranche plan
  // ("5sh now | 5sh in 30d | 5sh on -5% pullback to $79.20") for share
  // recs; option recs leave it empty.
  qty?: string;
  accumulation_plan?: string;
  // Phase 6 — structured gates. JSON-encoded array of gate strings
  // (`["exposure:NEW_ENTRY_ALLOWED", "tv_daily:BUY"]`). Replaces the
  // string-includes parsing of accumulation_plan in evaluateTrigger().
  // Empty / missing = no gates.
  gates?: string;
}

export interface ArchiveRow {
  date: string;
  title: string;
  drive_file_id: string;
  drive_url: string;
}

/**
 * Regime signal row — daily output from Agent 1's regime cron.
 * One row per (date, source). source ∈ {market_breadth, ftd,
 * distribution_day, macro_regime}. score is 0-100; label is
 * source-specific (e.g. "FTD_CONFIRMED", "HIGH", "Concentration").
 */
export interface RegimeSignalRow {
  date: string;
  source: string;          // "market_breadth" | "ftd" | "distribution_day" | "macro_regime"
  score: string;           // 0-100
  label: string;           // source-specific label
  summary: string;
  raw_json: string;
}

/**
 * Exposure posture row — daily output from exposure-coach.
 * One row per date. recommendation gates new-entry flow.
 */
export interface ExposurePostureRow {
  date: string;
  exposure_ceiling_pct: string;     // 0-100
  bias: string;                     // "GROWTH" | "VALUE" | "NEUTRAL"
  participation: string;            // "BROAD" | "NARROW"
  recommendation: string;           // "NEW_ENTRY_ALLOWED" | "REDUCE_ONLY" | "CASH_PRIORITY"
  confidence: string;               // 0-1
  rationale: string;
  components_json: string;
}

/**
 * Screen candidate row — weekly output from vcp + canslim screeners.
 * Fresh-blood ticker pool the brain can pull from when proposing
 * BUY_DIP entries.
 */
export interface ScreenCandidateRow {
  date: string;
  source: string;          // "vcp" | "canslim"
  ticker: string;
  sector: string;
  score: string;
  trigger_price: string;
  stop_price: string;
  rationale: string;
}

/**
 * TradingView 26-indicator consensus per (ticker, interval).
 * Written daily by `scripts/tv_signals_run.py` for both 1d and 1W
 * intervals. The DecisionCard renders a small chip showing the
 * recommendation for both timeframes; the brain uses the same data
 * server-side for multi-timeframe confluence checks.
 */
export interface TvSignalRow {
  date: string;
  ticker: string;
  exchange: string;
  interval: string;             // "1d" | "1W" | "1M"
  recommendation: string;       // STRONG_BUY | BUY | NEUTRAL | SELL | STRONG_SELL | "ERROR: ..."
  buy_count: string;
  sell_count: string;
  neutral_count: string;
  score_all: string;            // -1.0 to +1.0
  score_ma: string;
  score_other: string;
  close: string;
  volume: string;
  change_pct: string;
  rsi: string;
  macd: string;
  macd_signal: string;
  ema20: string;
  ema50: string;
  ema200: string;
  adx: string;
  bb_upper: string;
  bb_lower: string;
  stoch_k: string;
  stoch_d: string;
  cci20: string;
}

/** Latest TV signals across the timeframes we pull (1h + 1d + 1W). */
export interface TvConsensus {
  hourly?: TvSignalRow;   // intraday confluence — flags 1d/1h divergence
  daily?: TvSignalRow;
  weekly?: TvSignalRow;
}

/**
 * Derived trigger state for a watching decision row. Computed client-side
 * (no backend changes) by `evaluateTrigger()`. Bridges the gap between
 * "Watching — waiting for trigger" and "Filled — already executed":
 *
 *   dormant  → trigger > 5% away. Cards stay quiet.
 *   close    → within 3% of trigger price. Amber chip surfaces.
 *   ready    → trigger hit but a gate (regime / TV / etc.) blocks. Blue chip.
 *   act_now  → trigger hit AND all gates clear. Red pulsing chip.
 *
 * Only watching-status rows get evaluated; other statuses return dormant.
 */
export type TriggerState = "dormant" | "close" | "ready" | "act_now";

export interface TriggerEvaluation {
  state: TriggerState;
  reason: string;
  triggerPrice?: number;
  currentPrice?: number;
  pctToTrigger?: number;        // signed: negative = need to move further
  blockingGates: string[];
}

/**
 * Live-price feed row — one upserted row per portfolio ticker. Written
 * every 5 min by `tv-prices.yml` (TradingView public scanner endpoint).
 * The PWA Portfolio overlays `last` onto position rows for near-realtime
 * mkt_val/UPL display, and `updated_at` powers the freshness chip.
 */
export interface LivePriceRow {
  ticker: string;
  exchange: string;       // "NASDAQ" | "NYSE" | "AMEX" | "SGX"
  last: string;           // current price (string from CSV; parse via numeric())
  change_pct: string;     // day-over-day % change
  volume: string;
  updated_at: string;     // SGT-anchored "YYYY-MM-DDTHHMMSS"
  source: string;         // "tv" | "yahoo"
}

/**
 * API usage / cost row — one per completed brain run. Populated by
 * `scripts/api_usage_scrape.py` (gh run view → parse claude-code-action
 * result JSON). Settings panel reads this for MTD spend + per-workflow
 * breakdown + recent runs table.
 */
export interface ApiUsageRow {
  date: string;            // SGT iso run completion
  run_id: string;
  workflow: string;        // "daily-brief" | "wsr-full" | "wsr-lite" | "market-scan"
  model: string;
  status: string;          // "success" | "failure" | "cancelled"
  num_turns: string;
  duration_ms: string;
  total_cost_usd: string;
  updated_at: string;
}

export interface GovConfluenceRow {
  date: string;
  ticker: string;
  confluence_score: string;
  contract_score: string;
  congress_score: string;
  insider_score: string;
  analyst_score: string;
  tier: string;
  recommended_strategy: string;
  recommended_action: string;
  thesis_oneliner: string;
  contributing_contracts: string;
  contributing_congress_trades: string;
  contributing_insider_buys: string;
  updated_at: string;
  investment_score?: string;
  // Materiality — how big the bet is vs the company (judge stock-impact)
  contract_usd?: string;          // 30d contract award total ($)
  contract_pct_rev?: string;      // contract_usd / TTM revenue (fraction)
  contract_pct_mktcap?: string;   // contract_usd / market cap (fraction)
  insider_usd?: string;           // 30d insider buy total ($)
  insider_pct_mktcap?: string;    // insider_usd / market cap (fraction)
  materiality?: string;           // HUGE | MATERIAL | NOTABLE | IMMATERIAL | ""
  market_cap?: string;            // company market cap ($), 0 if unknown
  ttm_revenue?: string;           // TTM revenue ($), 0 if unknown
  congress_usd?: string;          // 60d Congress buy total ($)
  congress_pct_mktcap?: string;   // congress_usd / market cap (fraction)
}

export interface DailyPlanRow {
  date: string;
  rank?: string;
  leg?: string;          // hedge | protector | growth | income
  ticker?: string;
  strategy?: string;     // ALLOC | CSP | CC | PCS | CCS | IC | LONG_CALL | GROWTH
  detail?: string;
  conviction?: string;
  target_pct?: string;
  notional?: string;
  reason?: string;
  source?: string;       // risk_parity | scan_results | screen_candidates
  execute?: string;      // "TRUE" = the auto-trader will place it
  fill_status?: string;  // "" | filled | held (at target) | skipped:<why> | failed:<why>
  updated_at?: string;
}

export interface MacroLeanRow {
  date: string;
  net_lean?: string;     // hawkish | dovish | risk_on | risk_off | neutral
  summary?: string;      // "Core CPI→hawkish · GDP→risk_on"
  updated_at?: string;
}

// One curated pick from an external human-vetted source (Motley Fool Stock
// Advisor today). Read in-session via Chrome MCP, classified into a role, fed
// to the engine as INPUT — never an auto-signal. Every MF surface in the PWA
// is read-only/reference; none of them trigger trades.
export interface CuratedPickRow {
  date: string; ticker: string; role: string; mf_type: string;
  rec_date: string; rec_price: string; market_cap: string;
  return_since_rec: string; return_vs_sp: string; moneyball_score: string;
  source: string; note: string; updated_at: string;
}

export interface GexRegimeRow {
  date: string;
  symbol: string;                 // SPY | QQQ
  spot?: string;
  net_gex?: string;               // net dealer dollar-gamma ($ per 1% move)
  gamma_flip?: string;            // zero-gamma spot level (0 if none)
  flip_distance_pct?: string;     // (spot − flip) / spot * 100
  call_wall?: string;             // resistance strike
  put_wall?: string;              // support strike
  regime?: string;                // POSITIVE_PINNED | NEGATIVE_TREND | NEUTRAL
  premium_gate?: string;          // SELL_OK | SELL_CAUTION | NORMAL
  note?: string;
  updated_at?: string;
}

export interface AlpacaSnapshotRow {
  date: string;
  net_liq: string;
  cash: string;
  buying_power: string;
  long_value: string;
  short_value: string;
}

export interface AlpacaPositionRow {
  date: string;
  ticker: string;       // equity symbol OR an OCC option symbol (NVDA260116P00100000)
  qty: string;
  avg_cost: string;
  last: string;
  mkt_val: string;
  upl: string;
  upl_pct: string;
  side: string;
  origin?: string;      // "casaa" = FinancePWA's own book | "external" = other bot (ZeroDTE/decisions)
}

export interface PaperBenchmarkRow {
  date: string;
  ticker: string;          // a position symbol, or "TOTAL"
  entry_date: string;
  days_held: string;
  cost_basis: string;      // capital base (deployed) for the SPY-equivalent
  position_pl: string;
  spy_return_pct: string;
  spy_equiv_pl: string;    // what the same capital would have made in SPY
  alpha_pl: string;        // position_pl − spy_equiv_pl
  beat_spy: string;        // "TRUE" | ""
}

/** Parsed OCC option contract. */
export interface ParsedOcc {
  underlying: string;
  expiry: string;       // "YYYY-MM-DD"
  right: "C" | "P";
  strike: number;
}

export interface HarvestScanRow {
  date: string;
  ticker: string;
  strategy: string;
  strike: string;
  expiry: string;
  dte: string;
  credit: string;
  annual_yield_pct: string;
  iv_rank: string;
  conviction: string;
  underlying_last: string;
  cash_required: string;
  breakeven: string;
  sr_context: string;
  macro_regime: string;
  vix: string;
  entry_signals: string;
  maintenance_signals: string;
  exit_signals: string;
  notes: string;
}

/**
 * Scan result row — ALL strategy candidates from the daily options scanner.
 * Strategies: CSP, CC, PCS, CCS, IC, PMCC, LONG_CALL.
 * The harvest_scan tab is a CSP-only subset; this tab is the full universe.
 */
export interface ScanResultRow {
  date: string;
  ticker: string;
  strategy: string;      // "CSP" | "CC" | "PCS" | "CCS" | "IC" | "PMCC" | "LONG_CALL"
  right: string;         // "P" | "C" | ""
  strike: string;
  expiry: string;        // "YYYYMMDD"
  dte: string;
  delta: string;
  premium: string;
  bid: string;
  ask: string;
  annual_yield_pct: string;
  cash_required: string;
  breakeven: string;
  iv: string;
  iv_rank: string;
  spread_pct: string;
  underlying_last: string;
  technical_score: string;
  composite_score: string;
  catalyst_flag: string;
  notes: string;         // multi-leg detail for IC/PCS/CCS/PMCC
}

export interface IvSurfaceScanRow {
  date?: string;
  ticker?: string;
  type?: string;        // "P" or "C"
  strike?: string;
  expiry?: string;
  dte?: string;
  spot?: string;
  iv?: string;
  iv_fitted?: string;
  iv_excess?: string;   // percentage points above fitted surface
  delta?: string;
  bid?: string;
  ask?: string;
  mid?: string;
  ann_yield_pct?: string;
  oi?: string;
  volume?: string;
  spread_pct?: string;
  assignment_risk?: string;  // "LOW" | "MEDIUM" | "HIGH"
  earnings_before_expiry?: string;
}

/**
 * Unusual Options Activity alert — one row per alert per day.
 * Scanner flags Vol/OI spikes, strike concentration, far-OTM flow,
 * and put/call skew across the watchlist universe.
 */
export interface UoaAlertRow {
  date: string;
  ticker: string;
  alert_type: string;      // "VOL_OI_SPIKE" | "STRIKE_CONC" | "OTM_FLOW" | "PC_SKEW"
  side: string;            // "CALL" | "PUT"
  strike: string;
  expiry: string;          // "YYYY-MM-DD"
  dte: string;
  volume: string;
  open_interest: string;
  vol_oi_ratio: string;
  implied_vol: string;     // 0-1 scale
  notional: string;        // dollar value of flow
  moneyness: string;       // "ITM" | "ATM" | "OTM" | "FAR_OTM"
  underlying_last: string;
  option_price: string;    // mid price per share (0 for PC_SKEW aggregates)
  severity: string;        // "1" | "2" | "3"
  detail: string;
}

export interface CongressTradeRow {
  audit_ts: string;
  filing_id: string;
  politician_id: string;
  politician_name: string;
  party: string;
  chamber: string;
  committees: string;
  ticker: string;
  issuer_name: string;
  transaction_date: string;
  filing_date: string;
  transaction_type: string;
  amount_min: string;
  amount_max: string;
}

/**
 * Earnings calendar row — one upserted per (ticker, year, quarter).
 * Refreshed daily by `finnhub-calendars.yml`. PWA Decision cards show
 * an earnings badge when ticker has earnings inside option DTE.
 */
export interface EarningsRow {
  date: string;            // YYYY-MM-DD earnings date
  ticker: string;
  hour: string;            // "bmo" | "amc" | "dmh"
  year: string;
  quarter: string;
  eps_estimate: string;
  eps_actual: string;
  revenue_estimate: string;
  revenue_actual: string;
  surprise_pct: string;
  updated_at: string;
}

/**
 * Economic calendar row — medium+high impact macro events for next 14
 * days. Refreshed daily. Drives "Macro this week" widget on Home.
 */
export interface EconomicEventRow {
  date: string;
  time: string;
  country: string;        // ISO-2
  event: string;
  impact: string;         // "low" | "medium" | "high"
  forecast: string;
  actual: string;
  previous: string;
  unit: string;
  updated_at: string;
}

/**
 * News sentiment row — company news with heuristic sentiment score.
 * Refreshed 4×/day. PWA Decision cards show a sentiment dot.
 */
export interface NewsSentimentRow {
  id: string;
  datetime: string;
  ticker: string;
  headline: string;
  summary: string;
  source: string;
  url: string;
  sentiment_score: string; // -1..+1
  sentiment_label: string; // "negative" | "neutral" | "positive"
  category: string;
  updated_at: string;
}

/**
 * Insider transaction row — SEC Form 4 filing. Refreshed 4×/day.
 * PWA Decision cards show insider flow icon when last 7d net signal.
 */
export interface InsiderTransactionRow {
  id: string;
  transaction_date: string;
  filing_date: string;
  ticker: string;
  name: string;
  shares: string;          // signed
  transaction_code: string;
  side: string;            // "buy" | "sell" | "grant" | ...
  transaction_price: string;
  value_usd: string;
  is_derivative: string;   // "TRUE" | "FALSE"
  shares_after: string;
  updated_at: string;
}

/**
 * Analyst consensus row — Wall St rating distribution. Refreshed
 * weekly. Drives analyst chip on Decision cards.
 */
export interface AnalystConsensusRow {
  ticker: string;
  period: string;
  strong_buy_count: string;
  buy_count: string;
  hold_count: string;
  sell_count: string;
  strong_sell_count: string;
  total_count: string;
  consensus_score: string; // -2..+2
  consensus_label: string; // "STRONG_BUY" | "BUY" | ...
  updated_at: string;
}

/**
 * Per-ticker insider summary over a window. Brain prompts use these
 * aggregates ("net side=buy >$1M last 7d → bullish confirm"); PWA
 * renders them as a single icon + tooltip.
 */
export interface InsiderSummary {
  ticker: string;
  net_buy_value: number;   // signed; positive = net buying
  buy_count: number;       // # of buy filings
  sell_count: number;      // # of sell filings
  largest_value: number;
  largest_name: string;
  latest_date: string;
}

/** Per-ticker latest news summary — most recent headline + max-magnitude sentiment. */
export interface NewsSummary {
  ticker: string;
  latest_datetime: string;
  latest_headline: string;
  latest_score: number;
  worst_score: number;     // most-negative score in window
  best_score: number;      // most-positive in window
  count_24h: number;
  count_72h: number;
}

export interface RiskParityAuditRow {
  date: string;
  account: string;                  // "caspar" | "sarah"
  asset_class: string;              // see 8-class taxonomy above
  capital_pct: string;              // 0-100 — share of NLV
  vol_pct: string;                  // annualized vol of the class
  risk_contribution_pct: string;    // 0-100 — share of portfolio risk
  target_pct: string;               // 0-100 — configured target
  delta_pct: string;                // capital_pct - target_pct (signed)
  rebalance_action: string;         // "OVERWEIGHT" | "UNDERWEIGHT" | "ON_TARGET"
  rebalance_amount_usd: string;     // suggested $ shift to close gap
  rationale: string;                // brain-readable note per row
}

// ---------- aggregate fetch ----------

export interface DashboardData {
  dailyHistory: DailyBriefRow[];
  daily: DailyBriefRow | null;
  caspar: SnapshotRow | null;
  sarah: SnapshotRow | null;
  casparPositions: PositionRow[];
  sarahPositions: PositionRow[];
  options: OptionRow[];
  technicalScores: TechnicalScoreRow[];
  technicalScoresHistory: TechnicalScoreRow[];  // full history for sparklines
  wheelNextLeg: WheelNextLegRow[];
  exitPlans: ExitPlanRow[];
  optionsDefense: OptionsDefenseRow[];
  wsrSummary: WsrSummaryRow | null;
  wsrLite: WsrSummaryRow | null;       // latest WSR Lite (Wed/Fri), source = "wsr_lite"
  decisions: DecisionRow[];            // latest day's decisions (active queue)
  decisionsAll: DecisionRow[];         // full history (sorted by date asc) — used by Review › Closed Decisions
  macro: MacroRow | null;
  // History (all rows, sorted by date ascending)
  casparHistory: SnapshotRow[];
  sarahHistory: SnapshotRow[];
  macroHistory: MacroRow[];
  archive: ArchiveRow[];
  // Regime + exposure (Agent 1's regime cron output)
  regimeSignalsLatest: Record<string, RegimeSignalRow>;  // keyed by source
  exposurePosture: ExposurePostureRow | null;
  screenCandidates: ScreenCandidateRow[];                // last 30d, both sources
  // TradingView consensus chip data — keyed by upper-cased ticker.
  tvSignals: Map<string, TvConsensus>;
  // Risk Parity LITE audit — latest day only (16 rows: 8 classes × 2 accounts).
  riskParityAudit: RiskParityAuditRow[];
  // Live price feed (TV scanner, 5-min refresh). PWA Portfolio overlays
  // these onto positions for near-realtime mkt_val/UPL.
  livePrices: Map<string, LivePriceRow>;
  livePricesUpdatedAt: string;
  // Finnhub-powered structured tabs (Phase 1-3). Brain consumes these as
  // input and emits summary fields; PWA also renders chips on cards.
  earnings: EarningsRow[];               // next 30 days, filtered universe
  economicEvents: EconomicEventRow[];    // next 14 days
  newsByTicker: Map<string, NewsSummary>;
  insiderByTicker: Map<string, InsiderSummary>;
  analystByTicker: Map<string, AnalystConsensusRow>;
  apiUsage: ApiUsageRow[];               // raw rows; Settings panel aggregates
  govConfluence: GovConfluenceRow[];     // today's gov confluence signals (score ≥ 10)
  congressTrades: CongressTradeRow[];    // recent politician trades (last 7 days)
  uoaAlerts: UoaAlertRow[];              // unusual options activity (latest day)
  harvestScan: HarvestScanRow[];        // premium harvest picks (today)
  scanResults: ScanResultRow[];         // all strategy candidates (today) — CSP/CC/PCS/CCS/IC/PMCC/LONG_CALL
  ivSurfaceScan: IvSurfaceScanRow[];
  alpaca: AlpacaSnapshotRow | null;
  alpacaPositions: AlpacaPositionRow[];
  paperBenchmark: PaperBenchmarkRow[];   // "did each pick beat SPY?" (latest day, incl. a TOTAL row)
  gexRegime: GexRegimeRow[];             // dealer gamma regime per index (latest day: SPY, QQQ)
  dailyPlan: DailyPlanRow[];             // the unified plan the auto-trader executes (latest day)
  macroLean: MacroLeanRow | null;        // today's macro-surprise lean (tilts the plan sizing)
  curatedPicks: CuratedPickRow[];        // raw curated picks, latest day (Motley Fool today)
  mfWatchlist: CuratedPickRow[];         // role=watchlist — research, not a buy
  mfOverlay: CuratedPickRow[];           // role=overlay — CSP-entry targets (suggestion-only)
  mfReference: CuratedPickRow[];         // role=reference — Scorecard, reference only
  error: string | null;
}
