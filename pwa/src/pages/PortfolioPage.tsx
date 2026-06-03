import type {
  SnapshotRow,
  PositionRow,
  TechnicalScoreRow,
  ExitPlanRow,
  LivePriceRow,
  AlpacaSnapshotRow,
  AlpacaPositionRow,
  PaperBenchmarkRow,
  DailyPlanRow,
} from "../data";
import { PnlCard } from "../cards/PnlCard";
import { PaperTradingView } from "../cards/PaperTradingView";
import { PositionsTable } from "../components/PositionsTable";
import { SwipeTabs } from "../components/SwipeTabs";

// One-shot migration of the old 3-tab Portfolio sub-tab key
// (0=History, 1=Caspar, 2=Sarah) → 2-tab layout (0=Caspar, 1=Sarah).
// Runs at module load before any SwipeTabs reads the persisted index.
const PORTFOLIO_SUB_KEY = "casaa_portfolio_subtab";
const PORTFOLIO_MIGRATION_KEY = "casaa_portfolio_subtab_migrated_v2";
(function migratePortfolioSubtab() {
  try {
    if (localStorage.getItem(PORTFOLIO_MIGRATION_KEY)) return;
    const v = localStorage.getItem(PORTFOLIO_SUB_KEY);
    if (v === "0" || v === "1") {
      // 0=History → 0=Caspar (already correct); 1=Caspar → 0
      localStorage.setItem(PORTFOLIO_SUB_KEY, "0");
    } else if (v === "2") {
      localStorage.setItem(PORTFOLIO_SUB_KEY, "1"); // Sarah was idx 2
    }
    localStorage.setItem(PORTFOLIO_MIGRATION_KEY, "1");
  } catch {
    // ignore
  }
})();

export function PortfolioPage({
  casparSnapshot,
  casparPositions,
  sarahSnapshot,
  sarahPositions,
  technicalScores,
  technicalScoresHistory,
  exitPlans,
  livePrices,
  livePricesUpdatedAt,
  usdSgd,
  alpacaSnapshot,
  alpacaPositions,
  paperBenchmark,
  dailyPlan,
  loading,
}: {
  casparSnapshot: SnapshotRow | null;
  casparPositions: PositionRow[];
  sarahSnapshot: SnapshotRow | null;
  sarahPositions: PositionRow[];
  technicalScores: TechnicalScoreRow[];
  technicalScoresHistory: TechnicalScoreRow[];
  exitPlans: ExitPlanRow[];
  livePrices: Map<string, LivePriceRow>;
  livePricesUpdatedAt: string;
  usdSgd: number;
  alpacaSnapshot: AlpacaSnapshotRow | null;
  alpacaPositions: AlpacaPositionRow[];
  paperBenchmark: PaperBenchmarkRow[];
  dailyPlan: DailyPlanRow[];
  loading: boolean;
}) {
  const CasparPanel = (
    <div className="flex flex-col gap-4 px-4 pb-4">
      <div className="fade-up fade-up-1">
        <PnlCard
          label="Caspar"
          currency="USD"
          account="caspar"
          usdSgd={usdSgd}
          snapshot={casparSnapshot}
          positions={casparPositions}
          livePrices={livePrices}
          livePricesUpdatedAt={livePricesUpdatedAt}
          loading={loading}
        />
      </div>
      <div className="fade-up fade-up-2">
        <PositionsTable
          positions={casparPositions}
          currency="USD"
          account="caspar"
          technicalScores={technicalScores}
          technicalScoresHistory={technicalScoresHistory}
          exitPlans={exitPlans}
          livePrices={livePrices}
        />
      </div>
    </div>
  );

  const SarahPanel = (
    <div className="flex flex-col gap-4 px-4 pb-4">
      <div className="fade-up fade-up-1">
        <PnlCard
          label="Sarah"
          currency="SGD"
          account="sarah"
          usdSgd={usdSgd}
          snapshot={sarahSnapshot}
          positions={sarahPositions}
          livePrices={livePrices}
          livePricesUpdatedAt={livePricesUpdatedAt}
          loading={loading}
        />
      </div>
      <div className="fade-up fade-up-2">
        <PositionsTable
          positions={sarahPositions}
          currency="SGD"
          account="sarah"
          technicalScores={technicalScores}
          technicalScoresHistory={technicalScoresHistory}
          exitPlans={exitPlans}
          livePrices={livePrices}
        />
      </div>
    </div>
  );

  const AlpacaPanel = (
    <div className="flex flex-col gap-4 px-4 pb-4">
      <div className="fade-up fade-up-1">
        <PaperTradingView
          snapshot={alpacaSnapshot}
          positions={alpacaPositions}
          benchmark={paperBenchmark}
          dailyPlan={dailyPlan}
          loading={loading}
        />
      </div>
    </div>
  );

  return (
    <SwipeTabs
      tabs={[{ label: "Caspar" }, { label: "Sarah" }, { label: "Paper" }]}
      panels={[CasparPanel, SarahPanel, AlpacaPanel]}
      defaultIndex={0}
      persistKey={PORTFOLIO_SUB_KEY}
    />
  );
}
