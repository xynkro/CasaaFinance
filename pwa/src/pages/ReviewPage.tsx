import { lazy, Suspense, useState } from "react";
import type {
  DecisionRow,
  SnapshotRow,
  MacroRow,
  ArchiveRow,
  DailyBriefRow,
} from "../data";
import { Card } from "../cards/Card";
import { StickyTabs } from "../components/StickyTabs";
import { ClosedDecisionsCard } from "../cards/ClosedDecisionsCard";
import { RiskMetricsCard } from "../cards/RiskMetricsCard";
import { ArchivePage } from "./ArchivePage";
import { LineChart, BarChart3, FileText } from "lucide-react";

// Lazy: pulls in recharts (~150 KB) only when the Numbers sub-tab is opened.
// Preserves the lazy-load setup from commit 1bfe132.
const HistoryPage = lazy(() =>
  import("./HistoryPage").then((m) => ({ default: m.HistoryPage })),
);

type ReviewSubTab = "closed" | "numbers" | "reports";

const LAST_KEY = "casaa_review_subtab";

function loadLastSub(): ReviewSubTab {
  try {
    const v = localStorage.getItem(LAST_KEY);
    if (v === "closed" || v === "numbers" || v === "reports") return v;
  } catch {
    // ignore
  }
  return "closed";
}

function HistorySkeleton() {
  return (
    <div className="px-4 pb-4">
      <Card>
        <div className="flex items-center justify-between mb-4">
          <div className="shimmer h-3.5 w-20 rounded" />
          <div className="shimmer h-3 w-16 rounded" />
        </div>
        <div className="shimmer h-48 w-full rounded-xl mb-4" />
        <div className="shimmer h-48 w-full rounded-xl" />
      </Card>
    </div>
  );
}

export function ReviewPage({
  decisionsAll,
  casparHistory,
  sarahHistory,
  macroHistory,
  archive,
  dailyHistory,
}: {
  decisionsAll: DecisionRow[];
  casparHistory: SnapshotRow[];
  sarahHistory: SnapshotRow[];
  macroHistory: MacroRow[];
  archive: ArchiveRow[];
  dailyHistory: DailyBriefRow[];
}) {
  const [sub, setSub] = useState<ReviewSubTab>(loadLastSub);

  const handleSub = (key: string) => {
    const next = key as ReviewSubTab;
    setSub(next);
    try { localStorage.setItem(LAST_KEY, next); } catch {
      // ignore
    }
  };

  // Badge: count of closed decisions in the last 30 days for the closed-decisions tab
  const cutoff = (() => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    return d.toISOString().slice(0, 10);
  })();
  const closedRecent = decisionsAll.filter((r) => {
    const s = (r.status || "").toLowerCase();
    return (s === "filled" || s === "killed" || s === "expired") && r.date.slice(0, 10) >= cutoff;
  }).length;

  return (
    <div className="flex flex-col px-4 pb-4">
      <StickyTabs
        active={sub}
        onChange={handleSub}
        tabs={[
          { key: "closed",  label: "Closed",  icon: BarChart3,  badge: closedRecent },
          { key: "numbers", label: "Numbers", icon: LineChart },
          { key: "reports", label: "Reports", icon: FileText,   badge: archive.length },
        ]}
      />

      {sub === "closed" && (
        <div className="-mx-4">
          <ClosedDecisionsCard decisionsAll={decisionsAll} />
        </div>
      )}

      {sub === "numbers" && (
        <div className="-mx-4 pt-3">
          {/* Risk metrics on top, then charts (lazy) */}
          <div className="px-4 pb-4 fade-up fade-up-1">
            <RiskMetricsCard
              casparHistory={casparHistory}
              sarahHistory={sarahHistory}
              macroHistory={macroHistory}
            />
          </div>
          <Suspense fallback={<HistorySkeleton />}>
            <HistoryPage
              casparHistory={casparHistory}
              sarahHistory={sarahHistory}
              macroHistory={macroHistory}
            />
          </Suspense>
        </div>
      )}

      {sub === "reports" && (
        <div className="-mx-4 pt-3">
          <ArchivePage archive={archive} dailyHistory={dailyHistory} />
        </div>
      )}
    </div>
  );
}
