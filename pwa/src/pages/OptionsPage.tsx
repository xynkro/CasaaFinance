import type { OptionRow, OptionRecommendationRow, PositionRow } from "../data";
import { WheelCard } from "../cards/WheelCard";
import { RecommendationCard } from "../cards/RecommendationCard";

export function OptionsPage({
  options,
  recommendations,
  casparPositions,
  sarahPositions,
  loading,
}: {
  options: OptionRow[];
  recommendations: OptionRecommendationRow[];
  casparPositions: PositionRow[];
  sarahPositions: PositionRow[];
  loading: boolean;
}) {
  return (
    <div className="flex flex-col gap-4 px-4 pb-4">
      <div className="fade-up fade-up-1">
        <WheelCard
          options={options}
          casparPositions={casparPositions}
          sarahPositions={sarahPositions}
          loading={loading}
        />
      </div>

      <div className="fade-up fade-up-2">
        <RecommendationCard recommendations={recommendations} />
      </div>
    </div>
  );
}
