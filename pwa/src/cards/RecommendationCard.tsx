import type { OptionRecommendationRow } from "../data";
import { Card } from "./Card";
import { Lightbulb, ChevronRight, TrendingUp } from "lucide-react";

/** Stable identity for a recommendation — used as React key + selected-state token. */
export function recKey(r: OptionRecommendationRow): string {
  return `${r.date}|${r.source}|${r.strategy}|${r.ticker}|${r.strike}|${r.right}|${r.account}`;
}

const STRATEGY_LABEL: Record<string, string> = {
  CSP: "Cash-Secured Put",
  CC: "Covered Call",
  LONG_CALL: "Long Call",
  LONG_PUT: "Long Put",
  PMCC: "Poor Man's Covered Call",
};

const STATUS_STYLE: Record<string, { bg: string; fg: string; border: string }> = {
  proposed: { bg: "rgba(99,102,241,0.15)",  fg: "#818cf8", border: "rgba(99,102,241,0.20)"  },
  executed: { bg: "rgba(16,185,129,0.15)",  fg: "#34d399", border: "rgba(16,185,129,0.20)"  },
  skipped:  { bg: "rgba(100,116,139,0.15)", fg: "#94a3b8", border: "rgba(100,116,139,0.20)" },
  expired:  { bg: "rgba(245,158,11,0.15)",  fg: "#fbbf24", border: "rgba(245,158,11,0.20)"  },
};

