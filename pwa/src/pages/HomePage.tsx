import { useState } from "react";
import type { DashboardData } from "../data";
import { DailyBriefCard } from "../cards/DailyBriefCard";
import { RiskPulseCard } from "../cards/RiskPulseCard";
import { MoversCard } from "../cards/MoversCard";
import { SectorMixCard } from "../cards/SectorMixCard";
import { WsrSummaryCard } from "../cards/WsrSummaryCard";
import { MacroStrip } from "../components/MacroStrip";
import { BriefDetailModal } from "../components/BriefDetailModal";

export function HomePage({ data, loading }: { data: DashboardData | null; loading: boolean }) {
  const [briefOpen, setBriefOpen] = useState(false);
  const daily = data?.daily ?? null;

  return (
    <>
      <div className="flex flex-col gap-4 px-4 pb-4">
        <MacroStrip macro={data?.macro ?? null} />

        {data?.wsrSummary && (
          <div className="fade-up fade-up-1">
            <WsrSummaryCard wsr={data.wsrSummary} />
          </div>
        )}

        <div className="fade-up fade-up-2">
          <DailyBriefCard
            row={daily}
            loading={loading && !data}
            onOpen={daily ? () => setBriefOpen(true) : undefined}
          />
        </div>

        <div className="fade-up fade-up-3">
          <RiskPulseCard macro={data?.macro ?? null} />
        </div>

        <div className="fade-up fade-up-4">
          <MoversCard
            casparPositions={data?.casparPositions ?? []}
            sarahPositions={data?.sarahPositions ?? []}
          />
        </div>

        <div className="fade-up fade-up-5">
          <SectorMixCard
            casparPositions={data?.casparPositions ?? []}
            sarahPositions={data?.sarahPositions ?? []}
            macro={data?.macro ?? null}
          />
        </div>
      </div>

      {briefOpen && daily && (
        <BriefDetailModal row={daily} onClose={() => setBriefOpen(false)} />
      )}
    </>
  );
}
