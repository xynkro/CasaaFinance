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
  MacroLeanRow,
  ScanMetaRow,
  CuratedPickRow,
} from "../data";
import { Card } from "../cards/Card";
import { OptionsDefenseCard } from "../cards/OptionsDefenseCard";
import { GexRegimeBanner } from "../cards/GexRegimeBanner";
import { MacroLeanBanner } from "../cards/MacroLeanBanner";
import { ScanFreshnessBanner } from "../cards/ScanFreshnessBanner";
import { WheelCard } from "../cards/WheelCard";
import { WheelContinuationCard } from "../cards/WheelContinuationCard";
import { UoaFlowCard } from "../cards/UoaFlowCard";
import { HarvestContent } from "./HarvestPage";
import { StickyTabs } from "../components/StickyTabs";
import { Shield, Briefcase, Wheat, Activity, Target } from "lucide-react";

type Subtab = "defense" | "book" | "harvest" | "flow";
const LAST_KEY = "casaa_options_subtab";

/**
 * Motley Fool CSP-overlay targets — read-only. MF flagged these as recent Buys
 * trading near their recommended price; selling a cash-secured put is one way
 * to enter at (or below) MF's price. SUGGESTION-ONLY: nothing here is sized or
 * auto-traded — it's an engine input, not a signal. Renders null when empty.
 */
function MfOverlayTargetsCard({ overlay }: { overlay: CuratedPickRow[] }) {
  if (!overlay.length) return null;
  const seen = new Set<string>();
  const picks = overlay.filter((r) => {
    const t = (r.ticker || "").toUpperCase();
    if (!t || seen.has(t)) return false;
    seen.add(t);
    return true;
  });
  const fmtRec = (v?: string): string => {
    const n = Number(v);
    return v && !isNaN(n) ? `$${n.toFixed(2)}` : "—";
  };
  return (
    <Card>
      <div className="flex items-center gap-2 mb-1.5">
        <Target size={14} className="text-fuchsia-400" />
        <h3 className="text-[length:var(--t-sm)] font-medium text-slate-400">MF CSP Targets</h3>
        <span className="text-[length:var(--t-2xs)] text-slate-600">sell puts to enter at MF's price</span>
      </div>
      <p className="text-[length:var(--t-2xs)] text-slate-600 mb-2 leading-relaxed">
        Recent Motley Fool Buys near their rec price — suggestion-only, not auto-traded.
      </p>
      <div className="divide-y divide-white/5">
        {picks.map((r, i) => (
          <div key={`${r.ticker}-${i}`} className="flex items-center justify-between py-2">
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="text-[length:var(--t-sm)] font-bold text-white">{r.ticker}</span>
              {r.mf_type && <span className="text-[length:var(--t-2xs)] text-fuchsia-300">{r.mf_type}</span>}
            </div>
            <div className="flex flex-col items-end leading-tight shrink-0">
              <span className="text-[length:var(--t-xs)] font-semibold text-slate-300 tabular-nums">{fmtRec(r.rec_price)}</span>
              <span className="text-[length:var(--t-2xs)] text-slate-600">rec price</span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

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
  macroLean,
  scanMeta,
  mfOverlay,
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
  macroLean?: MacroLeanRow | null;
  scanMeta?: ScanMetaRow | null;
  mfOverlay?: CuratedPickRow[];
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
      {/* Last-scan freshness — quiet when current, amber when a recent run left
          the candidates frozen (the stale-data case). */}
      {scanMeta && (
        <div className="fade-up fade-up-1 mb-3">
          <ScanFreshnessBanner scanMeta={scanMeta} scanResults={scanResults} />
        </div>
      )}

      {/* Pre-market dealer-gamma regime — the premium-selling risk gate */}
      {gexRegime.length > 0 && (
        <div className="fade-up fade-up-1 mb-3">
          <GexRegimeBanner rows={gexRegime} />
        </div>
      )}

      {/* Macro-surprise lean — what today's releases mean, and how the plan tilts */}
      {macroLean?.net_lean && (
        <div className="fade-up fade-up-1 mb-3">
          <MacroLeanBanner macroLean={macroLean} />
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
          {/* Motley Fool CSP-overlay targets — read-only, suggestion-only.
              Renders null when empty via the card's own guard. */}
          {(mfOverlay?.length ?? 0) > 0 && (
            <div className="fade-up fade-up-2 mt-3">
              <MfOverlayTargetsCard overlay={mfOverlay ?? []} />
            </div>
          )}
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
