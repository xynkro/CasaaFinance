import type { OptionsDefenseRow } from "../data";
import { Card } from "./Card";
import { Shield, AlertOctagon, AlertTriangle, AlertCircle, Info } from "lucide-react";
import { useState } from "react";

const SEVERITY_META: Record<string, {
  icon: typeof AlertOctagon;
  bg: string;
  border: string;
  text: string;
  label: string;
  order: number;
}> = {
  CRITICAL: {
    icon: AlertOctagon,
    bg: "bg-red-500/15",
    border: "border-red-500/30",
    text: "text-red-400",
    label: "CRITICAL",
    order: 0,
  },
  HIGH: {
    icon: AlertTriangle,
    bg: "bg-orange-500/15",
    border: "border-orange-500/30",
    text: "text-orange-400",
    label: "HIGH",
    order: 1,
  },
  MEDIUM: {
    icon: AlertCircle,
    bg: "bg-amber-500/10",
    border: "border-amber-500/20",
    text: "text-amber-400",
    label: "MEDIUM",
    order: 2,
  },
  INFO: {
    icon: Info,
    bg: "bg-slate-500/10",
    border: "border-slate-500/20",
    text: "text-slate-400",
    label: "INFO",
    order: 3,
  },
};

function formatRelativeDate(rawDate: string): string {
  const plain = rawDate.split("T")[0];
  if (!plain) return "";
  try {
    const d = new Date(plain + "T00:00:00");
    const now = new Date();
    const diffDays = Math.round((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24));
    if (diffDays === 0) return "today";
    if (diffDays === 1) return "yesterday";
    return `${diffDays}d ago`;
  } catch {
    return plain;
  }
}

function AlertItem({ alert }: { alert: OptionsDefenseRow }) {
  const meta = SEVERITY_META[alert.severity] ?? SEVERITY_META.INFO;
  const Icon = meta.icon;
  const accountLabel = alert.account === "caspar" ? "Caspar" : "Sarah";
  const accountColor = alert.account === "caspar" ? "text-blue-400" : "text-pink-400";

  return (
    <div className={`rounded-xl p-3 border ${meta.bg} ${meta.border} space-y-2`}>
      {/* Header: severity + account + delta */}
      <div className="flex items-start gap-2">
        <Icon size={14} className={`${meta.text} shrink-0 mt-0.5`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-[length:var(--t-2xs)] font-bold ${meta.text}`}>{meta.label}</span>
            <span className={`text-[length:var(--t-2xs)] font-semibold uppercase ${accountColor}`}>
              {accountLabel}
            </span>
            {alert.delta_info && (
              <span className="px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] bg-white/5 text-slate-400 font-mono">
                {alert.delta_info}
              </span>
            )}
          </div>
          <div className="text-[length:var(--t-sm)] font-semibold text-white mt-0.5">
            {alert.title}
          </div>
          <div className="text-[length:var(--t-xs)] text-slate-400 mt-1 leading-relaxed">
            {alert.description}
          </div>
        </div>
      </div>

      {/* Action */}
      <div className="text-[length:var(--t-xs)] leading-relaxed pl-6">
        <span className="text-slate-500">Action: </span>
        <span className={`font-medium ${meta.text}`}>{alert.action}</span>
      </div>
    </div>
  );
}

export function OptionsDefenseCard({ alerts }: { alerts: OptionsDefenseRow[] }) {
  const [showAll, setShowAll] = useState(false);

  if (!alerts.length) {
    return (
      <Card>
        <div className="flex items-center gap-2">
          <Shield size={14} className="text-emerald-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Daily Defense</h2>
        </div>
        <div className="mt-2 flex items-center gap-2 text-emerald-400 text-[length:var(--t-sm)]">
          <Shield size={16} />
          <span>All positions nominal — no alerts today</span>
        </div>
      </Card>
    );
  }

  // Sort by severity
  const sorted = [...alerts].sort(
    (a, b) => (SEVERITY_META[a.severity]?.order ?? 4) - (SEVERITY_META[b.severity]?.order ?? 4),
  );

  const counts = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, INFO: 0 };
  for (const a of alerts) {
    if (a.severity in counts) counts[a.severity as keyof typeof counts]++;
  }

  const urgent = counts.CRITICAL + counts.HIGH;
  const visible = showAll ? sorted : sorted.slice(0, urgent > 0 ? urgent : 3);
  const hiddenCount = sorted.length - visible.length;

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Shield size={14} className={urgent > 0 ? "text-red-400" : "text-indigo-400"} />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Daily Defense</h2>
        </div>
        <div className="flex items-center gap-1.5">
          {counts.CRITICAL > 0 && (
            <span className="px-2 py-0.5 rounded text-[length:var(--t-2xs)] font-bold bg-red-500/20 text-red-400 border border-red-500/30">
              {counts.CRITICAL} CRIT
            </span>
          )}
          {counts.HIGH > 0 && (
            <span className="px-2 py-0.5 rounded text-[length:var(--t-2xs)] font-bold bg-orange-500/20 text-orange-400 border border-orange-500/30">
              {counts.HIGH} HIGH
            </span>
          )}
          {counts.MEDIUM > 0 && (
            <span className="px-2 py-0.5 rounded text-[length:var(--t-2xs)] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">
              {counts.MEDIUM} MED
            </span>
          )}
        </div>
      </div>

      <p className="text-[length:var(--t-2xs)] text-slate-600 mb-3 leading-relaxed">
        Updated {formatRelativeDate(alerts[0]?.date || "")} · day-over-day changes for each open option.
        Sorted by urgency.
      </p>

      <div className="space-y-2">
        {visible.map((a, i) => (
          <AlertItem key={`${a.ticker}-${a.strike}-${a.severity}-${i}`} alert={a} />
        ))}
      </div>

      {hiddenCount > 0 && (
        <button
          onClick={() => setShowAll(true)}
          className="mt-3 w-full py-2 rounded-lg text-[length:var(--t-2xs)] text-slate-500 hover:text-slate-300 border border-white/5 hover:border-white/10 transition-all"
        >
          Show {hiddenCount} more {hiddenCount === 1 ? "alert" : "alerts"}
        </button>
      )}
    </Card>
  );
}
