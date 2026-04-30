import type { WsrSummaryRow } from "../data";
import { parseWsrLite, isWsrLiteFresh, nextPulseLabel } from "../lib/wsrLiteParse";
import { Card } from "./Card";
import { Activity, ChevronRight, Clock } from "lucide-react";

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2">
      <span className="text-[length:var(--t-2xs)] text-slate-500 font-semibold shrink-0">CONF</span>
      <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.08)" }}>
        <div
          className="h-full"
          style={{
            width: `${pct}%`,
            background: "linear-gradient(90deg, rgb(var(--accent-rgb)), var(--accent-bright))",
          }}
        />
      </div>
      <span className="text-[length:var(--t-xs)] font-bold tabular-nums text-slate-100 shrink-0">{pct}%</span>
    </div>
  );
}

export function WsrLiteCard({
  wsrLite,
  loading,
  onOpen,
}: {
  wsrLite: WsrSummaryRow | null;
  loading?: boolean;
  onOpen?: () => void;
}) {
  if (loading) {
    return (
      <Card>
        <div className="flex items-center justify-between mb-3">
          <div className="shimmer h-4 w-28" />
          <div className="shimmer h-5 w-24" />
        </div>
        <div className="shimmer h-2 w-full mb-3" />
        <div className="space-y-2">
          <div className="shimmer h-4 w-full" />
          <div className="shimmer h-4 w-4/6" />
        </div>
      </Card>
    );
  }

  // No data at all
  if (!wsrLite) {
    return (
      <Card>
        <div className="flex items-center gap-3 py-3">
          <div
            className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}
          >
            <Activity size={16} style={{ color: "rgb(100 116 139)" }} />
          </div>
          <div>
            <p className="text-[length:var(--t-sm)] font-medium text-slate-400">No mid-week check-in yet</p>
            <p className="text-[length:var(--t-xs)] text-slate-600 mt-0.5 flex items-center gap-1">
              <Clock size={10} />
              Next pulse: {nextPulseLabel()}
            </p>
          </div>
        </div>
      </Card>
    );
  }

  const parsed = parseWsrLite(wsrLite.raw_md ?? "");
  const { bottomLine, triggers, regimeUnchanged } = parsed;
  const dateStr = wsrLite.date.slice(0, 10);
  const fresh = isWsrLiteFresh(wsrLite.date);

  const hitCount    = triggers.filter((t) => t.status === "HIT").length;
  const closeCount  = triggers.filter((t) => t.status === "CLOSE").length;
  const dormCount   = triggers.filter((t) => t.status === "DORMANT").length;

  return (
    <Card variant="bright">
      <button
        type="button"
        onClick={onOpen}
        className="block w-full text-left active:opacity-80 transition-opacity"
        aria-label="Open mid-week pulse"
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-[length:var(--t-base)]">⚡</span>
            <h2 className="text-[length:var(--t-sm)] font-semibold text-slate-200">Mid-Week Pulse</h2>
            <time className="text-[length:var(--t-xs)] text-slate-500 tabular-nums ml-1">{dateStr}</time>
            {!fresh && (
              <span className="text-[length:var(--t-2xs)] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded-full" style={{ background: "rgba(255,255,255,0.06)", color: "rgb(100 116 139)" }}>PREV</span>
            )}
          </div>
          {/* Regime badge */}
          <div
            className="inline-flex items-center px-2.5 py-1 rounded-full text-[length:var(--t-xs)] font-semibold border"
            style={
              regimeUnchanged
                ? { background: "rgba(52,211,153,0.1)", color: "#34d399", border: "1px solid rgba(52,211,153,0.25)" }
                : { background: "rgba(251,191,36,0.1)", color: "#fbbf24", border: "1px solid rgba(251,191,36,0.25)" }
            }
          >
            {regimeUnchanged ? "UNCHANGED" : "DRIFT"}
          </div>
        </div>

        {/* Trigger summary strip */}
        {triggers.length > 0 && (
          <div className="flex items-center gap-3 mb-3">
            {hitCount > 0 && (
              <span className="text-[length:var(--t-xs)] font-semibold" style={{ color: "#f87171" }}>
                {hitCount} HIT
              </span>
            )}
            {closeCount > 0 && (
              <span className="text-[length:var(--t-xs)] font-semibold" style={{ color: "#fbbf24" }}>
                {closeCount} CLOSE
              </span>
            )}
            {dormCount > 0 && (
              <span className="text-[length:var(--t-xs)]" style={{ color: "rgb(100 116 139)" }}>
                {dormCount} dormant
              </span>
            )}
          </div>
        )}

        {/* Confidence bar */}
        <div className="mb-3">
          <ConfidenceBar value={bottomLine.confidence} />
        </div>

        {/* Bottom line excerpt */}
        {bottomLine.text && (
          <p className="text-[length:var(--t-sm)] text-slate-100 leading-relaxed line-clamp-3">
            {bottomLine.text}
          </p>
        )}

        {onOpen && (
          <div className="flex items-center justify-center gap-1 pt-3 mt-3 border-t border-white/5 text-[length:var(--t-xs)] text-indigo-400 font-medium">
            <span>Open full pulse</span>
            <ChevronRight size={13} />
          </div>
        )}
      </button>
    </Card>
  );
}
