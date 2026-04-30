import { lazy, Suspense, useState } from "react";
import type { DashboardData } from "../data";
import { DailyBriefCard } from "../cards/DailyBriefCard";
import { RiskPulseCard } from "../cards/RiskPulseCard";
import { MoversCard } from "../cards/MoversCard";
import { SectorMixCard } from "../cards/SectorMixCard";
import { WsrSummaryCard } from "../cards/WsrSummaryCard";
import { WsrLiteCard } from "../cards/WsrLiteCard";
import { MacroStrip } from "../components/MacroStrip";
import { StickyTabs, BookOpen, Newspaper } from "../components/StickyTabs";
import { Activity } from "lucide-react";
import { isWsrLiteFresh } from "../lib/wsrLiteParse";

// Lazy: WsrDetailModal pulls in `marked` (~30 KB). All three modals are
// only mounted when their open-state is true, so a tiny Suspense fallback
// (the modal entry animation masks the flash).
const BriefDetailModal = lazy(() =>
  import("../components/BriefDetailModal").then((m) => ({ default: m.BriefDetailModal })),
);
const WsrDetailModal = lazy(() =>
  import("../components/WsrDetailModal").then((m) => ({ default: m.WsrDetailModal })),
);
const WsrLiteDetailModal = lazy(() =>
  import("../components/WsrLiteDetailModal").then((m) => ({ default: m.WsrLiteDetailModal })),
);

type HomeSubTab = "daily" | "lite" | "wsr";

const LAST_SUB_KEY = "casaa_home_subtab";

function loadLastSub(): HomeSubTab {
  try {
    const v = localStorage.getItem(LAST_SUB_KEY);
    if (v === "wsr" || v === "daily" || v === "lite") return v;
  } catch {}
  return "daily";
}

export function HomePage({ data, loading }: { data: DashboardData | null; loading: boolean }) {
  const [briefOpen, setBriefOpen] = useState(false);
  const [wsrOpen, setWsrOpen] = useState(false);
  const [liteOpen, setLiteOpen] = useState(false);
  const [sub, setSub] = useState<HomeSubTab>(loadLastSub);

  const daily   = data?.daily ?? null;
  const wsr     = data?.wsrSummary ?? null;
  const wsrLite = data?.wsrLite ?? null;

  const handleSubChange = (key: string) => {
    const next = key as HomeSubTab;
    setSub(next);
    try { localStorage.setItem(LAST_SUB_KEY, next); } catch {}
  };

  const liteFresh = wsrLite ? isWsrLiteFresh(wsrLite.date) : false;

  return (
    <>
      <div className="flex flex-col px-4 pb-4">
        {/* Sticky sub-tab selector */}
        <StickyTabs
          active={sub}
          onChange={handleSubChange}
          tabs={[
            { key: "daily", label: "Daily",     icon: Newspaper, badge: daily ? 1 : 0 },
            { key: "lite",  label: "Mid-Week",  icon: Activity,  badge: liteFresh ? 1 : 0 },
            { key: "wsr",   label: "Weekly",    icon: BookOpen,  badge: wsr ? 1 : 0 },
          ]}
        />

        {/* MacroStrip scrolls away with content */}
        <MacroStrip macro={data?.macro ?? null} />

        {/* Primary card */}
        <div className="fade-up fade-up-1 mt-4">
          {sub === "daily" && (
            <DailyBriefCard
              row={daily}
              loading={loading && !data}
              onOpen={daily ? () => setBriefOpen(true) : undefined}
            />
          )}
          {sub === "lite" && (
            <WsrLiteCard
              wsrLite={wsrLite}
              loading={loading && !data}
              onOpen={wsrLite ? () => setLiteOpen(true) : undefined}
            />
          )}
          {sub === "wsr" && (
            <WsrSummaryCard
              wsr={wsr}
              loading={loading && !data}
              onOpen={wsr ? () => setWsrOpen(true) : undefined}
            />
          )}
        </div>

        <div className="fade-up fade-up-2 mt-4">
          <RiskPulseCard macro={data?.macro ?? null} />
        </div>

        <div className="fade-up fade-up-3 mt-4">
          <MoversCard
            casparPositions={data?.casparPositions ?? []}
            sarahPositions={data?.sarahPositions ?? []}
          />
        </div>

        <div className="fade-up fade-up-4 mt-4">
          <SectorMixCard
            casparPositions={data?.casparPositions ?? []}
            sarahPositions={data?.sarahPositions ?? []}
            macro={data?.macro ?? null}
          />
        </div>
      </div>

      {briefOpen && daily && (
        <Suspense fallback={null}>
          <BriefDetailModal row={daily} onClose={() => setBriefOpen(false)} />
        </Suspense>
      )}
      {wsrOpen && wsr && (
        <Suspense fallback={null}>
          <WsrDetailModal wsr={wsr} onClose={() => setWsrOpen(false)} />
        </Suspense>
      )}
      {liteOpen && wsrLite && (
        <Suspense fallback={null}>
          <WsrLiteDetailModal wsrLite={wsrLite} onClose={() => setLiteOpen(false)} />
        </Suspense>
      )}
    </>
  );
}
