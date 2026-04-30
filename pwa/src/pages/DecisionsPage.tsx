import { useState } from "react";
import type {
  DecisionRow,
  TechnicalScoreRow,
  OptionsDefenseRow,
  WheelNextLegRow,
  ExitPlanRow,
} from "../data";
import { Card } from "../cards/Card";
import { BuyRecommendationsCard } from "../cards/BuyRecommendationsCard";
import { ActionQueueCard } from "../cards/ActionQueueCard";
import { StockDetail } from "../components/StockDetail";
import {
  Target,
  Clock,
  CheckCircle,
  XCircle,
  AlertTriangle,
  ChevronRight,
  Copy,
  Check,
  ExternalLink,
} from "lucide-react";

const OPTIONS_STRATEGIES = ["CSP", "CC", "PMCC", "LONG_CALL", "LONG_PUT"];
const SHARE_STRATEGIES = ["BUY_DIP", "TRIM", ""];

function fmtMoney(v: string | number | undefined): string {
  if (v === undefined || v === "") return "—";
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/**
 * Mantissa-aware money formatter for sub-cent option premiums.
 * Below $0.10 we render 4 decimals so $0.0095 doesn't get rounded to $0.01.
 */
function fmtMoneyMantissa(v: string | number | undefined): string {
  if (v === undefined || v === "") return "—";
  const n = Number(v);
  if (isNaN(n)) return "—";
  if (n > 0 && n < 0.1) {
    return `$${n.toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;
  }
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(v: string | number | undefined): string {
  if (v === undefined || v === "") return "—";
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${n.toFixed(1)}%`;
}

function fmtExpiry(expiry: string | undefined): string {
  if (!expiry) return "—";
  if (expiry.length === 8 && /^\d+$/.test(expiry)) {
    return `${expiry.slice(4, 6)}/${expiry.slice(6, 8)}`;
  }
  return expiry;
}

const STATUS_CONFIG: Record<string, {
  icon: typeof Target;
  bg: string;
  text: string;
  border: string;
  label: string;
}> = {
  pending: {
    icon: Clock,
    bg: "bg-amber-500/10",
    text: "text-amber-400",
    border: "border-amber-500/20",
    label: "Pending",
  },
  watching: {
    icon: Target,
    bg: "bg-blue-500/10",
    text: "text-blue-400",
    border: "border-blue-500/20",
    label: "Watching",
  },
  filled: {
    icon: CheckCircle,
    bg: "bg-emerald-500/10",
    text: "text-emerald-400",
    border: "border-emerald-500/20",
    label: "Filled",
  },
  killed: {
    icon: XCircle,
    bg: "bg-red-500/10",
    text: "text-red-400",
    border: "border-red-500/20",
    label: "Killed",
  },
  expired: {
    icon: AlertTriangle,
    bg: "bg-slate-500/10",
    text: "text-slate-400",
    border: "border-slate-500/20",
    label: "Expired",
  },
};

const DEFAULT_STATUS = STATUS_CONFIG.pending;

function ConvictionDots({ level }: { level: number }) {
  return (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          className={`w-1.5 h-1.5 rounded-full ${
            i <= level ? "bg-indigo-400" : "bg-slate-700"
          }`}
        />
      ))}
    </div>
  );
}