function fmt(v: string | number, prefix = "$"): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${prefix}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(v: string | number): string {
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${n.toFixed(1)}%`;
}

/**
 * Strategy-Notes row (rebuild v3, 2026-04-30).
 *
 * Why this looks different from other cards:
 *
 * The previous design wrapped each row in `.glass`. That class has a global
 * rule `.glass:active { transform: scale(0.983); }` which shrinks the card
 * toward its centre on touch. iOS dispatches the click to whatever element
 * is under the finger AT TOUCHEND — by then the card has shrunk by ~2px,
 * the upper portion of card N has receded, and the finger lands on card N-1.
 *
 * That explains the diagnostic "press above middle of card N → opens N-1,
 * press below middle → opens N, first card just flashes". Removing
 * `active:scale-[0.98]` Tailwind classes wasn't enough because the CSS
 * `.glass:active` rule was still firing on every tap.
 *
 * Fix: don't use `.glass` on the row buttons. Plain inline-styled buttons,
 * no transform, no event delegation, real <button>, direct onClick.
 */
function RecRow({
  rec,
  onTap,
  marginTop,
}: {
  rec: OptionRecommendationRow;
  onTap: () => void;
  marginTop: number;
}) {
  const strategy = STRATEGY_LABEL[rec.strategy] ?? rec.strategy;
  const status = rec.status?.toLowerCase() || "proposed";
  const sStyle = STATUS_STYLE[status] ?? STATUS_STYLE.proposed;
  const accountLabel = rec.account === "caspar" ? "Caspar" : "Sarah";
  const accountColor = rec.account === "caspar" ? "#60a5fa" : "#f472b6";
  const strike = Number(rec.strike);
  const yld = Number(rec.annual_yield_pct);

  let expiryDisplay = rec.expiry;
  if (rec.expiry.length === 8 && /^\d+$/.test(rec.expiry)) {
    expiryDisplay = `${rec.expiry.slice(4, 6)}/${rec.expiry.slice(6, 8)}`;
  }

  const conf = Number(rec.thesis_confidence) || 0;
  const confPct = Math.max(0, Math.min(1, conf)) * 100;
  const confColor = confPct >= 70 ? "#34d399" : confPct >= 50 ? "#818cf8" : "#fbbf24";

  return (
    <button
      type="button"
      onClick={onTap}
      style={{
        // Mobile-touch hygiene
        touchAction: "manipulation",
        WebkitTapHighlightColor: "transparent",
        // Reset native button defaults
        WebkitAppearance: "none",
        appearance: "none",
        font: "inherit",
        color: "inherit",
        cursor: "pointer",
        // Layout
        display: "block",
        width: "100%",
        textAlign: "left",
        padding: 14,
        margin: 0,
        marginTop,
        // Surface — explicit, NOT .glass (no active-scale anywhere)
        backgroundColor: "rgba(255,255,255,0.028)",
        border: "1px solid rgba(255,255,255,0.085)",
        borderRadius: 12,
        // No transform/transition — keeps hit area static during touch
      }}
    >
      {/* Header: ticker + strike + status */}
      <div className="flex items-center justify-between gap-3" style={{ marginBottom: 8 }}>
        <div className="flex items-center gap-2 min-w-0">
          <TrendingUp size={12} style={{ color: "#34d399", flexShrink: 0 }} />
          <span className="text-sm font-bold text-white">{rec.ticker}</span>
          <span className="text-[10px] font-semibold text-slate-500 shrink-0">
            ${strike.toFixed(strike < 10 ? 1 : 0)}{rec.right}
          </span>
          <span className="text-[9px] text-slate-600">exp {expiryDisplay}</span>
        </div>
        <div
          className="shrink-0 text-[10px] font-bold"
          style={{
            backgroundColor: sStyle.bg,
            color: sStyle.fg,
            border: `1px solid ${sStyle.border}`,
            padding: "2px 8px",
            borderRadius: 4,
          }}
        >
          {status.toUpperCase()}
        </div>
      </div>

      {/* Strategy + account */}
      <div className="flex items-center justify-between" style={{ marginBottom: 8 }}>
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-medium" style={{ color: "#818cf8" }}>{strategy}</span>
          <span
            className="text-[10px] font-semibold uppercase tracking-wider"
            style={{ color: accountColor }}
          >
            {accountLabel}
          </span>
        </div>
        <ChevronRight size={12} style={{ color: "#475569" }} />
      </div>

      {/* Key metrics */}
      <div
        className="flex items-center flex-wrap gap-x-4 gap-y-1 text-[10px] text-slate-500"
        style={{ marginBottom: 8 }}
      >
        <span>Premium: <span className="text-slate-300 tabular-nums">{fmt(rec.premium_per_share)}</span></span>
        <span>Yield: <span style={{ color: "#34d399" }} className="tabular-nums font-semibold">{fmtPct(yld)}</span></span>
        <span>Cash: <span className="text-slate-300 tabular-nums">{fmt(rec.cash_required)}</span></span>
        <span>Δ: <span className="text-slate-300 tabular-nums">{Number(rec.delta).toFixed(2)}</span></span>
      </div>

      {/* Footer: BE + IVR + confidence */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4 text-[10px] text-slate-500">
          <span>BE: <span className="text-slate-300 tabular-nums">{fmt(rec.breakeven)}</span></span>
          <span>IVR: <span className="text-slate-300 tabular-nums">{Number(rec.iv_rank).toFixed(0)}</span></span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-slate-500">Conf</span>
          <div className="flex items-center gap-1.5 shrink-0">
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
              {(conf * 100).toFixed(0)}%
            </span>
          </div>
        </div>
      </div>
    </button>
  );
}

export function RecommendationCard({
  recommendations,
  onSelectKey,
}: {
  recommendations: OptionRecommendationRow[];
  /** Called with a stable key when a rec is tapped. Parent looks up the rec. */
  onSelectKey?: (key: string) => void;
}) {
  if (!recommendations.length) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-slate-500">
          <Lightbulb size={16} />
          <span className="text-sm">No strategy recommendations yet</span>
        </div>
        <p className="text-[10px] text-slate-600 mt-1.5 pl-6">
          Drop an options scan into Weekly Strategy Review to auto-populate
        </p>
      </Card>
    );
  }

  // Sort: brain-derived first, then proposed/new, then by date desc, then conf+yield.
  const sortPriority: Record<string, number> = {
    proposed: 0, new: 0, executed: 1, expired: 2, skipped: 3,
  };
  const isBrain = (r: OptionRecommendationRow) =>
    r.source === "wsr_full" || r.source === "wsr_lite";
  const sorted = [...recommendations].sort((a, b) => {
    if (isBrain(a) !== isBrain(b)) return isBrain(a) ? -1 : 1;
    const sa = sortPriority[(a.status ?? "").toLowerCase()] ?? 4;
    const sb = sortPriority[(b.status ?? "").toLowerCase()] ?? 4;
    if (sa !== sb) return sa - sb;
    const da = (a.date ?? "").slice(0, 10);
    const db = (b.date ?? "").slice(0, 10);
    if (da !== db) return da > db ? -1 : 1;
    const confDiff = Number(b.thesis_confidence) - Number(a.thesis_confidence);
    if (confDiff !== 0) return confDiff;
    return Number(b.annual_yield_pct) - Number(a.annual_yield_pct);
  });

  const liveCount = recommendations.filter(
    (r) => ["proposed", "new"].includes((r.status ?? "").toLowerCase()),
  ).length;

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Lightbulb size={14} className="text-amber-400" />
          <h2 className="text-sm font-medium text-slate-400">Strategy Notes (weekly)</h2>
        </div>
        <div className="flex items-center gap-2">
          {liveCount > 0 && (
            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-500/15 text-slate-400 border border-slate-500/20">
              {liveCount} live
            </span>
          )}
          <span className="text-[10px] text-slate-600">context only</span>
        </div>
      </div>
      <p className="text-[10px] text-slate-600 mb-3 leading-relaxed">
        Manual entries from weekly ad-hoc scans. Prices + deltas are stale — verify against Daily Scan above before execution.
      </p>

      {/* Plain list — each row is a real <button> with its own onClick.
          No event delegation. No .glass (which has :active scale that
          shifts hit areas mid-touch). Visual gap is button margin-top. */}
      {sorted.map((r, i) => (
        <RecRow
          key={recKey(r)}
          rec={r}
          marginTop={i === 0 ? 0 : 8}
          onTap={() => onSelectKey?.(recKey(r))}
        />
      ))}
    </Card>
  );
}
