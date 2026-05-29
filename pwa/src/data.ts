import Papa from "papaparse";

const SHEET_ID = "1N2AAx1GqTi23Qlq6MZkQoYfQOY7An1K0vvPx65YBiQc";

function csvUrl(gid: string): string {
  return `https://docs.google.com/spreadsheets/d/${SHEET_ID}/gviz/tq?tqx=out:csv&gid=${gid}`;
}

/** Fetch by sheet name instead of GID — for tabs whose GID isn't known. */
function csvUrlByName(sheetName: string): string {
  return `https://docs.google.com/spreadsheets/d/${SHEET_ID}/gviz/tq?tqx=out:csv&sheet=${encodeURIComponent(sheetName)}`;
}

const GIDS: Record<string, string> = {
  daily_brief_latest: "1490893125",
  snapshot_caspar: "1233934747",
  snapshot_sarah: "1953218382",
  positions_caspar: "981534946",
  positions_sarah: "444641294",
  decision_queue: "1744723757",
  options: "326503132",
  technical_scores: "657341624",
  wheel_next_leg: "805863395",
  exit_plans: "515412556",
  options_defense: "1717646002",
  wsr_summary: "607663282",
  macro: "447436838",
  wsr_archive: "1065773181",
  // Quant regime layer — populated by regime-signals.yml daily 22:00 UTC.
  // regime_signals: market_breadth + ftd + distribution_day + macro_regime
  // exposure_posture: exposure-coach output (ceiling, recommendation, headroom)
  regime_signals: "1037039714",
  exposure_posture: "1572953132",
  // screen_candidates created on first Sunday cron run — placeholder until then.
  screen_candidates: "1773922612",
  // TradingView 26-indicator consensus, populated daily by tv-signals.yml.
  // One row per (ticker, interval) — both 1d and 1W. The DecisionCard reads
  // the latest 1d + 1W row per ticker for the consensus chip.
  tv_signals: "1954107259",
  // Risk Parity LITE — diversification hygiene audit. Written daily at
  // 22:45 UTC by risk-parity-audit.yml. 8 asset classes × 2 accounts =
  // 16 rows per run. Live GID resolved via gspread on 2026-05-07.
  risk_parity_audit: "1398209766",
  // Live price feed — written every 5 min by tv-prices.yml using
  // TradingView's public scanner endpoint. UPSERT semantics, one row
  // per portfolio ticker. PWA Portfolio overlays this on positions for
  // near-realtime mkt_val/UPL display.
  live_prices: "666282627",
  // Finnhub-powered tabs (Phase 1-3 of Strategy reliability rollout).
  // earnings_calendar: per (ticker, year, quarter) UPSERT, 30-day
  //   lookahead, filtered to portfolio + watchlist (~84 tickers). Drives
  //   the Earnings badge on Decision cards + "This week" Home widget.
  // economic_calendar: medium+high impact macro events for next 14
  //   days, US/EU/CN/JP/SG only. Drives "Macro this week" Home widget.
  // news_sentiment: company-news rows last 14 days per ticker with
  //   heuristic sentiment score. Drives the news dot on Decision cards.
  // insider_transactions: SEC Form 4 filings last 90 days per ticker.
  //   Drives the insider flow icon when last 7d net is meaningful.
  // analyst_consensus: latest Wall Street recommendation distribution
  //   per ticker. Drives the analyst chip on Decision cards.
  earnings_calendar: "1062081514",
  economic_calendar: "1783608533",
  news_sentiment: "1115837697",
  insider_transactions: "511704782",
  analyst_consensus: "991986564",
  // Anthropic API usage + cost log per brain run. Populated by
  // scripts/api_usage_scrape.py parsing claude-code-action's result
  // JSON. Settings tab renders MTD spend + per-workflow breakdown.
  api_usage: "1292394805",
  gov_confluence_signals: "1590812475",
  congress_trades: "870416250",
  snapshot_alpaca: "2094087184",
  positions_alpaca: "1331088115",
  harvest_scan: "1619087431",
  iv_surface_scan: "1665887293",
};

