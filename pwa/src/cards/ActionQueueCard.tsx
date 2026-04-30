import { useState } from "react";
import type { OptionsDefenseRow, WheelNextLegRow, ExitPlanRow, TechnicalScoreRow } from "../data";
import { Card } from "./Card";
import { StockDetail } from "../components/StockDetail";
import { Zap, ChevronRight } from "lucide-react";

type ActionSource = "defense" | "wheel" | "exit";

interface ActionItem {
  source: ActionSource;
  ticker: string;
  account?: string;
  severity: number;     // numeric rank, 0 = highest
  severityLabel: string;
  severityColor: string; // hex/rgb for the dot
  text: string;          // 1-line action text
  // Optional payloads to support tap routing
  exitPlan?: ExitPlanRow;
}

const DEFENSE_SEVERITY_RANK: Record<string, number> = {
  CRITICAL: 0,
  HIGH: 1,
};

const WHEEL_STATUS_RANK: Record<string, number> = {
  LIKELY_ASSIGNED: 0,
  EXPIRING_WORTHLESS: 2,
  ROLL: 1,
};

const EXIT_STATUS_RANK: Record<string, number> = {
  STOP_TRIGGERED: 0,
  T1_HIT: 1,
  T2_HIT: 2,
  TIME_STOP: 2,
  BREACH_WARNING: 2,
};

// Rank semantics: 0=red (urgent), 1=amber (high), 2=blue (notable)
const RANK_DOT_COLOR: Record<number, string> = {
  0: "#f87171", // red-400
  1: "#fb923c", // orange-400 / amber
  2: "#60a5fa", // blue-400
};

const SOURCE_LABEL: Record<ActionSource, string> = {
  defense: "Defense",
  wheel: "Wheel",
  exit: "Exit",
};

const SOURCE_COLOR: Record<ActionSource, string> = {
  defense: "text-red-300",
  wheel: "text-indigo-300",
  exit: "text-emerald-300",
};

function buildActionItems({
  optionsDefense,
  wheelNextLeg,
  exitPlans,
}: {
  optionsDefense: OptionsDefenseRow[];
  wheelNextLeg: WheelNextLegRow[];
  exitPlans: ExitPlanRow[];
}): ActionItem[] {
  const items: ActionItem[] = [];

  // 1. Defense alerts (CRITICAL / HIGH only)
  for (const d of optionsDefense) {
    if (!(d.severity in DEFENSE_SEVERITY_RANK)) continue;
    const rank = DEFENSE_SEVERITY_RANK[d.severity];
    items.push({
      source: "defense",
      ticker: d.ticker,
      account: d.account,
      severity: rank,
      severityLabel: d.severity,
      severityColor: RANK_DOT_COLOR[rank] ?? RANK_DOT_COLOR[2],
      text: d.action || d.title,
    });
  }

  // 2. Wheel continuation triggers
  for (const w of wheelNextLeg) {
    if (!(w.current_status in WHEEL_STATUS_RANK)) continue;
    const rank = WHEEL_STATUS_RANK[w.current_status];
    items.push({
      source: "wheel",
      ticker: w.ticker,
      account: w.account,
      severity: rank,
      severityLabel: w.current_status,
      severityColor: RANK_DOT_COLOR[rank] ?? RANK_DOT_COLOR[2],
      text: w.recommendation || w.next_action,
    });
  }

  // 3. Exit-plan triggers
  for (const e of exitPlans) {
    if (!(e.status in EXIT_STATUS_RANK)) continue;
    const rank = EXIT_STATUS_RANK[e.status];
    items.push({
      source: "exit",
      ticker: e.ticker,
      account: e.account,
      severity: rank,
      severityLabel: e.status,
      severityColor: RANK_DOT_COLOR[rank] ?? RANK_DOT_COLOR[2],
      text: e.recommendation || e.reasoning,
      exitPlan: e,
    });
  }

  // Sort by severity asc (0 first), then by source priority (defense > wheel > exit)
  const sourcePriority: Record<ActionSource, number> = { defense: 0, wheel: 1, exit: 2 };
  items.sort((a, b) => {
    if (a.severity !== b.severity) return a.severity - b.severity;
    return sourcePriority[a.source] - sourcePriority[b.source];
  });
  return items;
}