function OptionsSpecRow({ decision }: { decision: DecisionRow }) {
  const strike = Number(decision.strike) || 0;
  const conf = Number(decision.thesis_confidence) || 0;
  const confPct = Math.max(0, Math.min(1, conf)) * 100;
  const confColor = confPct >= 70 ? "#34d399" : confPct >= 50 ? "#818cf8" : "#fbbf24";
  const yldRaw = decision.annual_yield_pct;
  const yldNum = Number(yldRaw);
  // Suppress yield row when value is zero/empty/NaN (brain emits 0 for filled positions).
  const showYield = yldRaw !== undefined && yldRaw !== "" && !isNaN(yldNum) && yldNum !== 0;
  const delta = Number(decision.delta);
  const ivrRaw = decision.iv_rank;
  const ivrNum = Number(ivrRaw);
  // Suppress IVR (render "—") when value is zero/empty/NaN.
  const showIvr = ivrRaw !== undefined && ivrRaw !== "" && !isNaN(ivrNum) && ivrNum !== 0;

  return (
    <div
      style={{
        backgroundColor: "rgba(255,255,255,0.028)",
        border: "1px solid rgba(255,255,255,0.085)",
        borderRadius: 10,
        padding: "8px 10px",
        marginBottom: 12,
      }}
    >
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[length:var(--t-xs)] font-semibold text-slate-200 tabular-nums">
            ${strike.toFixed(strike < 10 ? 1 : 0)}{decision.right}
          </span>
          <span className="text-[length:var(--t-2xs)] text-slate-600">exp {fmtExpiry(decision.expiry)}</span>
        </div>
        <span className="text-[length:var(--t-2xs)] font-semibold uppercase tracking-wider" style={{ color: "#818cf8" }}>
          {decision.strategy}
        </span>
      </div>
      <div
        className="flex items-center flex-wrap gap-x-3 gap-y-1 text-[length:var(--t-2xs)] text-slate-500"
        style={{ marginBottom: 6 }}
      >
        <span>Premium <span className="text-slate-300 tabular-nums">{fmtMoneyMantissa(decision.premium_per_share)}</span></span>
        {showYield && (
          <span>Yield <span style={{ color: "#34d399" }} className="tabular-nums font-semibold">{fmtPct(yldNum)}</span></span>
        )}
        <span>Δ <span className="text-slate-300 tabular-nums">{isNaN(delta) ? "—" : delta.toFixed(2)}</span></span>
      </div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 text-[length:var(--t-2xs)] text-slate-500">
          <span>BE <span className="text-slate-300 tabular-nums">{fmtMoney(decision.breakeven)}</span></span>
          <span>IVR <span className="text-slate-300 tabular-nums">{showIvr ? ivrNum.toFixed(0) : "—"}</span></span>
        </div>
        {decision.thesis_confidence && (
          <div className="flex items-center gap-1.5 shrink-0">
            <span className="text-[length:var(--t-2xs)] text-slate-500">Conf</span>
            <div
              style={{
                width: 40,
                height: 4,
                borderRadius: 2,
                backgroundColor: "rgba(255,255,255,0.05)",
                overflow: "hidden",
              }}
            >
              <div style={{ height: "100%", width: `${confPct}%`, backgroundColor: confColor }} />
            </div>
            <span className="text-[length:var(--t-2xs)] font-semibold tabular-nums text-slate-300">
              {confPct.toFixed(0)}%
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function CardActions({ ticker }: { ticker: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!ticker) return;
    try {
      await navigator.clipboard.writeText(ticker);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API unavailable on http or older iOS — silently ignore.
    }
  };

  const handleOpenIbkr = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!ticker) return;
    const url = `https://www.interactivebrokers.com/en/index.php?f=2222&exch=NYSE&symbol=${encodeURIComponent(ticker)}`;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  // Stop pointer/touch events from bubbling so the parent card's tap doesn't fire.
  const stopAll = (e: React.SyntheticEvent) => e.stopPropagation();

  const baseBtn =
    "flex items-center gap-1 px-2 py-1 rounded-md border border-white/5 bg-white/3 hover:bg-white/5 active:bg-white/7 transition-colors text-[length:var(--t-2xs)]";

  return (
    <div
      className="flex items-center gap-1.5 shrink-0"
      onPointerDown={stopAll}
      onMouseDown={stopAll}
      onTouchStart={stopAll}
    >
      <button
        type="button"
        onClick={handleCopy}
        aria-label={`Copy ticker ${ticker}`}
        className={baseBtn}
      >
        {copied ? (
          <>
            <Check size={11} className="text-emerald-400" />
            <span className="text-emerald-400 font-medium">Copied</span>
          </>
        ) : (
          <>
            <Copy size={11} className="text-slate-500" />
            <span className="text-slate-400 font-medium">Copy</span>
          </>
        )}
      </button>
      <button
        type="button"
        onClick={handleOpenIbkr}
        aria-label={`Open ${ticker} in IBKR`}
        className={baseBtn}
      >
        <ExternalLink size={11} className="text-slate-500" />
        <span className="text-slate-400 font-medium">IBKR</span>
      </button>
    </div>
  );
}

function DecisionCard({ decision, onTap }: { decision: DecisionRow; onTap: () => void }) {
  const status = STATUS_CONFIG[decision.status?.toLowerCase()] ?? DEFAULT_STATUS;
  const Icon = status.icon;
  const conv = Math.round(Number(decision.conv) || 0);
  const showOptionsSpec = !!decision.strategy && OPTIONS_STRATEGIES.includes(decision.strategy);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onTap();
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onTap}
      onKeyDown={onKey}
      className={`w-full text-left glass rounded-2xl p-4 border ${status.border} active:bg-white/3 transition-colors cursor-pointer`}
    >
      {/* Header: ticker + status */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-10 h-10 rounded-xl bg-slate-700/50 flex items-center justify-center">
            <span className="text-[length:var(--t-xs)] font-bold text-slate-200">
              {decision.ticker?.slice(0, 4)}
            </span>
          </div>
          <div>
            <div className="text-[length:var(--t-sm)] font-semibold text-slate-100">{decision.ticker}</div>
            <div className="text-[length:var(--t-2xs)] text-slate-500 uppercase">{decision.account || "—"}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full ${status.bg}`}>
            <Icon size={12} className={status.text} />
            <span className={`text-[length:var(--t-xs)] font-semibold ${status.text}`}>{status.label}</span>
          </div>
          <ChevronRight size={14} className="text-slate-600" />
        </div>
      </div>

      {/* Thesis */}
      <p className="text-[length:var(--t-sm)] text-slate-300 leading-relaxed mb-3">{decision.thesis_1liner}</p>

      {/* Options-spec sub-row (only for option strategies) */}
      {showOptionsSpec && <OptionsSpecRow decision={decision} />}

      {/* Bucket + metrics row + actions */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-3 min-w-0">
          {decision.bucket && (
            <span className="text-[length:var(--t-2xs)] font-medium text-slate-500 uppercase bg-white/5 px-2 py-0.5 rounded">
              {decision.bucket}
            </span>
          )}
          {conv > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-[length:var(--t-2xs)] text-slate-500">Conv</span>
              <ConvictionDots level={conv} />
            </div>
          )}
        </div>
        <div className="flex items-center gap-3 text-[length:var(--t-xs)] tabular-nums">
          {decision.entry && (
            <span className="text-slate-500">
              Entry <span className="text-slate-300">${Number(decision.entry).toFixed(2)}</span>
            </span>
          )}
          {decision.target && (
            <span className="text-slate-500">
              Target <span className="text-emerald-400/80">${Number(decision.target).toFixed(2)}</span>
            </span>
          )}
        </div>
      </div>

      {/* Action strip */}
      <div className="flex items-center justify-end mt-2.5 pt-2.5 border-t border-white/5">
        <CardActions ticker={decision.ticker} />
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <Card>
      <div className="flex flex-col items-center gap-3 py-6">
        <div className="w-12 h-12 rounded-2xl bg-slate-700/50 flex items-center justify-center">
          <Target size={20} className="text-slate-500" />
        </div>
        <div className="text-center">
          <p className="text-[length:var(--t-sm)] font-medium text-slate-400">No decisions yet</p>
          <p className="text-[length:var(--t-xs)] text-slate-500 mt-0.5">
            Decisions from WSR will appear here
          </p>
        </div>
      </div>
    </Card>
  );
}

function SectionHeader({ label, count }: { label: string; count: number }) {
  return (
    <div className="flex items-center justify-between px-1">
      <span className="text-[length:var(--t-2xs)] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </span>
      <span className="text-[length:var(--t-2xs)] text-slate-600 tabular-nums">{count}</span>
    </div>
  );
}

// Sort key: pending → watching → filled → killed/expired → unknown
const STATUS_SORT_RANK: Record<string, number> = {
  pending: 0,
  watching: 1,
  filled: 2,
  killed: 3,
  expired: 3,
};
function statusSortKey(status: string | undefined): number {
  return STATUS_SORT_RANK[(status ?? "").toLowerCase()] ?? 4;
}

export function DecisionsPage({
  decisions,
  technicalScores,
  technicalScoresHistory,
  optionsDefense,
  wheelNextLeg,
  exitPlans,
}: {
  decisions: DecisionRow[];
  technicalScores?: TechnicalScoreRow[];
  technicalScoresHistory?: TechnicalScoreRow[];
  optionsDefense?: OptionsDefenseRow[];
  wheelNextLeg?: WheelNextLegRow[];
  exitPlans?: ExitPlanRow[];
}) {
  const [selected, setSelected] = useState<DecisionRow | null>(null);
  const techByTicker = new Map<string, TechnicalScoreRow>();
  for (const t of technicalScores ?? []) techByTicker.set(t.ticker, t);

  // If we have no WSR decisions, still show BuyRecommendationsCard if we have scores
  const showBuyRecs = (technicalScores?.length ?? 0) > 0;

  // Split decisions by strategy family
  const activeOptions = decisions
    .filter((d) => OPTIONS_STRATEGIES.includes(d.strategy ?? ""))
    .sort((a, b) => statusSortKey(a.status) - statusSortKey(b.status));

  const shareDecisions = decisions
    .filter((d) => SHARE_STRATEGIES.includes(d.strategy ?? ""))
    .sort((a, b) => statusSortKey(a.status) - statusSortKey(b.status));

  // Catch-all bucket for any unrecognised strategies — append to share section.
  const unrecognised = decisions.filter(
    (d) => !OPTIONS_STRATEGIES.includes(d.strategy ?? "") && !SHARE_STRATEGIES.includes(d.strategy ?? ""),
  );
  const shareDecisionsAll = [...shareDecisions, ...unrecognised].sort(
    (a, b) => statusSortKey(a.status) - statusSortKey(b.status),
  );

  // Count by status for the summary pills (whole page).
  const counts: Record<string, number> = {};
  for (const d of decisions) {
    const s = d.status?.toLowerCase() || "unknown";
    counts[s] = (counts[s] || 0) + 1;
  }

  let fadeIdx = 1;
  const nextFade = () => `fade-up fade-up-${Math.min(fadeIdx++, 4)}`;

  return (
    <>
      <div className="px-4 pb-4 flex flex-col gap-4">
        {/* Action Queue — only renders when non-empty */}
        <div className={nextFade()}>
          <ActionQueueCard
            optionsDefense={optionsDefense ?? []}
            wheelNextLeg={wheelNextLeg ?? []}
            exitPlans={exitPlans ?? []}
            technicalScores={technicalScores}
            technicalScoresHistory={technicalScoresHistory}
          />
        </div>

        {/* Buy recommendations from daily technical scan */}
        {showBuyRecs && (
          <div className={nextFade()}>
            <BuyRecommendationsCard
              technicalScores={technicalScores ?? []}
              technicalScoresHistory={technicalScoresHistory}
            />
          </div>
        )}

        {decisions.length > 0 ? (
          <>
            {/* Summary pills */}
            <div className="flex gap-2 overflow-x-auto no-scrollbar py-1 -mx-1 px-1">
              {Object.entries(counts).map(([status, count]) => {
                const cfg = STATUS_CONFIG[status] ?? DEFAULT_STATUS;
                return (
                  <div
                    key={status}
                    className={`shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full ${cfg.bg} border ${cfg.border}`}
                  >
                    <span className={`text-[length:var(--t-xs)] font-semibold ${cfg.text}`}>{count}</span>
                    <span className={`text-[length:var(--t-2xs)] ${cfg.text} opacity-70`}>{cfg.label}</span>
                  </div>
                );
              })}
            </div>

            {/* Active Options section */}
            {activeOptions.length > 0 && (
              <div className="flex flex-col gap-2.5">
                <SectionHeader label="Active Options" count={activeOptions.length} />
                {activeOptions.map((d, i) => (
                  <div key={`opt-${d.ticker}-${d.date}-${i}`}>
                    <DecisionCard decision={d} onTap={() => setSelected(d)} />
                  </div>
                ))}
              </div>
            )}

            {/* Share Decisions section */}
            {shareDecisionsAll.length > 0 && (
              <div className="flex flex-col gap-2.5">
                <SectionHeader label="Share Decisions" count={shareDecisionsAll.length} />
                {shareDecisionsAll.map((d, i) => (
                  <div key={`share-${d.ticker}-${d.date}-${i}`}>
                    <DecisionCard decision={d} onTap={() => setSelected(d)} />
                  </div>
                ))}
              </div>
            )}
          </>
        ) : !showBuyRecs && (
          <EmptyState />
        )}
      </div>

      {selected && (
        <StockDetail
          decision={selected}
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