async function fetchTab<T>(tab: keyof typeof GIDS): Promise<T[]> {
  const res = await fetch(csvUrl(GIDS[tab]));
  if (!res.ok) throw new Error(`Sheet fetch failed: ${tab} (${res.status})`);
  const text = await res.text();
  const { data } = Papa.parse<T>(text, { header: true, skipEmptyLines: true });
  return data;
}

/** Fetch a tab by sheet name (for tabs without a known GID). */
async function fetchTabByName<T>(sheetName: string): Promise<T[]> {
  const res = await fetch(csvUrlByName(sheetName));
  if (!res.ok) throw new Error(`Sheet fetch failed: ${sheetName} (${res.status})`);
  const text = await res.text();
  const { data } = Papa.parse<T>(text, { header: true, skipEmptyLines: true });
  return data;
}

// ---------- numeric coercion at the data boundary ----------

/**
 * Coerce a string|undefined sheet cell to a number with a stable fallback.
 * Replaces ad-hoc `Number(x) || 0` / `if (!v) continue` / unguarded `Number()`
 * patterns scattered across consumer cards.
 *
 * Rules:
 * - undefined/null/empty-string → fallback
 * - "NaN" / non-numeric strings → fallback
 * - Anything `Number()` parses successfully → that number (zero is preserved)
 *
 * Fallback default is 0; pass `null` if you need to distinguish "no data"
 * from "zero" (e.g. price-charts that should skip the point entirely).
 */
export function numeric(v: string | undefined | null, fallback = 0): number {
  if (v === undefined || v === null || v === "") return fallback;
  const n = Number(v);
  return Number.isNaN(n) ? fallback : n;
}

/**
 * Same as numeric() but returns null for missing/invalid — useful when
 * the consumer wants to filter the row out entirely rather than show 0.
 */
