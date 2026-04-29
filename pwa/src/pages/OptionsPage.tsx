import { useState, useMemo, useEffect } from "react";
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
import { RecommendationCard, recKey } from "../cards/RecommendationCard";
import { StickyTabs } from "../components/StickyTabs";
import { Shield, Briefcase, Telescope, Lightbulb } from "lucide-react";
import { RecommendationDetailModal } from "../components/RecommendationDetailModal";

type Subtab = "defense" | "book" | "scan" | "ideas";
const LAST_KEY = "casaa_options_subtab";

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
  const [sub, setSub] = useState<Subtab>(() => {
    try {
      const saved = localStorage.getItem(LAST_KEY) as Subtab | null;
      if (saved === "defense" || saved === "book" || saved === "scan" || saved === "ideas") return saved;
    } catch {}
    return "book";
  });

  // Strategy Notes detail modal — store the SELECTED KEY (a stable string),
  // then look up the rec from recommendations on each render. This eliminates
  // any stale-closure issues that could happen if the array reference changes
  // mid-tap (e.g., during the 15-min auto-refresh).
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [debugTrail, setDebugTrail] = useState<string[]>([]);
  const handleSelectKey = (k: string) => {
    // Run the lookup INSIDE the handler so we can compare what was tapped
    // vs what find() returns. Then log both into the trail.
    const found = recommendations.find((r) => recKey(r) === k);
    const tappedSummary = k.split("|").slice(2).join("|");
    let foundSummary = "(NOT FOUND in recommendations)";
    if (found) {
      foundSummary = `${found.ticker}/${found.strategy}/${found.account}`;
    }
    const matchCount = recommendations.filter((r) => recKey(r) === k).length;
    setDebugTrail((prev) => [
      `tap: ${tappedSummary}\n  → find: ${foundSummary} (matches=${matchCount}, total=${recommendations.length})\n  → selectedKey: ${k.length} chars; modal should mount NOW`,
      ...prev.slice(0, 3),
    ]);
    setSelectedKey(k);
  };

  const selectedRec = useMemo(
    () => (selectedKey ? recommendations.find((r) => recKey(r) === selectedKey) ?? null : null),
    [selectedKey, recommendations],
  );

  // Track modal lifecycle in the debug trail so we can see if it mounts AND
  // immediately unmounts (vs not mounting at all)
  useEffect(() => {
    if (selectedRec) {
      const ticker = selectedRec.ticker;
      setDebugTrail((prev) => [`  ✓ MODAL MOUNTED: ${ticker} @ ${new Date().toLocaleTimeString()}`, ...prev.slice(0, 4)]);
      return () => {
        setDebugTrail((prev) => [`  ✗ MODAL UNMOUNTED (${ticker}) @ ${new Date().toLocaleTimeString()}`, ...prev.slice(0, 4)]);
      };
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRec?.ticker]);

  // ticker → latest TechnicalScoreRow lookup (for the modal)
  const techByTicker = useMemo(() => {
    const m = new Map<string, TechnicalScoreRow>();
    for (const t of technicalScores) {
      const existing = m.get(t.ticker);
      if (!existing || t.date > existing.date) m.set(t.ticker, t);
    }
    return m;
  }, [technicalScores]);

  const handleChange = (key: string) => {
    const next = key as Subtab;
    setSub(next);
    try { localStorage.setItem(LAST_KEY, next); } catch {}
  };

  // Badges
  const urgentDefense = optionsDefense.filter(
    (d) => d.severity === "CRITICAL" || d.severity === "HIGH",
  ).length;
  const openPositions = options.length;
  const scanCount = scanResults.length;
  const ideaCount = recommendations.filter(
    (r) => (r.status ?? "").toLowerCase() === "proposed",
  ).length;

  return (
    <div className="flex flex-col px-4 pb-4">
      {/* Sticky subtab selector — Defense first so urgent alerts are 1 tap away */}
      <StickyTabs
        active={sub}
        onChange={handleChange}
        tabs={[
          { key: "defense", label: "Defense", icon: Shield,    badge: urgentDefense },
          { key: "book",    label: "Book",    icon: Briefcase, badge: openPositions },
          { key: "scan",    label: "Scan",    icon: Telescope, badge: scanCount },
          { key: "ideas",   label: "Ideas",   icon: Lightbulb, badge: ideaCount },
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

      {sub === "scan" && (
        <div className="fade-up fade-up-1 mt-3">
          <ScanCard candidates={scanResults} />
        </div>
      )}

      {sub === "ideas" && (
        <div className="fade-up fade-up-1 mt-3">
          {/* DEBUG TRAIL — always visible so user can confirm taps are registering */}
          <div className="rounded-lg p-2 mb-3 bg-amber-500/8 border border-amber-500/30">
            <div className="text-[9px] font-bold uppercase tracking-wider text-amber-400 mb-1">
              🐛 Tap debug — last {debugTrail.length} captures (build 7e19d65)
            </div>
            {debugTrail.length === 0 ? (
              <div className="text-[10px] text-amber-300 italic">
                Waiting for taps. Tap any rec below — you should see a key appear here.
                If nothing appears, the click handler isn't firing.
              </div>
            ) : (
              debugTrail.map((line, i) => (
                <div key={i} className="text-[10px] text-amber-200 font-mono break-all leading-relaxed whitespace-pre-line mb-1.5 pb-1.5 border-b border-amber-500/10 last:border-0">
                  {line}
                </div>
              ))
            )}
            {debugTrail.length > 0 && (
              <button
                onClick={() => setDebugTrail([])}
                className="text-[9px] text-amber-400 underline mt-1"
              >
                clear
              </button>
            )}
          </div>
          <RecommendationCard
            recommendations={recommendations}
            onSelectKey={handleSelectKey}
          />
        </div>
      )}

      {/* Modal rendered at PAGE level (sibling of all cards). Looks up
          selectedRec by stable key, not by object reference. */}
      {selectedRec && (
        <RecommendationDetailModal
          rec={selectedRec}
          techScore={techByTicker.get(selectedRec.ticker) ?? null}
          onClose={() => setSelectedKey(null)}
        />
      )}
    </div>
  );
}
