import type {
  SnapshotRow,
  PositionRow,
  TechnicalScoreRow,
  ExitPlanRow,
  MacroRow,
} from "../data";
import { PnlCard } from "../cards/PnlCard";
import { PositionsTable } from "../components/PositionsTable";
import { SwipeTabs } from "../components/SwipeTabs";
import { RiskMetricsCard } from "../cards/RiskMetricsCard";
import { HistoryPage } from "./HistoryPage";

export function PortfolioPage({
  casparSnapshot,
  casparPositions,
  sarahSnapshot,
  sarahPositions,
  casparHistory,
  sarahHistory,
  macroHistory,
  technicalScores,
  technicalScoresHistory,
  exitPlans,
  loading,
}: {
  casparSnapshot: SnapshotRow | null;
  casparPositions: PositionRow[];
  sarahSnapshot: SnapshotRow | null;
  sarahPositions: PositionRow[];
  casparHistory: SnapshotRow[];
  sarahHistory: SnapshotRow[];
  macroHistory: MacroRow[];
  technicalScores: TechnicalScoreRow[];
  technicalScoresHistory: TechnicalScoreRow[];
  exitPlans: ExitPlanRow[];
  loading: boolean;
}) {
  const HistoryPanel = (
    <div className="flex flex-col gap-4 px-4 pb-4">
      <div className="fade-up fade-up-1">
        <RiskMetricsCard
          casparHistory={casparHistory}
          sarahHistory={sarahHistory}
          macroHistory={macroHistory}
        />
      </div>
      <div className="fade-up fade-up-2">
        <HistoryPage
          casparHistory={casparHistory}
          sarahHistory={sarahHistory}
          macroHistory={macroHistory}
        />
      </div>
    </div>
  );

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
      tabs={[{ label: "History" }, { label: "Caspar" }, { label: "Sarah" }]}
      panels={[HistoryPanel, CasparPanel, SarahPanel]}
      defaultIndex={0}
    />
  );
}
