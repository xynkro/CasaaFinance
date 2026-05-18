import { useState } from "react";
import type {
  OptionRow,
  PositionRow,
  TechnicalScoreRow,
  WheelNextLegRow,
  ExitPlanRow,
  OptionsDefenseRow,
  HarvestScanRow,
} from "../data";
import { OptionsDefenseCard } from "../cards/OptionsDefenseCard";
import { WheelCard } from "../cards/WheelCard";
import { WheelContinuationCard } from "../cards/WheelContinuationCard";
import { HarvestContent } from "./HarvestPage";
import { StickyTabs } from "../components/StickyTabs";
import { Shield, Briefcase, Wheat } from "lucide-react";

type Subtab = "defense" | "book" | "harvest";
const LAST_KEY = "casaa_options_subtab";

export function OptionsPage({
  options,
  technicalScores,
  wheelNextLeg,
  exitPlans,
  optionsDefense,
  casparPositions,
  sarahPositions,
  harvestScan,
  loading,
}: {
  options: OptionRow[];
  technicalScores: TechnicalScoreRow[];
  wheelNextLeg: WheelNextLegRow[];
  exitPlans: ExitPlanRow[];
  optionsDefense: OptionsDefenseRow[];
  casparPositions: PositionRow[];
  sarahPositions: PositionRow[];
  harvestScan: HarvestScanRow[];
  loading: boolean;
}) {
  const [sub, setSub] = useState<Subtab>(() => {
    try {
      const saved = localStorage.getItem(LAST_KEY) as Subtab | null;
      if (saved === "defense" || saved === "book" || saved === "harvest") return saved;
    } catch {
      // ignore
    }
    return "book";
  });

  const handleChange = (key: string) => {
    const next = key as Subtab;
    setSub(next);
    try { localStorage.setItem(LAST_KEY, next); } catch {
      // ignore
    }
  };

  // Badges
  const urgentDefense = optionsDefense.filter(
    (d) => d.severity === "CRITICAL" || d.severity === "HIGH",
  ).length;
  const openPositions = options.length;
  const harvestCount = harvestScan.filter((r) => r.strategy !== "HALTED").length;

  return (
    <div className="flex flex-col px-4 pb-4">
      {/* Sticky subtab selector — Defense first so urgent alerts are 1 tap away */}
      <StickyTabs
        active={sub}
        onChange={handleChange}
        tabs={[
          { key: "defense", label: "Defense", icon: Shield,    badge: urgentDefense },
          { key: "book",    label: "Book",    icon: Briefcase, badge: openPositions },
          { key: "harvest", label: "Harvest", icon: Wheat,     badge: harvestCount },
        ]}
      />

      {sub === "defense" && (
        <div className="fade-up fade-up-1 mt-3">
          <OptionsDefenseCard alerts={optionsDefense} />
        </div>
      )}

      {sub === "book" && (
        <>
          <div className="fade-up fade-up-1 mt-3">
            <WheelCard
              options={options}
              casparPositions={casparPositions}
              sarahPositions={sarahPositions}
              technicalScores={technicalScores}
              exitPlans={exitPlans}
              loading={loading}
            />
          </div>
          <div className="fade-up fade-up-2 mt-3">
            <WheelContinuationCard rows={wheelNextLeg} />
          </div>
        </>
      )}

      {sub === "harvest" && (
        <HarvestContent harvestScan={harvestScan} options={options} loading={loading} />
      )}
    </div>
  );
}