function ActionRow({ item, onTap }: { item: ActionItem; onTap: () => void }) {
  return (
    <button
      type="button"
      onClick={onTap}
      className="w-full text-left flex items-start gap-2.5 px-3 py-2.5 rounded-xl border border-white/5 bg-white/3 hover:bg-white/5 active:bg-white/7 transition-colors"
    >
      {/* severity dot */}
      <div
        className="shrink-0 mt-1.5 w-2 h-2 rounded-full"
        style={{ backgroundColor: item.severityColor }}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[length:var(--t-sm)] font-bold text-slate-100">{item.ticker}</span>
          <span
            className={`text-[length:var(--t-2xs)] font-semibold uppercase tracking-wider ${SOURCE_COLOR[item.source]}`}
          >
            {SOURCE_LABEL[item.source]}
          </span>
          <span className="text-[length:var(--t-2xs)] text-slate-600 font-mono">
            {item.severityLabel.replace(/_/g, " ")}
          </span>
        </div>
        <p className="text-[length:var(--t-xs)] text-slate-300 leading-snug mt-0.5 line-clamp-2">
          {item.text || "—"}
        </p>
      </div>
      <ChevronRight size={14} className="text-slate-600 shrink-0 mt-1" />
    </button>
  );
}

export function ActionQueueCard({
  optionsDefense,
  wheelNextLeg,
  exitPlans,
  technicalScores,
  technicalScoresHistory,
}: {
  optionsDefense: OptionsDefenseRow[];
  wheelNextLeg: WheelNextLegRow[];
  exitPlans: ExitPlanRow[];
  technicalScores?: TechnicalScoreRow[];
  technicalScoresHistory?: TechnicalScoreRow[];
}) {
  const [selected, setSelected] = useState<ActionItem | null>(null);

  const items = buildActionItems({ optionsDefense, wheelNextLeg, exitPlans });

  // Empty state hides the card entirely.
  if (!items.length) return null;

  const techByTicker = new Map<string, TechnicalScoreRow>();
  for (const t of technicalScores ?? []) techByTicker.set(t.ticker, t);

  const urgentCount = items.filter((i) => i.severity === 0).length;
  const highCount = items.filter((i) => i.severity === 1).length;
  const otherCount = items.length - urgentCount - highCount;

  const headerColor = urgentCount > 0 ? "text-red-400" : highCount > 0 ? "text-orange-400" : "text-blue-400";

  return (
    <>
      <Card>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Zap size={14} className={headerColor} />
            <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Action Queue</h2>
          </div>
          <div className="flex items-center gap-1.5">
            {urgentCount > 0 && (
              <span className="px-2 py-0.5 rounded text-[length:var(--t-2xs)] font-bold bg-red-500/20 text-red-400 border border-red-500/30">
                {urgentCount} URGENT
              </span>
            )}
            {highCount > 0 && (
              <span className="px-2 py-0.5 rounded text-[length:var(--t-2xs)] font-bold bg-orange-500/20 text-orange-400 border border-orange-500/30">
                {highCount} HIGH
              </span>
            )}
            {otherCount > 0 && urgentCount + highCount === 0 && (
              <span className="px-2 py-0.5 rounded text-[length:var(--t-2xs)] font-bold bg-blue-500/20 text-blue-400 border border-blue-500/30">
                {otherCount}
              </span>
            )}
          </div>
        </div>
        <p className="text-[length:var(--t-2xs)] text-slate-600 mb-3 leading-relaxed">
          What needs action right now — from defense alerts, wheel continuation, and stop/target triggers.
        </p>
        <div className="space-y-1.5">
          {items.map((item, i) => (
            <ActionRow
              key={`${item.source}-${item.ticker}-${item.severityLabel}-${i}`}
              item={item}
              onTap={() => setSelected(item)}
            />
          ))}
        </div>
      </Card>

      {selected && (
        <StockDetail
          ticker={selected.ticker}
          techScore={techByTicker.get(selected.ticker)}
          techHistory={technicalScoresHistory}
          currency={selected.account?.toLowerCase() === "sarah" ? "SGD" : "USD"}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}
