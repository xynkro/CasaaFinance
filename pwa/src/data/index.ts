/**
 * data/ — the FinancePWA data layer (FACADE / re-export barrel).
 *
 * The original monolithic ``src/data.ts`` was split into focused modules:
 *   - data/types.ts      — every *Row interface + derived types (DashboardData,
 *                          TvConsensus, TriggerEvaluation, ParsedOcc, summaries…)
 *   - data/transport.ts  — csvUrl / csvUrlByName / fetchTab / fetchTabByName
 *                          (+ SHEET_ID, GIDS, the Firestore branch)
 *   - data/normalize.ts  — numeric / numericOrNull / coercions / derivations
 *                          (evaluateTrigger, parseOcc, summarize*, lookup*…)
 *   - data/dashboard.ts  — fetchDashboard
 *
 * This barrel re-exports the EXACT public API the flat ``data.ts`` exposed, so
 * every existing ``import { … } from "../data"`` / ``"./data"`` keeps working
 * unchanged. (verbatimModuleSyntax is on, so types are re-exported via
 * ``export type`` and runtime values via ``export``.)
 */

// ---- runtime values ----
export {
  numeric,
  numericOrNull,
  evaluateTrigger,
  parseOcc,
  isOccOption,
  summarizeInsider,
  summarizeNews,
  indexLivePrices,
  lookupTvConsensusMap,
  lookupRiskParity,
} from "./normalize";

export { fetchDashboard } from "./dashboard";

// ---- types ----
export type {
  DailyBriefRow,
  SnapshotRow,
  PositionRow,
  MacroRow,
  OptionRow,
  WsrSummaryRow,
  OptionsDefenseRow,
  ExitPlanRow,
  TechnicalScoreRow,
  WheelNextLegRow,
  DecisionRow,
  ArchiveRow,
  RegimeSignalRow,
  ExposurePostureRow,
  ScreenCandidateRow,
  TvSignalRow,
  TvConsensus,
  TriggerState,
  TriggerEvaluation,
  LivePriceRow,
  ApiUsageRow,
  GovConfluenceRow,
  DailyPlanRow,
  MacroLeanRow,
  ScanMetaRow,
  CuratedPickRow,
  GexRegimeRow,
  AlpacaSnapshotRow,
  AlpacaPositionRow,
  PaperBenchmarkRow,
  ParsedOcc,
  HarvestScanRow,
  ScanResultRow,
  IvSurfaceScanRow,
  UoaAlertRow,
  CongressTradeRow,
  EarningsRow,
  EconomicEventRow,
  NewsSentimentRow,
  InsiderTransactionRow,
  AnalystConsensusRow,
  InsiderSummary,
  NewsSummary,
  RiskParityAuditRow,
  DashboardData,
} from "./types";
