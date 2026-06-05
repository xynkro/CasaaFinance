import { lazy, Suspense, useState } from "react";
import type { DashboardData } from "../data";
import { DailyBriefCard } from "../cards/DailyBriefCard";
import { RiskPulseCard } from "../cards/RiskPulseCard";
import { MoversCard } from "../cards/MoversCard";
import { SectorMixCard } from "../cards/SectorMixCard";
import { WsrSummaryCard } from "../cards/WsrSummaryCard";
import { WsrLiteCard } from "../cards/WsrLiteCard";
import { UpcomingCalendarsCard } from "../cards/UpcomingCalendarsCard";
import { ConcentrationCard } from "../cards/ConcentrationCard";
import { GovConfluenceCard } from "../cards/GovConfluenceCard";
import { CongressTradesCard } from "../cards/CongressTradesCard";
import { TldrTodayCard } from "../cards/TldrTodayCard";
import { PaperStatusCard } from "../cards/PaperStatusCard";
import { TodaysPlanCard } from "../cards/TodaysPlanCard";
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
  } catch {
    // ignore — localStorage may be disabled (private mode / quota)
  }
  return "daily";
}

export function HomePage({
  data,
  loading,
  onJumpTab,
}: {
  data: DashboardData | null;
  loading: boolean;
  onJumpTab?: (tabIndex: number) => void;
}) {
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
    try { localStorage.setItem(LAST_SUB_KEY, next); } catch {
      // ignore
    }
  };

  const liteFresh = wsrLite ? isWsrLiteFresh(wsrLite.date) : false;

  // Tab indices: Decisions=3, Options=2 (matches TAB_TITLES in App.tsx).
  const jumpDecisions = () => onJumpTab?.(3);
  const jumpOptions = () => onJumpTab?.(2);
  // Portfolio is tab 1; sub-tab index 2 = Paper (see PortfolioPage SwipeTabs).
  const jumpPaper = () => {
    try { localStorage.setItem("casaa_portfolio_subtab", "2"); } catch { /* ignore */ }
    onJumpTab?.(1);
  };

  return (
    <>
      <div className="flex flex-col px-4 pb-4">
        {/* TL;DR Today — single-row "what matters now" strip. Renders null
            on calm days. Lives ABOVE the StickyTabs so it's the first
            thing visible when Home opens. */}
        <div className="mb-2 fade-up fade-up-1">
          <TldrTodayCard
            decisions={data?.decisions ?? []}
            optionsDefense={data?.optionsDefense ?? []}
            earnings={data?.earnings ?? []}
            economicEvents={data?.economicEvents ?? []}
            livePrices={data?.livePrices ?? new Map()}
            exposurePosture={data?.exposurePosture ?? null}
            tvSignals={data?.tvSignals}
            casparPositions={data?.casparPositions ?? []}
            sarahPositions={data?.sarahPositions ?? []}
            onJumpDecisions={jumpDecisions}
            onJumpOptions={jumpOptions}
          />
        </div>

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
        <MacroStrip
          macro={data?.macro ?? null}
          regimeSignals={data?.regimeSignalsLatest}
        />

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

        {/* Paper auto-trader — clearly separated from real money; renders only
            once the bot is active. Taps through to Portfolio → Paper. */}
        <div className="fade-up fade-up-2 mt-3">
          <PaperStatusCard
            snapshot={data?.alpaca ?? null}
            positions={data?.alpacaPositions ?? []}
            onOpen={jumpPaper}
          />
        </div>

        {/* Today's Plan — the unified recommendation list the auto-trader will
            execute (core + hedge + protector + opportunities). This is the
            "what's the bot doing" surface; recommendation == execution. */}
        {(data?.dailyPlan?.length ?? 0) > 0 && (
          <div className="fade-up fade-up-2 mt-3">
            <TodaysPlanCard plan={data?.dailyPlan ?? []} newsByTicker={data?.newsByTicker} />
          </div>
        )}

        {/* Concentration alert — single-ticker over-exposure. Only renders
            when at least one position crosses 30% of NLV. Risk parity audit
            covers asset-class diversification; this catches the orthogonal
            "all my equity_us is just NVDA" risk. */}
        <div className="fade-up fade-up-2 mt-4">
          <ConcentrationCard
            casparPositions={data?.casparPositions ?? []}
            sarahPositions={data?.sarahPositions ?? []}
            casparSnapshot={data?.caspar ?? null}
            sarahSnapshot={data?.sarah ?? null}
          />
        </div>

        {/* Week-ahead earnings + macro events (Phase 6 — Finnhub-driven).
            Renders null when both lists are empty so first-deploy doesn't
            show a stub card. */}
        <div className="fade-up fade-up-3 mt-4">
          <UpcomingCalendarsCard
            earnings={data?.earnings ?? []}
            events={data?.economicEvents ?? []}
          />
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

        <div className="fade-up fade-up-4 mt-4">
          <GovConfluenceCard signals={data?.govConfluence ?? []} />
        </div>

        <div className="fade-up fade-up-4 mt-4">
          <CongressTradesCard trades={data?.congressTrades ?? []} />
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
