import Papa from "papaparse";

const SHEET_ID = "1N2AAx1GqTi23Qlq6MZkQoYfQOY7An1K0vvPx65YBiQc";

function csvUrl(gid: string): string {
  return `https://docs.google.com/spreadsheets/d/${SHEET_ID}/gviz/tq?tqx=out:csv&gid=${gid}`;
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
  scan_results: "1133435061",
  option_recommendations: "129728101",
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
  screen_candidates: "0",
  // TradingView 26-indicator consensus, populated daily by tv-signals.yml.
  // One row per (ticker, interval) — both 1d and 1W. The DecisionCard reads
  // the latest 1d + 1W row per ticker for the consensus chip.
  tv_signals: "1954107259",
  // Risk Parity LITE — diversification hygiene audit. Written daily at
  // 22:45 UTC by risk-parity-audit.yml. 8 asset classes × 2 accounts =
  // 16 rows per run. Live GID resolved via gspread on 2026-05-07.
  risk_parity_audit: "1398209766",
};

async function fetchTab<T>(tab: keyof typeof GIDS): Promise<T[]> {
  const res = await fetch(csvUrl(GIDS[tab]));
  if (!res.ok) throw new Error(`Sheet fetch failed: ${tab} (${res.status})`);
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

export interface ScanResultRow {
  date: string;
  ticker: string;
  strategy: string;           // "CSP" | "CC"
  right: string;
  strike: string;
  expiry: string;
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
}

export interface OptionRecommendationRow {
  date: string;
  source: string;             // "market_scan" | "wheel_continuation" | etc.
  account: string;            // "watchlist" | "caspar" | "sarah"
  ticker: string;
  strategy: string;           // "BUY_DIP" | "CSP" | "CC" | "PMCC" | "LONG_CALL" | "LONG_PUT"
  right: string;              // "C" | "P" | ""
  strike: string;
  expiry: string;             // "YYYY-MM-DD"
  premium_per_share: string;
  delta: string;
  annual_yield_pct: string;
  breakeven: string;
  cash_required: string;
  iv_rank: string;
  thesis_confidence: string;
  thesis: string;
  status: string;             // "NEW" | etc.
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

/** Latest 1d + 1W TV signal for one ticker. */
export interface TvConsensus {
  daily?: TvSignalRow;
  weekly?: TvSignalRow;
}

/**
 * Risk Parity LITE audit row — written daily at 22:45 UTC by
 * `risk-parity-audit.yml`. 16 rows per run = 8 asset classes
 * (equity_us, equity_us_dividend, equity_intl, bond_long,
 * bond_intermediate, gold, commodities_broad, vol_long) × 2 accounts
 * (caspar, sarah). The PWA RiskAllocationCard consumes the latest run.
 */
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
    if (interval === "1d") entry.daily = row;
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
  scanResults: ScanResultRow[];
  optionRecommendations: OptionRecommendationRow[];  // market_scan source, latest date only
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
    const [dailyRows, casparRaw, sarahRaw, casparPos, sarahPos, optionRows, techRows, wheelRows, scanRows, optRecRows, exitRows, defenseRows, wsrSumRows, decisions, macroRows, archiveRows, regimeRows, postureRows, screenRows, tvRows, riskParityRows] =
      await Promise.all([
        fetchTab<DailyBriefRow>("daily_brief_latest"),
        fetchTab<Record<string, string>>("snapshot_caspar"),
        fetchTab<Record<string, string>>("snapshot_sarah").catch(() => [] as Record<string, string>[]),
        fetchTab<PositionRow>("positions_caspar").catch(() => [] as PositionRow[]),
        fetchTab<PositionRow>("positions_sarah").catch(() => [] as PositionRow[]),
        fetchTab<OptionRow>("options").catch(() => [] as OptionRow[]),
        fetchTab<TechnicalScoreRow>("technical_scores").catch(() => [] as TechnicalScoreRow[]),
        fetchTab<WheelNextLegRow>("wheel_next_leg").catch(() => [] as WheelNextLegRow[]),
        fetchTab<ScanResultRow>("scan_results").catch(() => [] as ScanResultRow[]),
        fetchTab<OptionRecommendationRow>("option_recommendations").catch(() => [] as OptionRecommendationRow[]),
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
      scanResults: latestGroup(scanRows),
      optionRecommendations: (() => {
        // Filter to market_scan source, then take rows from the latest day (YYYY-MM-DD prefix).
        const ms = optRecRows.filter((r) => r.source === "market_scan" && r.date);
        if (!ms.length) return [];
        const latestDay = ms.reduce(
          (acc, r) => (r.date.slice(0, 10) > acc ? r.date.slice(0, 10) : acc),
          "",
        );
        return ms.filter((r) => r.date.slice(0, 10) === latestDay);
      })(),
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
      error: null,
    };
  } catch (e) {
    return {
      dailyHistory: [], daily: null, caspar: null, sarah: null,
      casparPositions: [], sarahPositions: [], options: [],
      technicalScores: [], technicalScoresHistory: [],
      wheelNextLeg: [], scanResults: [], optionRecommendations: [], exitPlans: [], optionsDefense: [],
      wsrSummary: null, wsrLite: null, decisions: [], decisionsAll: [],
      macro: null, casparHistory: [], sarahHistory: [], macroHistory: [],
      archive: [],
      regimeSignalsLatest: {},
      exposurePosture: null,
      screenCandidates: [],
      tvSignals: new Map(),
      riskParityAudit: [],
      error: String(e),
    };
  }
}