export function numericOrNull(v: string | undefined | null): number | null {
  if (v === undefined || v === null || v === "") return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

/**
 * Normalize snapshot rows from either account's CSV headers into the
 * generic SnapshotRow shape.  Caspar's sheet uses `net_liq_usd` / `cash`,
 * Sarah's uses `net_liq_sgd` / `cash_sgd` / `upl_sgd`, but the frontend
 * expects `net_liq` / `cash` / `upl` everywhere.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeSnapshot(rows: any[]): SnapshotRow[] {
  return rows.map((r) => ({
    date: r.date ?? "",
    net_liq: r.net_liq ?? r.net_liq_usd ?? r.net_liq_sgd ?? "0",
    cash: r.cash ?? r.cash_sgd ?? "0",
    upl: r.upl ?? r.upl_sgd ?? "0",
    upl_pct: r.upl_pct ?? "0",
  }));
}

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
  status: string;              // HEALTHY/WARNING/STOP_TRIGGERED/T1_HIT/T2_HIT/BAG/TIME_STOP/PROFIT_TARGET_HIT/ROLL_OR_ASSIGN/LET_EXPIRE/BREACH_WARNING/CATALYST_WARNING
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
 * Derive a real-time trigger state from a decision row + live data.
 *
 * The brain writes a "watching" row with `entry` set to the price level
 * it wants to act at, and an `accumulation_plan` that may reference
 * regime gates (NEW_ENTRY_ALLOWED) or TV signal gates (TV daily=BUY).
 * This function compares live data against those gates so the PWA can
 * show "ACT NOW" the moment the conditions are met — instead of
 * waiting for the next WSR re-emission to flip status to pending.
 */
/**
 * Parse the gates JSON field on a decision row. Returns an empty array
 * for empty / malformed input (the evaluator then falls back to the
 * legacy accumulation_plan string parsing).
 */
function parseStructuredGates(gatesStr: string | undefined): string[] {
  if (!gatesStr) return [];
  try {
    const parsed = JSON.parse(gatesStr);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((g): g is string => typeof g === "string" && g.length > 0);
  } catch {
    return [];
  }
}

/**
 * Evaluate a single gate against live data. Returns a non-empty string
 * describing the block when the gate is NOT satisfied, or empty string
 * when it passes. Unknown gate types pass through with a "manual gate"
 * note so the user knows there's something to check.
 *
 * Recognised gate types:
 *   - exposure:<value>      e.g. "exposure:NEW_ENTRY_ALLOWED"
 *   - tv_daily:<value>      e.g. "tv_daily:BUY"   (matches BUY or STRONG_BUY)
 *   - tv_weekly:<value>     same shape as tv_daily
 *   - earnings_clear        no value; flagged manual (PWA doesn't have DTE-aware ticker map yet)
 *   - regime_above:<score>  not yet wired — passes with note
 */
function evaluateGate(
  gate: string,
  exposurePosture: ExposurePostureRow | null,
  tvConsensus: TvConsensus | undefined,
): string {
  const [rawType, ...rest] = gate.split(":");
  const type = (rawType || "").trim().toLowerCase();
  const required = rest.join(":").trim().toUpperCase();

  if (type === "exposure") {
    const rec = exposurePosture?.recommendation?.toUpperCase();
    if (!rec) return `exposure unknown, need ${required}`;
    if (rec !== required) return `exposure ${rec}, need ${required}`;
    return "";
  }
  if (type === "tv_daily") {
    const tvRec = (tvConsensus?.daily?.recommendation || "").toUpperCase();
    if (!tvRec) return `TV daily unknown, need ${required}`;
    // BUY required matches both BUY and STRONG_BUY; SELL matches both SELL forms.
    const ok = required === "BUY"
      ? tvRec.includes("BUY")
      : required === "SELL"
      ? tvRec.includes("SELL")
      : tvRec === required;
    return ok ? "" : `TV daily=${tvRec}, need ${required}`;
  }
  if (type === "tv_weekly") {
    const tvRec = (tvConsensus?.weekly?.recommendation || "").toUpperCase();
    if (!tvRec) return `TV weekly unknown, need ${required}`;
    const ok = required === "BUY"
      ? tvRec.includes("BUY")
      : required === "SELL"
      ? tvRec.includes("SELL")
      : tvRec === required;
    return ok ? "" : `TV weekly=${tvRec}, need ${required}`;
  }
  if (type === "earnings_clear") {
    // Brain has already filtered DTE conflicts at decision-emit time;
    // nothing to re-check client-side. Pass.
    return "";
  }
  // Unknown gate — surface as manual check instead of silently passing.
  return `manual gate: ${gate}`;
}

export function evaluateTrigger(
  decision: DecisionRow,
  currentPrice: number | undefined,
  exposurePosture: ExposurePostureRow | null,
  tvConsensus: TvConsensus | undefined,
): TriggerEvaluation {
  const empty: TriggerEvaluation = {
    state: "dormant",
    reason: "",
    blockingGates: [],
  };

  if ((decision.status || "").toLowerCase() !== "watching") return empty;

  const entry = Number(decision.entry);
  if (!entry || !currentPrice) return { ...empty, reason: "no price data" };

  const strategy = (decision.strategy || "").toUpperCase();
  // Direction: BUY_DIP / CSP / LONG_PUT-on-puts wait for the underlying
  // to drop to the entry level. TRIM / CC wait for it to rise.
  const isBuy = strategy === "BUY_DIP" || strategy === "CSP" || strategy === "PMCC";
  const isSell = strategy === "TRIM" || strategy === "CC";
  if (!isBuy && !isSell) return { ...empty, reason: "non-directional strategy" };

  // Signed distance: positive = trigger already crossed; negative = still away.
  const pctToTrigger = isBuy
    ? (currentPrice - entry) / entry        // BUY: need price ≤ entry → 0 or negative when triggered
    : (entry - currentPrice) / entry;       // SELL: need price ≥ entry → 0 or negative when triggered

  // Detect blocking gates. Prefer the structured `gates` JSON field
  // (Phase 6 — brain emits a list[str] like ["exposure:NEW_ENTRY_ALLOWED",
  // "tv_daily:BUY"]). Fall back to the legacy accumulation_plan string
  // includes for rows written before the gates column existed.
  const gates: string[] = [];
  const structuredGates = parseStructuredGates(decision.gates);

  if (structuredGates.length > 0) {
    for (const g of structuredGates) {
      const block = evaluateGate(g, exposurePosture, tvConsensus);
      if (block) gates.push(block);
    }
  } else {
    // Legacy fallback for pre-Phase-6 rows.
    const planLower = (decision.accumulation_plan || "").toLowerCase();
    if (
      planLower.includes("new_entry_allowed") ||
      planLower.includes("cash_priority blocks") ||
      planLower.includes("ceiling ≥") ||
      planLower.includes("exposure_ceiling")
    ) {
      const rec = exposurePosture?.recommendation;
      if (rec && rec !== "NEW_ENTRY_ALLOWED") {
        gates.push(`exposure ${rec}, need NEW_ENTRY_ALLOWED`);
      }
    }
    if (
      planLower.includes("tv daily=buy") ||
      planLower.includes("tv daily flips") ||
      planLower.includes("tv daily=str")
    ) {
      const tvRec = (tvConsensus?.daily?.recommendation || "").toUpperCase();
      if (tvRec && !tvRec.includes("BUY")) {
        gates.push(`TV daily=${tvRec}, need BUY`);
      }
    }
  }

  // State machine
  // - triggered: pctToTrigger ≤ 0  (price has crossed the trigger threshold)
  // - close:     pctToTrigger ≤ 0.03  (within 3% — getting interesting)
  // - dormant:   pctToTrigger > 0.03
  let state: TriggerState;
  if (pctToTrigger <= 0) {
    state = gates.length === 0 ? "act_now" : "ready";
  } else if (pctToTrigger <= 0.03) {
    state = "close";
  } else {
    state = "dormant";
  }

  const reason = (() => {
    const tag = isBuy ? "drop to" : "rise to";
    const pricePct = (Math.abs(pctToTrigger) * 100).toFixed(1);
    if (state === "act_now") {
      return `Trigger hit — ${isBuy ? "buy" : "trim"} at $${currentPrice.toFixed(2)} (entry $${entry.toFixed(2)})`;
    }
    if (state === "ready") {
      return `Trigger hit but gated: ${gates.join(" · ")}`;
    }
    if (state === "close") {
      return `${pricePct}% to ${tag} $${entry.toFixed(2)}`;
    }
    return `${pricePct}% from trigger $${entry.toFixed(2)}`;
  })();

  return {
    state,
    reason,
    triggerPrice: entry,
    currentPrice,
    pctToTrigger,
    blockingGates: gates,
  };
}

/**
 * Risk Parity LITE audit row — written daily at 22:45 UTC by
 * `risk-parity-audit.yml`. 16 rows per run = 8 asset classes
 * (equity_us, equity_us_dividend, equity_intl, bond_long,
 * bond_intermediate, gold, commodities_broad, vol_long) × 2 accounts
 * (caspar, sarah). The PWA RiskAllocationCard consumes the latest run.
 */
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
  ticker: string;
  qty: string;
  avg_cost: string;
  last: string;
  mkt_val: string;
  upl: string;
  upl_pct: string;
  side: string;
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

export function summarizeInsider(
  rows: InsiderTransactionRow[],
  windowDays = 7,
): Map<string, InsiderSummary> {
  const out = new Map<string, InsiderSummary>();
  if (!rows.length) return out;
  const cutoff = new Date();
  cutoff.setUTCDate(cutoff.getUTCDate() - windowDays);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  for (const r of rows) {
    if (!r.ticker || (r.transaction_date || "") < cutoffStr) continue;
    const t = r.ticker.toUpperCase();
    const value = Number(r.value_usd) || 0;
    const side = (r.side || "").toLowerCase();
    let entry = out.get(t);
    if (!entry) {
      entry = {
        ticker: t, net_buy_value: 0, buy_count: 0, sell_count: 0,
        largest_value: 0, largest_name: "", latest_date: r.transaction_date,
      };
      out.set(t, entry);
    }
    if (side === "buy") {
      entry.net_buy_value += value;
      entry.buy_count += 1;
    } else if (side === "sell" || side === "issuer_sale") {
      entry.net_buy_value -= value;
      entry.sell_count += 1;
    }
    if (value > entry.largest_value) {
      entry.largest_value = value;
      entry.largest_name = r.name;
    }
    if ((r.transaction_date || "") > entry.latest_date) {
      entry.latest_date = r.transaction_date;
    }
  }
  return out;
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

export function summarizeNews(rows: NewsSentimentRow[]): Map<string, NewsSummary> {
  const out = new Map<string, NewsSummary>();
  if (!rows.length) return out;
  const now = new Date();
  const t24 = new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString().slice(0, 13);
  const t72 = new Date(now.getTime() - 72 * 60 * 60 * 1000).toISOString().slice(0, 13);
  for (const r of rows) {
    const t = (r.ticker || "").toUpperCase();
    if (!t) continue;
    const score = Number(r.sentiment_score) || 0;
    let entry = out.get(t);
    if (!entry) {
      entry = {
        ticker: t,
        latest_datetime: r.datetime,
        latest_headline: r.headline,
        latest_score: score,
        worst_score: score,
        best_score: score,
        count_24h: 0,
        count_72h: 0,
      };
      out.set(t, entry);
    }
    if ((r.datetime || "") > entry.latest_datetime) {
      entry.latest_datetime = r.datetime;
      entry.latest_headline = r.headline;
      entry.latest_score = score;
    }
    if (score < entry.worst_score) entry.worst_score = score;
    if (score > entry.best_score) entry.best_score = score;
    // crude time bucketing using ISO-prefix string compare
    const dtIso = r.datetime?.replace(/(\d{4}-\d{2}-\d{2})T(\d{2}).*/, "$1T$2");
    if (dtIso && dtIso >= t24) entry.count_24h += 1;
    if (dtIso && dtIso >= t72) entry.count_72h += 1;
  }
  return out;
}

/**
 * Build a ticker→LivePriceRow map for fast lookup. Empty/missing ticker
 * rows skipped. The map's `latest_updated_at` returns the most recent
 * timestamp across all rows (for the freshness chip).
 */
export function indexLivePrices(rows: LivePriceRow[]): {
  byTicker: Map<string, LivePriceRow>;
  latestUpdatedAt: string;
} {
  const byTicker = new Map<string, LivePriceRow>();
  let latestUpdatedAt = "";
  for (const r of rows) {
    const t = (r.ticker || "").toUpperCase();
    if (!t) continue;
    byTicker.set(t, r);
    if (r.updated_at && r.updated_at > latestUpdatedAt) {
      latestUpdatedAt = r.updated_at;
    }
  }
  return { byTicker, latestUpdatedAt };
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

/**
 * Build a per-ticker map: ticker -> { daily, weekly } using only the LATEST
 * row per (ticker, interval). The cron writes one row per ticker per day
 * per interval, so the latest row is the source of truth.
 */
export function lookupTvConsensusMap(rows: TvSignalRow[]): Map<string, TvConsensus> {
  const out = new Map<string, TvConsensus>();
  if (!rows.length) return out;
  // Group by (ticker, interval), keeping the row with the largest date.
  const latest = new Map<string, TvSignalRow>();
  for (const r of rows) {
    if (!r.ticker || !r.interval) continue;
    const key = `${r.ticker.toUpperCase()}|${r.interval}`;
    const prev = latest.get(key);
    if (!prev || (r.date ?? "") > (prev.date ?? "")) {
      latest.set(key, r);
    }
  }
  for (const [key, row] of latest) {
    const [ticker, interval] = key.split("|");
    if (!out.has(ticker)) out.set(ticker, {});
    const entry = out.get(ticker)!;
    if (interval === "1h") entry.hourly = row;
    else if (interval === "1d") entry.daily = row;
    else if (interval === "1W") entry.weekly = row;
  }
  return out;
}

/**
 * lookupRiskParity — group an audit-row list by account.
 *
 * Returns:
 *   - byClass:  Map<asset_class, RiskParityAuditRow> for the requested account
 *   - topOver:  rows where rebalance_action == OVERWEIGHT, sorted by
 *               delta_pct DESC (largest positive first), max 3
 *   - topUnder: rows where rebalance_action == UNDERWEIGHT, sorted by
 *               delta_pct ASC (most negative first), max 3
 *
 * The signals.ts helpers consume this to build the brain prompt's
 * `risk_parity` regime_anchor sub-object and the PWA card uses it for the
 * 8-bar layout. Empty input → empty maps + arrays.
 */
export function lookupRiskParity(
  account: string,
  rows: RiskParityAuditRow[],
): { byClass: Map<string, RiskParityAuditRow>; topOver: RiskParityAuditRow[]; topUnder: RiskParityAuditRow[] } {
  const accLower = account.toLowerCase();
  const byClass = new Map<string, RiskParityAuditRow>();
  const over: RiskParityAuditRow[] = [];
  const under: RiskParityAuditRow[] = [];

  for (const r of rows) {
    if ((r.account ?? "").toLowerCase() !== accLower) continue;
    if (r.asset_class && !byClass.has(r.asset_class)) byClass.set(r.asset_class, r);
    const action = (r.rebalance_action ?? "").toUpperCase();
    if (action === "OVERWEIGHT") over.push(r);
    else if (action === "UNDERWEIGHT") under.push(r);
  }

  over.sort((a, b) => numeric(b.delta_pct) - numeric(a.delta_pct));
  under.sort((a, b) => numeric(a.delta_pct) - numeric(b.delta_pct));

  return { byClass, topOver: over.slice(0, 3), topUnder: under.slice(0, 3) };
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
  error: string | null;
}

function latest<T extends { date: string }>(rows: T[]): T | null {
  if (!rows.length) return null;
  return rows.reduce((a, b) => (a.date > b.date ? a : b));
}

function latestGroup<T extends { date: string }>(rows: T[]): T[] {
  const l = latest(rows);
  if (!l) return [];
  return rows.filter((r) => r.date === l.date);
}

function sortByDate<T extends { date: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => a.date.localeCompare(b.date));
}

/** Deduplicate rows per date (keep last entry per date). */
function dedup<T extends { date: string }>(rows: T[]): T[] {
  const map = new Map<string, T>();
  for (const r of rows) {
    const key = r.date.slice(0, 10); // normalize to YYYY-MM-DD
    map.set(key, r);
  }
  return sortByDate([...map.values()]);
}

export async function fetchDashboard(): Promise<DashboardData> {
  try {
    const [dailyRows, casparRaw, sarahRaw, casparPos, sarahPos, optionRows, techRows, wheelRows, exitRows, defenseRows, wsrSumRows, decisions, macroRows, archiveRows, regimeRows, postureRows, screenRows, tvRows, riskParityRows] =
      await Promise.all([
        fetchTab<DailyBriefRow>("daily_brief_latest"),
        fetchTab<Record<string, string>>("snapshot_caspar"),
        fetchTab<Record<string, string>>("snapshot_sarah").catch(() => [] as Record<string, string>[]),
        fetchTab<PositionRow>("positions_caspar").catch(() => [] as PositionRow[]),
        fetchTab<PositionRow>("positions_sarah").catch(() => [] as PositionRow[]),
        fetchTab<OptionRow>("options").catch(() => [] as OptionRow[]),
        fetchTab<TechnicalScoreRow>("technical_scores").catch(() => [] as TechnicalScoreRow[]),
        fetchTab<WheelNextLegRow>("wheel_next_leg").catch(() => [] as WheelNextLegRow[]),
        fetchTab<ExitPlanRow>("exit_plans").catch(() => [] as ExitPlanRow[]),
        fetchTab<OptionsDefenseRow>("options_defense").catch(() => [] as OptionsDefenseRow[]),
        fetchTab<WsrSummaryRow>("wsr_summary").catch(() => [] as WsrSummaryRow[]),
        fetchTab<DecisionRow>("decision_queue").catch(() => [] as DecisionRow[]),
        fetchTab<MacroRow>("macro"),
        fetchTab<ArchiveRow>("wsr_archive").catch(() => [] as ArchiveRow[]),
        // New regime tabs (Agent 1's regime cron output). GIDs are
        // placeholder zeros — the catch fallback keeps things alive
        // until production GIDs land.
        fetchTab<RegimeSignalRow>("regime_signals").catch(() => [] as RegimeSignalRow[]),
        fetchTab<ExposurePostureRow>("exposure_posture").catch(() => [] as ExposurePostureRow[]),
        fetchTab<ScreenCandidateRow>("screen_candidates").catch(() => [] as ScreenCandidateRow[]),
        // TradingView 26-indicator consensus (1d + 1W per ticker).
        fetchTab<TvSignalRow>("tv_signals").catch(() => [] as TvSignalRow[]),
        // Risk Parity LITE audit (Agent 1 backend). Placeholder GID
        // until first cron run lands; catch keeps PWA alive meanwhile.
        fetchTab<RiskParityAuditRow>("risk_parity_audit").catch(() => [] as RiskParityAuditRow[]),
      ]);
    // Live prices + Finnhub tabs fetched in a second batch — failures here
    // shouldn't blow up the rest of the dashboard load.
    const [
      livePriceRows,
      earningsRows,
      economicRows,
      newsRows,
      insiderRows,
      analystRows,
      apiUsageRows,
      govConfRows,
      congressRows,
      uoaRows,
      harvestScanRows,
      scanResultRows,
      ivSurfaceScanRows,
      alpacaSnapRaw,
      alpacaPosRows,
    ] = await Promise.all([
      fetchTab<LivePriceRow>("live_prices").catch(() => [] as LivePriceRow[]),
      fetchTab<EarningsRow>("earnings_calendar").catch(() => [] as EarningsRow[]),
      fetchTab<EconomicEventRow>("economic_calendar").catch(() => [] as EconomicEventRow[]),
      fetchTab<NewsSentimentRow>("news_sentiment").catch(() => [] as NewsSentimentRow[]),
      fetchTab<InsiderTransactionRow>("insider_transactions").catch(() => [] as InsiderTransactionRow[]),
      fetchTab<AnalystConsensusRow>("analyst_consensus").catch(() => [] as AnalystConsensusRow[]),
      fetchTab<ApiUsageRow>("api_usage").catch(() => [] as ApiUsageRow[]),
      fetchTab<GovConfluenceRow>("gov_confluence_signals").catch(() => [] as GovConfluenceRow[]),
      fetchTab<CongressTradeRow>("congress_trades").catch(() => [] as CongressTradeRow[]),
      fetchTabByName<UoaAlertRow>("uoa_alerts").catch(() => [] as UoaAlertRow[]),
      fetchTab<HarvestScanRow>("harvest_scan").catch(() => [] as HarvestScanRow[]),
      fetchTabByName<ScanResultRow>("scan_results").catch(() => [] as ScanResultRow[]),
      fetchTab<IvSurfaceScanRow>("iv_surface_scan").catch(() => [] as IvSurfaceScanRow[]),
      fetchTab<Record<string, string>>("snapshot_alpaca").catch(() => [] as Record<string, string>[]),
      fetchTab<AlpacaPositionRow>("positions_alpaca").catch(() => [] as AlpacaPositionRow[]),
    ]);
    const liveIdx = indexLivePrices(livePriceRows);
    const newsByTicker = summarizeNews(newsRows);
    const insiderByTicker = summarizeInsider(insiderRows, 7);
    const analystByTicker = new Map<string, AnalystConsensusRow>();
    for (const a of analystRows) {
      if (a.ticker) analystByTicker.set(a.ticker.toUpperCase(), a);
    }
    const casparRows = normalizeSnapshot(casparRaw);
    const sarahRows = normalizeSnapshot(sarahRaw);

    // Latest regime row per source (market_breadth / ftd /
    // distribution_day / macro_regime). Sources without rows just
    // don't appear in the map → consumers default to "—".
    const regimeSignalsLatest: Record<string, RegimeSignalRow> = {};
    for (const r of regimeRows) {
      if (!r.source) continue;
      const prev = regimeSignalsLatest[r.source];
      if (!prev || (r.date ?? "") > (prev.date ?? "")) {
        regimeSignalsLatest[r.source] = r;
      }
    }

    return {
      dailyHistory: dedup(dailyRows).reverse(),
      daily: latest(dailyRows),
      caspar: latest(casparRows),
      sarah: latest(sarahRows),
      casparPositions: latestGroup(casparPos),
      sarahPositions: latestGroup(sarahPos),
      options: latestGroup(optionRows),
      technicalScores: latestGroup(techRows),
      technicalScoresHistory: sortByDate(techRows),
      wheelNextLeg: latestGroup(wheelRows),
      exitPlans: latestGroup(exitRows),
      optionsDefense: latestGroup(defenseRows),
      wsrSummary: (() => {
        const full = sortByDate(wsrSumRows.filter((r) => r.source !== "wsr_lite"));
        return full.length ? full[full.length - 1] : null;
      })(),
      wsrLite: (() => {
        const lite = sortByDate(wsrSumRows.filter((r) => r.source === "wsr_lite"));
        return lite.length ? lite[lite.length - 1] : null;
      })(),
      decisions: latestGroup(decisions),
      decisionsAll: sortByDate(decisions),
      macro: latest(macroRows),
      casparHistory: dedup(casparRows),
      sarahHistory: dedup(sarahRows),
      macroHistory: dedup(macroRows),
      archive: sortByDate(archiveRows).reverse(),
      regimeSignalsLatest,
      exposurePosture: latest(postureRows),
      screenCandidates: sortByDate(screenRows),
      tvSignals: lookupTvConsensusMap(tvRows),
      riskParityAudit: latestGroup(riskParityRows),
      livePrices: liveIdx.byTicker,
      livePricesUpdatedAt: liveIdx.latestUpdatedAt,
      earnings: earningsRows,
      economicEvents: economicRows,
      newsByTicker,
      insiderByTicker,
      analystByTicker,
      apiUsage: apiUsageRows,
      govConfluence: latestGroup(govConfRows)
        .filter((r) => Number(r.confluence_score) >= 10)
        .sort((a, b) => Number(b.confluence_score) - Number(a.confluence_score)),
      congressTrades: (() => {
        const sevenDaysAgo = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
        return congressRows
          .filter((r) => (r.transaction_date || r.filing_date || "") >= sevenDaysAgo && r.ticker)
          .sort((a, b) => (b.transaction_date || b.filing_date || "").localeCompare(a.transaction_date || a.filing_date || ""));
      })(),
      uoaAlerts: latestGroup(uoaRows),
      harvestScan: latestGroup(harvestScanRows),
      scanResults: latestGroup(scanResultRows),
      ivSurfaceScan: ivSurfaceScanRows,
      alpaca: (() => {
        const rows = normalizeSnapshot(alpacaSnapRaw) as unknown as AlpacaSnapshotRow[];
        return rows.length ? rows.reduce((a, b) => (a.date > b.date ? a : b)) : null;
      })(),
      alpacaPositions: latestGroup(alpacaPosRows),
      error: null,
    };
  } catch (e) {
    return {
      dailyHistory: [], daily: null, caspar: null, sarah: null,
      casparPositions: [], sarahPositions: [], options: [],
      technicalScores: [], technicalScoresHistory: [],
      wheelNextLeg: [], exitPlans: [], optionsDefense: [],
      wsrSummary: null, wsrLite: null, decisions: [], decisionsAll: [],
      macro: null, casparHistory: [], sarahHistory: [], macroHistory: [],
      archive: [],
      regimeSignalsLatest: {},
      exposurePosture: null,
      screenCandidates: [],
      tvSignals: new Map(),
      riskParityAudit: [],
      livePrices: new Map(),
      livePricesUpdatedAt: "",
      earnings: [],
      economicEvents: [],
      newsByTicker: new Map(),
      insiderByTicker: new Map(),
      analystByTicker: new Map(),
      apiUsage: [],
      govConfluence: [],
      congressTrades: [],
      uoaAlerts: [],
      harvestScan: [],
      scanResults: [],
      ivSurfaceScan: [],
      alpaca: null,
      alpacaPositions: [],
      error: String(e),
    };
  }
}
