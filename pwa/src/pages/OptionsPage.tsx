import type {
  OptionRow,
  OptionRecommendationRow,
  PositionRow,
  TechnicalScoreRow,
  WheelNextLegRow,
  ScanResultRow,
  ExitPlanRow,
  OptionsDefenseRow,
} from "../data";
import { OptionsDefenseCard } from "../cards/OptionsDefenseCard";
import { WheelCard } from "../cards/WheelCard";
import { WheelContinuationCard } from "../cards/WheelContinuationCard";
import { ScanCard } from "../cards/ScanCard";
import { RecommendationCard } from "../cards/RecommendationCard";

export function OptionsPage({
  options,
  recommendations,
  technicalScores,
  wheelNextLeg,
  scanResults,
  exitPlans,
  optionsDefense,
  casparPositions,
  sarahPositions,
  loading,
}: {
  options: OptionRow[];
  recommendations: OptionRecommendationRow[];
  technicalScores: TechnicalScoreRow[];
  wheelNextLeg: WheelNextLegRow[];
  scanResults: ScanResultRow[];
  exitPlans: ExitPlanRow[];
  optionsDefense: OptionsDefenseRow[];
  casparPositions: PositionRow[];
  sarahPositions: PositionRow[];
  loading: boolean;
}) {
  return (
    <div className="flex flex-col gap-4 px-4 pb-4">
      {/* DAILY DEFENSE — the most urgent, always-first */}
      <div className="fade-up fade-up-1">
        <OptionsDefenseCard alerts={optionsDefense} />
      </div>

      {/* Open positions */}
      <div className="fade-up fade-up-2">
        <WheelCard
          options={options}
          casparPositions={casparPositions}
          sarahPositions={sarahPositions}
          technicalScores={technicalScores}
          exitPlans={exitPlans}
          loading={loading}
        />
      </div>

      {/* What to do when each expires (weeks out) */}
      <div className="fade-up fade-up-3">
        <WheelContinuationCard rows={wheelNextLeg} />
      </div>

      {/* Fresh daily scan — new idea generation */}
      <div className="fade-up fade-up-4">
        <ScanCard candidates={scanResults} />
      </div>

      {/* Weekly strategy notes — bottom, contextual only */}
      <div className="fade-up fade-up-5">
        <RecommendationCard recommendations={recommendations} />
      </div>
    </div>
  );
}
