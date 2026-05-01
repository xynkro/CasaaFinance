import { useState, useMemo } from "react";
import type { DecisionRow } from "../data";
import { Card } from "./Card";
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  Target,
  TrendingUp,
  ChevronRight,
  X,
} from "lucide-react";
import { shortDate } from "../lib/dates";

// ---------- types & constants ----------

type Window = "7d" | "30d" | "90d" | "all";
const CLOSED_STATUSES = new Set(["filled", "killed", "expired"]);

// ---------- helpers ----------

function num(v: string | undefined): number {
  return !v ? 0 : Number(v) || 0;
}

function dayKey(d: string): string {
  return d.slice(0, 10);
}

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function filterByWindow(rows: DecisionRow[], w: Window): DecisionRow[] {
  if (w === "all" || !rows.length) return rows;
  const days = w === "7d" ? 7 : w === "30d" ? 30 : 90;
  const cutoff = daysAgo(days);
  return rows.filter((r) => dayKey(r.date) >= cutoff);
}

// ---------- Window pills ----------

function WindowPills({ value, onChange }: { value: Window; onChange: (w: Window) => void }) {
  const opts: { key: Window; label: string }[] = [
    { key: "7d",  label: "7d" },
    { key: "30d", label: "30d" },
    { key: "90d", label: "90d" },
    { key: "all", label: "All" },
  ];
  return (
    <div className="flex gap-1">
      {opts.map((o) => {
        const active = value === o.key;
        return (
          <button
            key={o.key}
            onClick={() => onChange(o.key)}
            className="px-2.5 py-1 rounded-md font-semibold transition-all"
            style={{
              fontSize: "var(--t-2xs)",
              background: active
                ? `rgba(var(--accent-rgb), 0.16)`
                : "transparent",
              color: active ? `rgb(var(--accent-rgb))` : "rgb(100 116 139)",
              border: active
                ? `1px solid rgba(var(--accent-rgb), 0.30)`
                : "1px solid transparent",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

// ---------- Headline scorecard ----------

interface HeadlineStats {
  total: number;
  filled: number;
  killed: number;
  expired: number;
  hitRate: number;          // 0-1
  avgConvFilled: number;    // 0-5
  avgConvKilled: number;
  avgConfFilled: number;    // 0-1
  avgConfKilled: number;
}

function computeHeadline(rows: DecisionRow[]): HeadlineStats {
  let filled = 0, killed = 0, expired = 0;
  let convFilledSum = 0, convFilledN = 0;
  let convKilledSum = 0, convKilledN = 0;
  let confFilledSum = 0, confFilledN = 0;
  let confKilledSum = 0, confKilledN = 0;

  for (const r of rows) {
    const status = (r.status || "").toLowerCase();
    if (status === "filled") {
      filled++;
      const c = num(r.conv);
      if (c > 0) { convFilledSum += c; convFilledN++; }
      const tc = num(r.thesis_confidence);
      if (tc > 0) { confFilledSum += tc; confFilledN++; }
    } else if (status === "killed") {
      killed++;
      const c = num(r.conv);
      if (c > 0) { convKilledSum += c; convKilledN++; }
      const tc = num(r.thesis_confidence);
      if (tc > 0) { confKilledSum += tc; confKilledN++; }
    } else if (status === "expired") {
      expired++;
    }
  }
  const total = filled + killed + expired;
  const hitRate = total > 0 ? filled / total : 0;
  return {
    total,
    filled,
    killed,
    expired,
    hitRate,
    avgConvFilled: convFilledN > 0 ? convFilledSum / convFilledN : 0,
    avgConvKilled: convKilledN > 0 ? convKilledSum / convKilledN : 0,
    avgConfFilled: confFilledN > 0 ? confFilledSum / confFilledN : 0,
    avgConfKilled: confKilledN > 0 ? confKilledSum / confKilledN : 0,
  };
}

function HeadlineScorecard({ stats }: { stats: HeadlineStats }) {
  const hitRatePct = (stats.hitRate * 100).toFixed(0);
  const hitRateColor =
    stats.hitRate >= 0.6 ? "#34d399" :
    stats.hitRate >= 0.4 ? `rgb(var(--accent-rgb))` :
    "#f87171";

  // Calibration deltas (positive = brain works)
  const convDelta = stats.avgConvFilled - stats.avgConvKilled;
  const confDelta = stats.avgConfFilled - stats.avgConfKilled;
  const convDeltaColor = convDelta > 0 ? "#34d399" : convDelta < 0 ? "#f87171" : "rgb(148 163 184)";
  const confDeltaColor = confDelta > 0 ? "#34d399" : confDelta < 0 ? "#f87171" : "rgb(148 163 184)";

  return (
    <Card>
      <div className="flex items-center gap-2 mb-3">
        <TrendingUp size={14} style={{ color: `rgb(var(--accent-rgb))` }} />
        <h3 className="text-[length:var(--t-sm)] font-medium text-slate-300">Closed Decisions</h3>
      </div>

      {/* Total + hit rate (row 1 — hero numerics) */}
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div
          style={{
            background: "rgba(255,255,255,0.025)",
            border: "1px solid rgba(255,255,255,0.06)",
            borderRadius: 12,
            padding: "10px 12px",
          }}
        >
          <div className="text-[length:var(--t-2xs)] uppercase tracking-wider text-slate-500 font-medium mb-1">
            Total
          </div>
          <div className="font-mono font-bold tabular-nums text-slate-100"
               style={{ fontSize: "var(--t-hero)", lineHeight: 1 }}>
            {stats.total}
          </div>
          <div className="text-[length:var(--t-2xs)] text-slate-500 mt-1">
            <span className="text-emerald-400 font-semibold">{stats.filled}</span> filled ·{" "}
            <span className="text-red-400 font-semibold">{stats.killed}</span> killed
            {stats.expired > 0 && (
              <> · <span className="text-slate-400 font-semibold">{stats.expired}</span> expired</>
            )}
          </div>
        </div>

        <div
          style={{
            background: "rgba(255,255,255,0.025)",
            border: "1px solid rgba(255,255,255,0.06)",
            borderRadius: 12,
            padding: "10px 12px",
          }}
        >
          <div className="text-[length:var(--t-2xs)] uppercase tracking-wider text-slate-500 font-medium mb-1">
            Hit Rate
          </div>
          <div className="font-mono font-bold tabular-nums"
               style={{ fontSize: "var(--t-hero)", lineHeight: 1, color: hitRateColor }}>
            {stats.total > 0 ? `${hitRatePct}%` : "—"}
          </div>
          <div
            className="mt-2 rounded-full overflow-hidden"
            style={{ height: 4, background: "rgba(255,255,255,0.06)" }}
          >
            <div
              style={{
                height: "100%",
                width: `${stats.hitRate * 100}%`,
                background: hitRateColor,
                transition: "width 0.3s",
              }}
            />
          </div>
        </div>
      </div>

      {/* Calibration row (row 2 — does conviction predict?) */}
      <div className="grid grid-cols-2 gap-3">
        <div
          style={{
            background: "rgba(255,255,255,0.025)",
            border: "1px solid rgba(255,255,255,0.06)",
            borderRadius: 12,
            padding: "10px 12px",
          }}
        >
          <div className="text-[length:var(--t-2xs)] uppercase tracking-wider text-slate-500 font-medium mb-1">
            Conv (gut)
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono font-semibold tabular-nums text-emerald-400"
                  style={{ fontSize: "var(--t-lg)", lineHeight: 1 }}>
              {stats.avgConvFilled.toFixed(1)}
            </span>
            <span className="text-[length:var(--t-2xs)] text-slate-600">filled</span>
            <span className="font-mono font-semibold tabular-nums text-red-400 ml-auto"
                  style={{ fontSize: "var(--t-lg)", lineHeight: 1 }}>
              {stats.avgConvKilled.toFixed(1)}
            </span>
            <span className="text-[length:var(--t-2xs)] text-slate-600">killed</span>
          </div>
          <div className="text-[length:var(--t-2xs)] mt-1.5" style={{ color: convDeltaColor }}>
            {convDelta > 0 ? "+" : ""}{convDelta.toFixed(2)} edge
          </div>
        </div>

        <div
          style={{
            background: "rgba(255,255,255,0.025)",
            border: "1px solid rgba(255,255,255,0.06)",
            borderRadius: 12,
            padding: "10px 12px",
          }}
        >
          <div className="text-[length:var(--t-2xs)] uppercase tracking-wider text-slate-500 font-medium mb-1">
            Confidence (brain)
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono font-semibold tabular-nums text-emerald-400"
                  style={{ fontSize: "var(--t-lg)", lineHeight: 1 }}>
              {(stats.avgConfFilled * 100).toFixed(0)}%
            </span>
            <span className="text-[length:var(--t-2xs)] text-slate-600">filled</span>
            <span className="font-mono font-semibold tabular-nums text-red-400 ml-auto"
                  style={{ fontSize: "var(--t-lg)", lineHeight: 1 }}>
              {(stats.avgConfKilled * 100).toFixed(0)}%
            </span>
            <span className="text-[length:var(--t-2xs)] text-slate-600">killed</span>
          </div>
          <div className="text-[length:var(--t-2xs)] mt-1.5" style={{ color: confDeltaColor }}>
            {confDelta > 0 ? "+" : ""}{(confDelta * 100).toFixed(1)}pp edge
          </div>
        </div>
      </div>
    </Card>
  );
}

// ---------- Bucket breakdown ----------

interface BucketRow {
  bucket: string;
  total: number;
  filled: number;
  killed: number;
  expired: number;
  hitRate: number;
}

function computeBuckets(rows: DecisionRow[]): BucketRow[] {
  const map = new Map<string, BucketRow>();
  for (const r of rows) {
    const key = (r.bucket || "unknown").toLowerCase();
    let b = map.get(key);
    if (!b) {
      b = { bucket: key, total: 0, filled: 0, killed: 0, expired: 0, hitRate: 0 };
      map.set(key, b);
    }
    b.total++;
    const status = (r.status || "").toLowerCase();
    if (status === "filled") b.filled++;
    else if (status === "killed") b.killed++;
    else if (status === "expired") b.expired++;
  }
  for (const b of map.values()) {
    b.hitRate = b.total > 0 ? b.filled / b.total : 0;
  }
  return [...map.values()].sort((a, b) => b.total - a.total);
}

function BucketBreakdown({ rows }: { rows: BucketRow[] }) {
  if (!rows.length) return null;
  return (
    <Card>
      <div className="flex items-center gap-2 mb-3">
        <Target size={14} style={{ color: `rgb(var(--accent-rgb))` }} />
        <h3 className="text-[length:var(--t-sm)] font-medium text-slate-300">By Bucket</h3>
      </div>
      <div className="flex flex-col gap-2.5">
        {rows.map((b) => {
          const fillW = b.total > 0 ? (b.filled / b.total) * 100 : 0;
          const killW = b.total > 0 ? (b.killed / b.total) * 100 : 0;
          const expW  = b.total > 0 ? (b.expired / b.total) * 100 : 0;
          const hrColor =
            b.hitRate >= 0.6 ? "#34d399" :
            b.hitRate >= 0.4 ? `rgb(var(--accent-rgb))` :
            "#f87171";
          return (
            <div key={b.bucket}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[length:var(--t-xs)] font-semibold text-slate-300 uppercase tracking-wide">
                  {b.bucket}
                </span>
                <div className="flex items-center gap-2.5 text-[length:var(--t-2xs)] tabular-nums">
                  <span className="text-slate-500">
                    n=<span className="text-slate-300 font-semibold">{b.total}</span>
                  </span>
                  <span className="font-mono font-bold tabular-nums" style={{ color: hrColor }}>
                    {(b.hitRate * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
              {/* Stacked bar */}
              <div className="flex rounded-full overflow-hidden" style={{ height: 6, background: "rgba(255,255,255,0.04)" }}>
                {fillW > 0 && (
                  <div style={{ width: `${fillW}%`, background: "#34d399" }} title={`${b.filled} filled`} />
                )}
                {killW > 0 && (
                  <div style={{ width: `${killW}%`, background: "#f87171" }} title={`${b.killed} killed`} />
                )}
                {expW > 0 && (
                  <div style={{ width: `${expW}%`, background: "rgb(148 163 184)" }} title={`${b.expired} expired`} />
                )}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// ---------- Decision-by-decision list ----------

const STATUS_VIEW: Record<string, { icon: typeof CheckCircle; bg: string; text: string; border: string; label: string }> = {
  filled:  { icon: CheckCircle,  bg: "bg-emerald-500/10", text: "text-emerald-400", border: "border-emerald-500/20", label: "Filled" },
  killed:  { icon: XCircle,      bg: "bg-red-500/10",     text: "text-red-400",     border: "border-red-500/20",     label: "Killed" },
  expired: { icon: AlertTriangle, bg: "bg-slate-500/10",  text: "text-slate-400",   border: "border-slate-500/20",   label: "Expired" },
};

function ConvictionDots({ level }: { level: number }) {
  return (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          className={`w-1.5 h-1.5 rounded-full ${i <= level ? "bg-indigo-400" : "bg-slate-700"}`}
        />
      ))}
    </div>
  );
}

function DecisionListItem({ row, onTap }: { row: DecisionRow; onTap: () => void }) {
  const status = STATUS_VIEW[(row.status || "").toLowerCase()] ?? STATUS_VIEW.expired;
  const Icon = status.icon;
  const conv = Math.round(num(row.conv));
  const conf = Math.max(0, Math.min(1, num(row.thesis_confidence)));
  const confPct = conf * 100;
  const confColor = confPct >= 70 ? "#34d399" : confPct >= 50 ? "#818cf8" : "#fbbf24";

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
      className={`w-full text-left glass rounded-2xl p-3.5 border ${status.border} active:bg-white/3 transition-colors cursor-pointer`}
    >
      {/* Header: ticker + status + date */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[length:var(--t-sm)] font-bold tabular-nums text-slate-100">
            {row.ticker}
          </span>
          {row.strategy && (
            <span className="text-[length:var(--t-2xs)] font-semibold uppercase tracking-wider text-slate-500">
              {row.strategy}
            </span>
          )}
          {row.bucket && (
            <span className="text-[length:var(--t-2xs)] font-medium text-slate-500 uppercase bg-white/5 px-1.5 py-0.5 rounded">
              {row.bucket}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className={`flex items-center gap-1 px-2 py-0.5 rounded-full ${status.bg}`}>
            <Icon size={10} className={status.text} />
            <span className={`text-[length:var(--t-2xs)] font-semibold ${status.text}`}>{status.label}</span>
          </div>
          <ChevronRight size={12} className="text-slate-600" />
        </div>
      </div>

      {/* Thesis 1-liner */}
      {row.thesis_1liner && (
        <p className="text-[length:var(--t-xs)] text-slate-400 leading-snug mb-2 line-clamp-2">
          {row.thesis_1liner}
        </p>
      )}

      {/* Footer: conv + confidence + date */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          {conv > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-[length:var(--t-2xs)] text-slate-500">Conv</span>
              <ConvictionDots level={conv} />
            </div>
          )}
          {conf > 0 && (
            <div className="flex items-center gap-1.5">
              <span className="text-[length:var(--t-2xs)] text-slate-500">Conf</span>
              <div
                style={{
                  width: 32,
                  height: 3,
                  borderRadius: 2,
                  backgroundColor: "rgba(255,255,255,0.05)",
                  overflow: "hidden",
                }}
              >
                <div style={{ height: "100%", width: `${confPct}%`, backgroundColor: confColor }} />
              </div>
              <span className="text-[length:var(--t-2xs)] font-mono tabular-nums text-slate-400">
                {confPct.toFixed(0)}%
              </span>
            </div>
          )}
        </div>
        <span className="text-[length:var(--t-2xs)] text-slate-600 tabular-nums">
          {shortDate(row.date)}
        </span>
      </div>
    </div>
  );
}

// ---------- Thesis modal ----------

function ThesisModal({ row, onClose }: { row: DecisionRow; onClose: () => void }) {
  const status = STATUS_VIEW[(row.status || "").toLowerCase()] ?? STATUS_VIEW.expired;
  const Icon = status.icon;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center"
      style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(8px)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg max-h-[85vh] glass rounded-t-3xl sm:rounded-3xl overflow-hidden flex flex-col"
        style={{ marginBottom: "env(safe-area-inset-bottom, 0px)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/5">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="text-[length:var(--t-lg)] font-bold tabular-nums text-slate-100">
              {row.ticker}
            </span>
            {row.strategy && (
              <span className="text-[length:var(--t-xs)] font-semibold uppercase tracking-wider text-slate-500">
                {row.strategy}
              </span>
            )}
            <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full ${status.bg}`}>
              <Icon size={11} className={status.text} />
              <span className={`text-[length:var(--t-2xs)] font-semibold ${status.text}`}>{status.label}</span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-white/5 active:bg-white/10 transition-colors"
            aria-label="Close"
          >
            <X size={16} className="text-slate-400" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {/* Meta */}
          <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-[length:var(--t-2xs)] text-slate-500 mb-3">
            <span>{shortDate(row.date)}</span>
            {row.account && <span className="uppercase">· {row.account}</span>}
            {row.bucket && <span>· {row.bucket}</span>}
            {num(row.conv) > 0 && (
              <span>· conv <span className="text-slate-300 font-semibold">{Math.round(num(row.conv))}</span>/5</span>
            )}
            {num(row.thesis_confidence) > 0 && (
              <span>· confidence <span className="text-slate-300 font-semibold tabular-nums">{(num(row.thesis_confidence) * 100).toFixed(0)}%</span></span>
            )}
          </div>

          {/* 1-liner */}
          {row.thesis_1liner && (
            <p className="text-[length:var(--t-sm)] text-slate-200 leading-relaxed mb-4 font-medium">
              {row.thesis_1liner}
            </p>
          )}

          {/* Full thesis */}
          {row.thesis && (
            <div>
              <div className="text-[length:var(--t-2xs)] uppercase tracking-wider text-slate-500 font-semibold mb-1.5">
                Original thesis
              </div>
              <p className="text-[length:var(--t-xs)] text-slate-300 leading-relaxed whitespace-pre-wrap">
                {row.thesis}
              </p>
            </div>
          )}

          {/* Entry/target if present */}
          {(row.entry || row.target) && (
            <div className="flex items-center gap-3 mt-4 pt-4 border-t border-white/5 text-[length:var(--t-xs)] tabular-nums">
              {row.entry && (
                <span className="text-slate-500">
                  Entry <span className="text-slate-300 font-semibold">${num(row.entry).toFixed(2)}</span>
                </span>
              )}
              {row.target && (
                <span className="text-slate-500">
                  Target <span className="text-emerald-400/80 font-semibold">${num(row.target).toFixed(2)}</span>
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------- Empty state ----------

function EmptyClosed({ window }: { window: Window }) {
  return (
    <Card>
      <div className="flex flex-col items-center gap-3 py-6">
        <div className="w-12 h-12 rounded-2xl bg-slate-700/50 flex items-center justify-center">
          <Target size={20} className="text-slate-500" />
        </div>
        <div className="text-center">
          <p className="text-[length:var(--t-sm)] font-medium text-slate-400">
            No closed decisions {window === "all" ? "yet" : `in last ${window}`}
          </p>
          <p className="text-[length:var(--t-xs)] text-slate-500 mt-0.5">
            Closed = filled, killed, or expired.{" "}
            {window !== "all" && "Try a wider window."}
          </p>
        </div>
      </div>
    </Card>
  );
}

// ---------- Main card ----------

const LAST_KEY = "casaa_review_window";

function loadLastWindow(): Window {
  try {
    const v = localStorage.getItem(LAST_KEY);
    if (v === "7d" || v === "30d" || v === "90d" || v === "all") return v;
  } catch {
    // ignore
  }
  return "30d";
}

export function ClosedDecisionsCard({ decisionsAll }: { decisionsAll: DecisionRow[] }) {
  const [window, setWindow] = useState<Window>(loadLastWindow);
  const [selected, setSelected] = useState<DecisionRow | null>(null);

  const handleWindow = (w: Window) => {
    setWindow(w);
    try { localStorage.setItem(LAST_KEY, w); } catch {
      // ignore
    }
  };

  // Filter: closed status only, then by window
  const closed = useMemo(() => {
    const all = decisionsAll.filter((r) => CLOSED_STATUSES.has((r.status || "").toLowerCase()));
    return filterByWindow(all, window);
  }, [decisionsAll, window]);

  const stats = useMemo(() => computeHeadline(closed), [closed]);
  const buckets = useMemo(() => computeBuckets(closed), [closed]);

  // Most recent first (limit 50 for perf, not strictly needed at current scale)
  const sorted = useMemo(() => {
    return [...closed]
      .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0))
      .slice(0, 50);
  }, [closed]);

  return (
    <>
      <div className="flex flex-col gap-4 px-4 pb-4 pt-3">
        {/* Window pills row */}
        <div className="flex items-center justify-between">
          <h3 className="text-[length:var(--t-xs)] font-medium text-slate-500 uppercase tracking-wider">
            Window
          </h3>
          <WindowPills value={window} onChange={handleWindow} />
        </div>

        {closed.length === 0 ? (
          <EmptyClosed window={window} />
        ) : (
          <>
            <div className="fade-up fade-up-1">
              <HeadlineScorecard stats={stats} />
            </div>

            {buckets.length > 0 && (
              <div className="fade-up fade-up-2">
                <BucketBreakdown rows={buckets} />
              </div>
            )}

            <div className="fade-up fade-up-3 flex flex-col gap-2">
              <div className="flex items-center justify-between px-1">
                <span className="text-[length:var(--t-2xs)] font-semibold uppercase tracking-wider text-slate-500">
                  Decisions
                </span>
                <span className="text-[length:var(--t-2xs)] text-slate-600 tabular-nums">
                  {sorted.length}
                </span>
              </div>
              {sorted.map((d, i) => (
                <DecisionListItem
                  key={`${d.ticker}-${d.date}-${i}`}
                  row={d}
                  onTap={() => setSelected(d)}
                />
              ))}
            </div>
          </>
        )}
      </div>

      {selected && <ThesisModal row={selected} onClose={() => setSelected(null)} />}
    </>
  );
}
