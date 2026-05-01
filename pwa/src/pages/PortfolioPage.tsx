import type {
  SnapshotRow,
  PositionRow,
  TechnicalScoreRow,
  ExitPlanRow,
} from "../data";
import { PnlCard } from "../cards/PnlCard";
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
  loading,
}: {
  casparSnapshot: SnapshotRow | null;
  casparPositions: PositionRow[];
  sarahSnapshot: SnapshotRow | null;
  sarahPositions: PositionRow[];
  technicalScores: TechnicalScoreRow[];
  technicalScoresHistory: TechnicalScoreRow[];
  exitPlans: ExitPlanRow[];
  loading: boolean;
}) {
  const CasparPanel = (
    <div className="flex flex-col gap-4 px-4 pb-4">
      <div className="fade-up fade-up-1">
        <PnlCard
          label="Caspar"
          currency="USD"
          snapshot={casparSnapshot}
          positions={casparPositions}
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
          snapshot={sarahSnapshot}
          positions={sarahPositions}
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
        />
      </div>
    </div>
  );

  return (
    <SwipeTabs
      tabs={[{ label: "Caspar" }, { label: "Sarah" }]}
      panels={[CasparPanel, SarahPanel]}
      defaultIndex={0}
      persistKey={PORTFOLIO_SUB_KEY}
    />
  );
}
