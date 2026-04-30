import { lazy, Suspense } from "react";
import type {
  SnapshotRow,
  PositionRow,
  TechnicalScoreRow,
  ExitPlanRow,
  MacroRow,
} from "../data";
import { Card } from "../cards/Card";
import { PnlCard } from "../cards/PnlCard";
import { PositionsTable } from "../components/PositionsTable";
import { SwipeTabs } from "../components/SwipeTabs";
import { RiskMetricsCard } from "../cards/RiskMetricsCard";

// Lazy: pulls in recharts (~150 KB) only when the History tab is opened.
const HistoryPage = lazy(() =>
  import("./HistoryPage").then((m) => ({ default: m.HistoryPage })),
);

function HistorySkeleton() {
  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <div className="shimmer h-3.5 w-20 rounded" />
        <div className="shimmer h-3 w-16 rounded" />
      </div>
      <div className="shimmer h-48 w-full rounded-xl mb-4" />
      <div className="shimmer h-48 w-full rounded-xl" />
    </Card>
  );
}

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
        <Suspense fallback={<HistorySkeleton />}>
          <HistoryPage
            casparHistory={casparHistory}
            sarahHistory={sarahHistory}
            macroHistory={macroHistory}
          />
        </Suspense>
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
      persistKey="casaa_portfolio_subtab"
    />
  );
}
