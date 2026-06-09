/**
 * data/dashboard.ts — the aggregate dashboard fetch.
 *
 * Owns ``fetchDashboard`` (the two-batch parallel fetch of every tab, plus the
 * latest/history shaping) and its private row-shaping helpers
 * (latest / latestGroup / sortByDate / dedup).
 *
 * Split out of the original monolithic ``src/data.ts``. ``fetchDashboard`` and
 * the ``DashboardData`` type are re-exported from ``../data`` so existing
 * importers keep resolving unchanged.
 */
import { fetchTab, fetchTabByName } from "./transport";
import {
  normalizeSnapshot,
  indexLivePrices,
  summarizeNews,
  summarizeInsider,
  lookupTvConsensusMap,
} from "./normalize";
import type {
  DashboardData,
  DailyBriefRow,
  PositionRow,
  OptionRow,
  TechnicalScoreRow,
  WheelNextLegRow,
  ExitPlanRow,
  OptionsDefenseRow,
  WsrSummaryRow,
  DecisionRow,
  MacroRow,
  ArchiveRow,
  RegimeSignalRow,
  ExposurePostureRow,
  ScreenCandidateRow,
  TvSignalRow,
  RiskParityAuditRow,
  LivePriceRow,
  EarningsRow,
  EconomicEventRow,
  NewsSentimentRow,
  InsiderTransactionRow,
  AnalystConsensusRow,
  ApiUsageRow,
  GovConfluenceRow,
  CongressTradeRow,
  UoaAlertRow,
  HarvestScanRow,
  ScanResultRow,
  IvSurfaceScanRow,
  AlpacaSnapshotRow,
  AlpacaPositionRow,
  PaperBenchmarkRow,
  GexRegimeRow,
  DailyPlanRow,
  MacroLeanRow,
  ScanMetaRow,
  CuratedPickRow,
} from "./types";

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
      paperBenchmarkRows,
      gexRegimeRows,
      dailyPlanRows,
      macroLeanRows,
      curatedPickRows,
      scanMetaRows,
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
      fetchTabByName<PaperBenchmarkRow>("paper_benchmark").catch(() => [] as PaperBenchmarkRow[]),
      fetchTabByName<GexRegimeRow>("gex_regime").catch(() => [] as GexRegimeRow[]),
      fetchTabByName<DailyPlanRow>("daily_plan").catch(() => [] as DailyPlanRow[]),
      fetchTabByName<MacroLeanRow>("macro_lean").catch(() => [] as MacroLeanRow[]),
      fetchTabByName<CuratedPickRow>("curated_picks").catch(() => [] as CuratedPickRow[]),
      fetchTabByName<ScanMetaRow>("scan_meta").catch(() => [] as ScanMetaRow[]),
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
      // Harvest freshness guard: harvest_scan and scan_results are written by the
      // SAME scan run, so they share a date on a healthy run. If harvest's latest
      // date is OLDER than scan_results', a newer scan ran without producing any
      // harvest picks — the harvest set is stale, so don't surface it (this is what
      // kept showing week-old CLSK/MARA puts the gates already reject).
      harvestScan: (() => {
        const h = latestGroup(harvestScanRows);
        const hDate = (h[0]?.date ?? "").slice(0, 10);
        const sDate = (latest(scanResultRows)?.date ?? "").slice(0, 10);
        return sDate && hDate && hDate < sDate ? [] : h;
      })(),
      scanResults: latestGroup(scanResultRows),
      ivSurfaceScan: ivSurfaceScanRows,
      alpaca: (() => {
        const rows = normalizeSnapshot(alpacaSnapRaw) as unknown as AlpacaSnapshotRow[];
        return rows.length ? rows.reduce((a, b) => (a.date > b.date ? a : b)) : null;
      })(),
      alpacaPositions: latestGroup(alpacaPosRows),
      paperBenchmark: latestGroup(paperBenchmarkRows),
      gexRegime: latestGroup(gexRegimeRows),
      dailyPlan: latestGroup(dailyPlanRows),
      macroLean: latest(macroLeanRows),
      // Single-row heartbeat (upsert-overwritten each run) — no date field to
      // sort on; take the last row written.
      scanMeta: scanMetaRows[scanMetaRows.length - 1] ?? null,
      ...(() => {
        const cp = latestGroup(curatedPickRows);
        return {
          curatedPicks: cp,
          mfWatchlist: cp.filter((r) => r.role === "watchlist"),
          mfOverlay: cp.filter((r) => r.role === "overlay"),
          mfReference: cp.filter((r) => r.role === "reference"),
        };
      })(),
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
      paperBenchmark: [],
      gexRegime: [],
      dailyPlan: [],
      macroLean: null,
      scanMeta: null,
      curatedPicks: [], mfWatchlist: [], mfOverlay: [], mfReference: [],
      error: String(e),
    };
  }
}
