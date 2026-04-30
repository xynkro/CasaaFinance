import { useState } from "react";
import type { DecisionRow, TechnicalScoreRow } from "../data";
import { Card } from "../cards/Card";
import { BuyRecommendationsCard } from "../cards/BuyRecommendationsCard";
import { StockDetail } from "../components/StockDetail";
import { Target, Clock, CheckCircle, XCircle, AlertTriangle, ChevronRight } from "lucide-react";

const OPTIONS_STRATEGIES = ["CSP", "CC", "PMCC", "LONG_CALL", "LONG_PUT"];

function fmtMoney(v: string | number | undefined): string {
  if (v === undefined || v === "") return "—";
  const n = Number(v);
  if (isNaN(n)) return "—";
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
  const yld = Number(decision.annual_yield_pct);
  const delta = Number(decision.delta);
  const ivr = Number(decision.iv_rank);

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
          <span className="text-[11px] font-semibold text-slate-200 tabular-nums">
            ${strike.toFixed(strike < 10 ? 1 : 0)}{decision.right}
          </span>
          <span className="text-[9px] text-slate-600">exp {fmtExpiry(decision.expiry)}</span>
        </div>
        <span className="text-[9px] font-semibold uppercase tracking-wider" style={{ color: "#818cf8" }}>
          {decision.strategy}
        </span>
      </div>
      <div
        className="flex items-center flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-500"
        style={{ marginBottom: 6 }}
      >
        <span>Premium <span className="text-slate-300 tabular-nums">{fmtMoney(decision.premium_per_share)}</span></span>
        <span>Yield <span style={{ color: "#34d399" }} className="tabular-nums font-semibold">{fmtPct(yld)}</span></span>
        <span>Δ <span className="text-slate-300 tabular-nums">{isNaN(delta) ? "—" : delta.toFixed(2)}</span></span>
      </div>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 text-[10px] text-slate-500">
          <span>BE <span className="text-slate-300 tabular-nums">{fmtMoney(decision.breakeven)}</span></span>
          <span>IVR <span className="text-slate-300 tabular-nums">{isNaN(ivr) ? "—" : ivr.toFixed(0)}</span></span>
        </div>
        {decision.thesis_confidence && (
          <div className="flex items-center gap-1.5 shrink-0">
            <span className="text-[10px] text-slate-500">Conf</span>
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
            <span className="text-[10px] font-semibold tabular-nums text-slate-300">
              {confPct.toFixed(0)}%
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function DecisionCard({ decision, onTap }: { decision: DecisionRow; onTap: () => void }) {
  const status = STATUS_CONFIG[decision.status?.toLowerCase()] ?? DEFAULT_STATUS;
  const Icon = status.icon;
  const conv = Math.round(Number(decision.conv) || 0);
  const showOptionsSpec = !!decision.strategy && OPTIONS_STRATEGIES.includes(decision.strategy);

  return (
    <button
      onClick={onTap}
      className={`w-full text-left glass rounded-2xl p-4 border ${status.border} active:bg-white/3 transition-colors`}
    >
      {/* Header: ticker + status */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-10 h-10 rounded-xl bg-slate-700/50 flex items-center justify-center">
            <span className="text-xs font-bold text-slate-200">
              {decision.ticker?.slice(0, 4)}
            </span>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-100">{decision.ticker}</div>
            <div className="text-[10px] text-slate-500 uppercase">{decision.account || "—"}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full ${status.bg}`}>
            <Icon size={12} className={status.text} />
            <span className={`text-xs font-semibold ${status.text}`}>{status.label}</span>
          </div>
          <ChevronRight size={14} className="text-slate-600" />
        </div>
      </div>

      {/* Thesis */}
      <p className="text-sm text-slate-300 leading-relaxed mb-3">{decision.thesis_1liner}</p>

      {/* Options-spec sub-row (only for option strategies) */}
      {showOptionsSpec && <OptionsSpecRow decision={decision} />}

      {/* Bucket + metrics row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {decision.bucket && (
            <span className="text-[10px] font-medium text-slate-500 uppercase bg-white/5 px-2 py-0.5 rounded">
              {decision.bucket}
            </span>
          )}
          {conv > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-slate-500">Conv</span>
              <ConvictionDots level={conv} />
            </div>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs tabular-nums">
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
    </button>
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
          <p className="text-sm font-medium text-slate-400">No decisions yet</p>
          <p className="text-xs text-slate-500 mt-0.5">
            Decisions from WSR will appear here
          </p>
        </div>
      </div>
    </Card>
  );
}

export function DecisionsPage({
  decisions,
  technicalScores,
  technicalScoresHistory,
}: {
  decisions: DecisionRow[];
  technicalScores?: TechnicalScoreRow[];
  technicalScoresHistory?: TechnicalScoreRow[];
}) {
  const [selected, setSelected] = useState<DecisionRow | null>(null);
  const techByTicker = new Map<string, TechnicalScoreRow>();
  for (const t of technicalScores ?? []) techByTicker.set(t.ticker, t);

  // If we have no WSR decisions, still show BuyRecommendationsCard if we have scores
  const showBuyRecs = (technicalScores?.length ?? 0) > 0;

  // Group by status: pending/watching first, then filled, then killed/expired
  const order: Record<string, number> = { pending: 0, watching: 1, filled: 2, killed: 3, expired: 4 };
  const sorted = [...decisions].sort(
    (a, b) => (order[a.status?.toLowerCase()] ?? 5) - (order[b.status?.toLowerCase()] ?? 5),
  );

  // Count by status
  const counts: Record<string, number> = {};
  for (const d of decisions) {
    const s = d.status?.toLowerCase() || "unknown";
    counts[s] = (counts[s] || 0) + 1;
  }

  return (
    <>
      <div className="px-4 pb-4 flex flex-col gap-4">
        {/* Buy recommendations from daily technical scan */}
        {showBuyRecs && (
          <div className="fade-up fade-up-1">
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
                    <span className={`text-xs font-semibold ${cfg.text}`}>{count}</span>
                    <span className={`text-[10px] ${cfg.text} opacity-70`}>{cfg.label}</span>
                  </div>
                );
              })}
            </div>

            {/* Decision cards */}
            {sorted.map((d, i) => (
              <div key={`${d.ticker}-${d.date}-${i}`} className={`fade-up fade-up-${Math.min(i + 2, 4)}`}>
                <DecisionCard decision={d} onTap={() => setSelected(d)} />
              </div>
            ))}
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
