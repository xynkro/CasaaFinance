import type { DashboardData } from "../data";
import { DailyBriefCard } from "../cards/DailyBriefCard";
import { HouseholdCard } from "../cards/HouseholdCard";
import { MacroStrip } from "../components/MacroStrip";

export function HomePage({ data, loading }: { data: DashboardData | null; loading: boolean }) {
  return (
    <div className="flex flex-col gap-4 px-4 pb-4">
      <MacroStrip macro={data?.macro ?? null} />
      <div className="fade-up fade-up-1">
        <DailyBriefCard row={data?.daily ?? null} loading={loading && !data} />
      </div>
      <div className="fade-up fade-up-2">
        <HouseholdCard
          caspar={data?.caspar ?? null}
          sarah={data?.sarah ?? null}
          macro={data?.macro ?? null}
        />
      </div>
    </div>
  );
}
