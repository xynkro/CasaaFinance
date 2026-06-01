import { useState } from "react";
import type {
  OptionRow,
  PositionRow,
  TechnicalScoreRow,
  WheelNextLegRow,
  ExitPlanRow,
  OptionsDefenseRow,
  HarvestScanRow,
  ScanResultRow,
  UoaAlertRow,
  GexRegimeRow,
} from "../data";
import { OptionsDefenseCard } from "../cards/OptionsDefenseCard";
import { GexRegimeBanner } from "../cards/GexRegimeBanner";
import { WheelCard } from "../cards/WheelCard";
import { WheelContinuationCard } from "../cards/WheelContinuationCard";
import { UoaFlowCard } from "../cards/UoaFlowCard";
import { HarvestContent } from "./HarvestPage";
import { StickyTabs } from "../components/StickyTabs";
import { Shield, Briefcase, Wheat, Activity } from "lucide-react";

type Subtab = "defense" | "book" | "harvest" | "flow";
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
  scanResults,
  uoaAlerts,
  gexRegime,
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
  scanResults: ScanResultRow[];
  uoaAlerts: UoaAlertRow[];
  gexRegime: GexRegimeRow[];
  loading: boolean;
}) {
  const [sub, setSub] = useState<Subtab>(() => {
    try {
      const saved = localStorage.getItem(LAST_KEY) as Subtab | null;
      if (saved === "defense" || saved === "book" || saved === "harvest" || saved === "flow") return saved;
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
  const harvestCount = harvestScan.filter((r) => r.strategy !== "HALTED").length + scanResults.length;
  const extremeFlow = uoaAlerts.filter((a) => Number(a.severity) >= 3).length;

  return (
    <div className="flex flex-col px-4 pb-4">
      {/* Pre-market dealer-gamma regime — the premium-selling risk gate */}
      {gexRegime.length > 0 && (
        <div className="fade-up fade-up-1 mb-3">
          <GexRegimeBanner rows={gexRegime} />
        </div>
      )}

      {/* Sticky subtab selector */}
      <StickyTabs
        active={sub}
        onChange={handleChange}
        tabs={[
          { key: "defense", label: "Defense", icon: Shield,    badge: urgentDefense },
          { key: "book",    label: "Book",    icon: Briefcase, badge: openPositions },
          { key: "harvest", label: "Harvest", icon: Wheat,     badge: harvestCount },
          { key: "flow",    label: "Flow",    icon: Activity,  badge: extremeFlow },
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
        <HarvestContent harvestScan={harvestScan} scanResults={scanResults} options={options} loading={loading} />
      )}

      {sub === "flow" && (
        <div className="fade-up fade-up-1 mt-3">
          <UoaFlowCard alerts={uoaAlerts} />
        </div>
      )}
    </div>
  );
}
