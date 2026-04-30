import type { ExitPlanRow } from "../data";
import { Shield, Target, AlertTriangle, TrendingUp, Package, CheckCircle2, Clock } from "lucide-react";

// ---------- Status styling ----------

export const STATUS_META: Record<string, {
  label: string;
  bg: string;
  border: string;
  text: string;
  icon: typeof Shield;
}> = {
  HEALTHY: {
    label: "Healthy",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/20",
    text: "text-emerald-400",
    icon: CheckCircle2,
  },
  WARNING: {
    label: "Warning",
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
    text: "text-amber-400",
    icon: AlertTriangle,
  },
  STOP_TRIGGERED: {
    label: "Stop Hit",
    bg: "bg-red-500/10",
    border: "border-red-500/20",
    text: "text-red-400",
    icon: AlertTriangle,
  },
  T1_HIT: {
    label: "T1 Hit",
    bg: "bg-indigo-500/10",
    border: "border-indigo-500/20",
    text: "text-indigo-400",
    icon: Target,
  },
  T2_HIT: {
    label: "T2 Hit",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/20",
    text: "text-emerald-400",
    icon: TrendingUp,
  },
  BAG: {
    label: "Bag",
    bg: "bg-red-500/15",
    border: "border-red-500/30",
    text: "text-red-400",
    icon: Package,
  },
  TIME_STOP: {
    label: "Time Stop",
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
    text: "text-amber-400",
    icon: Clock,
  },
  PROFIT_TARGET_HIT: {
    label: "Close Target",
    bg: "bg-emerald-500/15",
    border: "border-emerald-500/30",
    text: "text-emerald-400",
    icon: CheckCircle2,
  },
  ROLL_OR_ASSIGN: {
    label: "Roll/Assign",
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
    text: "text-amber-400",
    icon: AlertTriangle,
  },
  LET_EXPIRE: {
    label: "Let Expire",
    bg: "bg-slate-500/10",
    border: "border-slate-500/20",
    text: "text-slate-400",
    icon: Clock,
  },
  BREACH_WARNING: {
    label: "Breach Risk",
    bg: "bg-red-500/10",
    border: "border-red-500/20",
    text: "text-red-400",
    icon: AlertTriangle,
  },
  CATALYST_WARNING: {
    label: "Catalyst",
    bg: "bg-orange-500/10",
    border: "border-orange-500/20",
    text: "text-orange-400",
    icon: AlertTriangle,
  },
  HOLD: {
    label: "Hold",
    bg: "bg-slate-500/10",
    border: "border-slate-500/20",
    text: "text-slate-400",
    icon: Shield,
  },
};

const CATEGORY_LABEL: Record<string, string> = {
  blue_chip: "Blue Chip",
  etf_broad: "Broad ETF",
  etf_commodity: "Commodity ETF",
  etf_leveraged: "Leveraged ETF",
  speculative: "Speculative",
  option: "Option",
};

function fmtPrice(v: string | number, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n) || n === 0) return "—";
  return `${prefix}${n.toFixed(2)}`;
}

function fmtPct(v: string | number): string {
  const n = Number(v) * 100;
  if (isNaN(n)) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
}

// ---------- Compact badge (for PositionsTable rows) ----------

