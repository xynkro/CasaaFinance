import type { DashboardData } from "../data";
import { DailyBriefCard } from "../cards/DailyBriefCard";
import { RiskPulseCard } from "../cards/RiskPulseCard";
import { MoversCard } from "../cards/MoversCard";
import { SectorMixCard } from "../cards/SectorMixCard";
import { MacroStrip } from "../components/MacroStrip";

export function HomePage({ data, loading }: { data: DashboardData | null; loading: boolean }) {
  return (
    <div className="flex flex-col gap-4 px-4 pb-4">
      <MacroStrip macro={data?.macro ?? null} />

      <div className="fade-up fade-up-1">
        <DailyBriefCard row={data?.daily ?? null} loading={loading && !data} />
      </div>

      <div className="fade-up fade-up-2">
        <RiskPulseCard macro={data?.macro ?? null} />
      </div>

      <div className="fade-up fade-up-3">
        <MoversCard
          casparPositions={data?.casparPositions ?? []}
          sarahPositions={data?.sarahPositions ?? []}
        />
      </div>

      <div className="fade-up fade-up-4">
        <SectorMixCard
          casparPositions={data?.casparPositions ?? []}
          sarahPositions={data?.sarahPositions ?? []}
          macro={data?.macro ?? null}
        />
      </div>
    </div>
  );
}
