import type {
  OptionRow,
  OptionRecommendationRow,
  PositionRow,
  TechnicalScoreRow,
  WheelNextLegRow,
} from "../data";
import { WheelCard } from "../cards/WheelCard";
import { WheelContinuationCard } from "../cards/WheelContinuationCard";
import { RecommendationCard } from "../cards/RecommendationCard";

export function OptionsPage({
  options,
  recommendations,
  technicalScores,
  wheelNextLeg,
  casparPositions,
  sarahPositions,
  loading,
}: {
  options: OptionRow[];
  recommendations: OptionRecommendationRow[];
  technicalScores: TechnicalScoreRow[];
  wheelNextLeg: WheelNextLegRow[];
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
          technicalScores={technicalScores}
          loading={loading}
        />
      </div>

      <div className="fade-up fade-up-2">
        <WheelContinuationCard rows={wheelNextLeg} />
      </div>

      <div className="fade-up fade-up-3">
        <RecommendationCard recommendations={recommendations} />
      </div>
    </div>
  );
}