export function ExitStatusBadge({ plan }: { plan: ExitPlanRow | null | undefined }) {
  if (!plan) return null;
  const meta = STATUS_META[plan.status] ?? STATUS_META.HOLD;
  const Icon = meta.icon;
  return (
    <div className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-bold border ${meta.bg} ${meta.border}`}>
      <Icon size={9} className={meta.text} />
      <span className={meta.text}>{meta.label}</span>
    </div>
  );
}

// ---------- Full exit plan panel (for StockDetail) ----------

export function ExitPlanPanel({ plan }: { plan: ExitPlanRow }) {
  const isOption = plan.position_type?.startsWith("OPTION");
  const isBag = plan.status === "BAG";
  const meta = STATUS_META[plan.status] ?? STATUS_META.HOLD;
  const Icon = meta.icon;

  const entry = Number(plan.entry);
  const current = Number(plan.current);
  const stop = Number(plan.stop_loss);
  const t1 = Number(plan.target_1);
  const t2 = Number(plan.target_2);
  const uplPct = Number(plan.upl_pct) * 100;

  // Progress bar: position current price within stop → T2 range
  const range = Math.max(t2 - stop, 0.01);
  const position = Math.max(0, Math.min(1, (current - stop) / range));

  return (
    <div className="px-4 py-4 border-b border-white/6 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield size={14} className="text-indigo-400" />
          <h3 className="text-[length:var(--t-sm)] font-semibold text-slate-200">Exit Plan</h3>
        </div>
        <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-md border ${meta.bg} ${meta.border}`}>
          <Icon size={11} className={meta.text} />
          <span className={`text-[length:var(--t-2xs)] font-bold ${meta.text}`}>{meta.label}</span>
        </div>
      </div>

      {/* Category + key info */}
      <div className="flex items-center gap-2 text-[length:var(--t-2xs)] text-slate-500">
        <span className="px-1.5 py-0.5 rounded bg-white/5 text-slate-400 font-semibold">
          {CATEGORY_LABEL[plan.category] ?? plan.category}
        </span>
        {plan.is_blue_chip === "TRUE" && (
          <span className="text-[length:var(--t-2xs)] text-indigo-400">monitor-only</span>
        )}
        {Number(plan.time_stop_days) > 0 && (
          <span>Time stop: {plan.time_stop_days}d</span>
        )}
      </div>

      {/* Recommendation — the actionable line */}
      <div className={`rounded-lg p-3 border ${meta.bg} ${meta.border}`}>
        <p className={`text-[length:var(--t-xs)] font-semibold leading-relaxed ${meta.text}`}>
          {plan.recommendation}
        </p>
        {plan.reasoning && (
          <p className="text-[length:var(--t-2xs)] text-slate-500 mt-1 leading-relaxed">
            {plan.reasoning}
          </p>
        )}
      </div>

      {/* Stock-specific metrics */}
      {!isOption && !isBag && (
        <>
          {/* Stop — Current — T1 — T2 bar */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[length:var(--t-2xs)]">
              <span className="text-red-400 tabular-nums font-semibold">{fmtPrice(stop)}</span>
              <span className="text-slate-500">stop</span>
              <span className="flex-1 text-center text-slate-600">·</span>
              <span className="text-slate-500">targets</span>
              <span className="text-indigo-400 tabular-nums font-semibold">{fmtPrice(t1)}</span>
              <span className="text-slate-600">·</span>
              <span className="text-emerald-400 tabular-nums font-semibold">{fmtPrice(t2)}</span>
            </div>
            {/* Visual bar */}
            <div className="relative h-1.5 rounded-full bg-white/5 overflow-hidden">
              <div className="absolute inset-y-0 left-0 bg-gradient-to-r from-red-500/40 via-amber-500/30 to-emerald-500/40 w-full" />
              {/* Position marker */}
              <div
                className="absolute top-1/2 -translate-y-1/2 w-2 h-2 rounded-full bg-white border border-slate-900"
                style={{ left: `calc(${position * 100}% - 4px)` }}
              />
            </div>
            <div className="flex items-center justify-between text-[length:var(--t-2xs)]">
              <span className="text-slate-600">Entry: <span className="text-slate-400 tabular-nums">{fmtPrice(entry)}</span></span>
              <span className="text-slate-600">Current: <span className="text-white tabular-nums font-semibold">{fmtPrice(current)}</span></span>
              <span className={`tabular-nums font-semibold ${uplPct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {fmtPct(plan.upl_pct)}
              </span>
            </div>
          </div>

          {/* Rule references */}
          <div className="grid grid-cols-3 gap-1.5 text-[length:var(--t-2xs)]">
            <div className="glass rounded-lg p-2">
              <div className="text-slate-600">Stop rule</div>
              <div className="tabular-nums text-slate-300 capitalize">
                {plan.stop_key?.replace("_", " ") || "—"}
              </div>
            </div>
            <div className="glass rounded-lg p-2">
              <div className="text-slate-600">Distance to T1</div>
              <div className="tabular-nums text-indigo-400">
                {t1 > 0 && current > 0 ? `+${((t1 - current) / current * 100).toFixed(1)}%` : "—"}
              </div>
            </div>
            <div className="glass rounded-lg p-2">
              <div className="text-slate-600">Distance to stop</div>
              <div className="tabular-nums text-red-400">
                {stop > 0 && current > 0 ? `${((stop - current) / current * 100).toFixed(1)}%` : "—"}
              </div>
            </div>
          </div>
        </>
      )}

      {/* Bag: show entry + current + drawdown */}
      {isBag && !isOption && (
        <div className="grid grid-cols-2 gap-1.5 text-[length:var(--t-2xs)]">
          <div className="glass rounded-lg p-2">
            <div className="text-slate-600">Entry</div>
            <div className="tabular-nums text-slate-300">{fmtPrice(entry)}</div>
          </div>
          <div className="glass rounded-lg p-2">
            <div className="text-slate-600">Drawdown</div>
            <div className="tabular-nums text-red-400 font-bold">{fmtPct(plan.upl_pct)}</div>
          </div>
        </div>
      )}

      {/* Option-specific metrics */}
      {isOption && (
        <div className="grid grid-cols-3 gap-1.5 text-[length:var(--t-2xs)]">
          <div className="glass rounded-lg p-2">
            <div className="text-slate-600">Credit received</div>
            <div className="tabular-nums text-slate-300">{fmtPrice(entry)}</div>
          </div>
          <div className="glass rounded-lg p-2">
            <div className="text-slate-600">Current price</div>
            <div className="tabular-nums text-slate-300">{fmtPrice(current)}</div>
          </div>
          <div className="glass rounded-lg p-2">
            <div className="text-slate-600">Captured</div>
            <div className={`tabular-nums font-semibold ${
              Number(plan.profit_capture_pct) >= 50 ? "text-emerald-400" : "text-slate-300"
            }`}>
              {Number(plan.profit_capture_pct).toFixed(0)}%
            </div>
          </div>
          <div className="glass rounded-lg p-2 col-span-3">
            <div className="text-slate-600">Close at 50% target</div>
            <div className="tabular-nums text-emerald-400 font-semibold">{fmtPrice(plan.target_close_at)}</div>
          </div>
        </div>
      )}
    </div>
  );
}
