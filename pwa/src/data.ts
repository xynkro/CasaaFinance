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
  option_recommendations: "129728101",
  technical_scores: "657341624",
  wheel_next_leg: "805863395",
  scan_results: "1133435061",
  exit_plans: "515412556",
  options_defense: "1717646002",
  macro: "447436838",
  wsr_archive: "1065773181",
};

async function fetchTab<T>(tab: keyof typeof GIDS): Promise<T[]> {
  const res = await fetch(csvUrl(GIDS[tab]));
  if (!res.ok) throw new Error(`Sheet fetch failed: ${tab} (${res.status})`);
  const text = await res.text();
  const { data } = Papa.parse<T>(text, { header: true, skipEmptyLines: true });
  return data;
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

export interface OptionRecommendationRow {
  date: string;
  source: string;
  account: string;
  ticker: string;
  strategy: string;              // "CSP" | "CC" | "LONG_CALL" | "LONG_PUT" | "PMCC"
  right: string;
  strike: string;
  expiry: string;
  premium_per_share: string;
  delta: string;
  annual_yield_pct: string;
  breakeven: string;
  cash_required: string;
  iv_rank: string;
  thesis_confidence: string;     // 0.0 - 1.0
  thesis: string;
  status: string;                // "proposed" | "executed" | "skipped" | "expired"
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
}

export interface ArchiveRow {
  date: string;
  title: string;
  drive_file_id: string;
  drive_url: string;
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
  optionRecommendations: OptionRecommendationRow[];
  technicalScores: TechnicalScoreRow[];
  technicalScoresHistory: TechnicalScoreRow[];  // full history for sparklines
  wheelNextLeg: WheelNextLegRow[];
  scanResults: ScanResultRow[];
  exitPlans: ExitPlanRow[];
  optionsDefense: OptionsDefenseRow[];
  decisions: DecisionRow[];
  macro: MacroRow | null;
  // History (all rows, sorted by date ascending)
  casparHistory: SnapshotRow[];
  sarahHistory: SnapshotRow[];
  macroHistory: MacroRow[];
  archive: ArchiveRow[];
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
    const [dailyRows, casparRaw, sarahRaw, casparPos, sarahPos, optionRows, optionRecs, techRows, wheelRows, scanRows, exitRows, defenseRows, decisions, macroRows, archiveRows] =
      await Promise.all([
        fetchTab<DailyBriefRow>("daily_brief_latest"),
        fetchTab<Record<string, string>>("snapshot_caspar"),
        fetchTab<Record<string, string>>("snapshot_sarah").catch(() => [] as Record<string, string>[]),
        fetchTab<PositionRow>("positions_caspar").catch(() => [] as PositionRow[]),
        fetchTab<PositionRow>("positions_sarah").catch(() => [] as PositionRow[]),
        fetchTab<OptionRow>("options").catch(() => [] as OptionRow[]),
        fetchTab<OptionRecommendationRow>("option_recommendations").catch(() => [] as OptionRecommendationRow[]),
        fetchTab<TechnicalScoreRow>("technical_scores").catch(() => [] as TechnicalScoreRow[]),
        fetchTab<WheelNextLegRow>("wheel_next_leg").catch(() => [] as WheelNextLegRow[]),
        fetchTab<ScanResultRow>("scan_results").catch(() => [] as ScanResultRow[]),
        fetchTab<ExitPlanRow>("exit_plans").catch(() => [] as ExitPlanRow[]),
        fetchTab<OptionsDefenseRow>("options_defense").catch(() => [] as OptionsDefenseRow[]),
        fetchTab<DecisionRow>("decision_queue").catch(() => [] as DecisionRow[]),
        fetchTab<MacroRow>("macro"),
        fetchTab<ArchiveRow>("wsr_archive").catch(() => [] as ArchiveRow[]),
      ]);
    const casparRows = normalizeSnapshot(casparRaw);
    const sarahRows = normalizeSnapshot(sarahRaw);
    return {
      dailyHistory: dedup(dailyRows).reverse(),
      daily: latest(dailyRows),
      caspar: latest(casparRows),
      sarah: latest(sarahRows),
      casparPositions: latestGroup(casparPos),
      sarahPositions: latestGroup(sarahPos),
      options: latestGroup(optionRows),
      optionRecommendations: optionRecs,
      technicalScores: latestGroup(techRows),
      technicalScoresHistory: sortByDate(techRows),
      wheelNextLeg: latestGroup(wheelRows),
      scanResults: latestGroup(scanRows),
      exitPlans: latestGroup(exitRows),
      optionsDefense: latestGroup(defenseRows),
      decisions: latestGroup(decisions),
      macro: latest(macroRows),
      casparHistory: dedup(casparRows),
      sarahHistory: dedup(sarahRows),
      macroHistory: dedup(macroRows),
      archive: sortByDate(archiveRows).reverse(),
      error: null,
    };
  } catch (e) {
    return {
      dailyHistory: [], daily: null, caspar: null, sarah: null,
      casparPositions: [], sarahPositions: [], options: [], optionRecommendations: [],
      technicalScores: [], technicalScoresHistory: [],
      wheelNextLeg: [], scanResults: [], exitPlans: [], optionsDefense: [], decisions: [],
      macro: null, casparHistory: [], sarahHistory: [], macroHistory: [],
      archive: [], error: String(e),
    };
  }
}
