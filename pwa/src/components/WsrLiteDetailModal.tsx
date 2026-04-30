import { useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { X, ChevronLeft, Target, AlertTriangle, Moon } from "lucide-react";
import type { WsrSummaryRow } from "../data";
import { parseWsrLite } from "../lib/wsrLiteParse";
import type { TriggerRow, TrafficLightRow, DecisionQueueRow, CatalystDay } from "../lib/wsrLiteParse";

// ── Trigger Audit ─────────────────────────────────────────────────────────────

const TRIGGER_STYLES = {
  HIT:     { color: "#f87171", Icon: Target,        bg: "rgba(248,113,113,0.08)", border: "rgba(248,113,113,0.25)" },
  CLOSE:   { color: "#fbbf24", Icon: AlertTriangle,  bg: "rgba(251,191,36,0.08)",  border: "rgba(251,191,36,0.25)"  },
  DORMANT: { color: "rgb(71 85 105)", Icon: Moon,   bg: "transparent",            border: "transparent"            },
};

function TriggerList({ rows }: { rows: TriggerRow[] }) {
  if (!rows.length) return <p className="text-[length:var(--t-sm)] text-slate-500">No triggers parsed.</p>;
  return (
    <div className="space-y-1">
      {rows.map((t) => {
        const style = TRIGGER_STYLES[t.status];
        const { Icon } = style;
        return (
          <div
            key={t.ticker}
            className="flex items-start gap-3 rounded-xl px-3 py-2.5"
            style={{ background: style.bg, border: `1px solid ${style.border}` }}
          >
            <div className="w-1 self-stretch rounded-full shrink-0 mt-0.5" style={{ background: style.color, minWidth: 3 }} />
            <Icon size={13} className="shrink-0 mt-0.5" style={{ color: style.color }} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[length:var(--t-sm)] font-bold text-white">{t.ticker}</span>
                <span className="text-[length:var(--t-xs)] tabular-nums text-slate-400">{t.price}</span>
                <span className="text-[length:var(--t-2xs)] font-bold px-1.5 py-0.5 rounded" style={{ background: `${style.color}20`, color: style.color }}>
                  {t.status}
                </span>
              </div>
              {t.action && <p className="text-[length:var(--t-xs)] text-slate-400 mt-0.5 leading-relaxed">{t.action}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Options Traffic Lights ────────────────────────────────────────────────────

const FLAG_STYLE: Record<string, { border: string; bg: string }> = {
  "🔴": { border: "rgba(248,113,113,0.3)",  bg: "rgba(248,113,113,0.07)"  },
  "🟡": { border: "rgba(251,191,36,0.3)",   bg: "rgba(251,191,36,0.07)"   },
  "🟢": { border: "rgba(52,211,153,0.2)",   bg: "rgba(52,211,153,0.05)"   },
};

function TrafficCards({ rows }: { rows: TrafficLightRow[] }) {
  if (!rows.length) return <p className="text-[length:var(--t-sm)] text-slate-500">No options data parsed.</p>;
  return (
    <div className="space-y-2">
      {rows.map((r) => {
        const fs = FLAG_STYLE[r.flag] ?? FLAG_STYLE["🟢"];
        return (
          <div key={r.ticker} className="rounded-2xl px-4 py-3" style={{ background: fs.bg, border: `1px solid ${fs.border}` }}>
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2">
                <span className="text-[length:var(--t-base)] leading-none">{r.flag}</span>
                <span className="text-[length:var(--t-sm)] font-bold text-white">{r.ticker}</span>
                <span className="text-[length:var(--t-xs)] text-slate-500">{r.strategy} ${r.strike} · {r.dte} DTE</span>
              </div>
            </div>
            <div className="text-[length:var(--t-xl)] font-bold tabular-nums text-white mb-0.5">{r.proximity}</div>
            <div className="text-[length:var(--t-xs)] text-slate-500 mb-1">Underlying ~{r.underlying}</div>
            {r.note && <p className="text-[length:var(--t-xs)] text-slate-300 italic leading-relaxed">{r.note}</p>}
          </div>
        );
      })}
    </div>
  );
}

// ── Regime Drift ──────────────────────────────────────────────────────────────

function RegimePanel({ text, unchanged }: { text: string; unchanged: boolean }) {
  // Highlight key metric tokens inline
  const highlighted = text.split(/(\bVIX\s+[\d.]+|\bSPX\s+[\d,]+|\b10Y\s+[\d.]+%|\bSMA\d+|\bDXY\s+[\d.]+)/g).map(
    (chunk, i) =>
      i % 2 === 1 ? (
        <span key={i} className="font-semibold" style={{ color: "rgb(165 180 252)" }}>{chunk}</span>
      ) : (
        chunk
      )
  );
  return (
    <div
      className="rounded-2xl p-4"
      style={{
        background: unchanged ? "rgba(52,211,153,0.04)" : "rgba(251,191,36,0.06)",
        border: `1px solid ${unchanged ? "rgba(52,211,153,0.15)" : "rgba(251,191,36,0.2)"}`,
      }}
    >
      <div className="flex items-center gap-2 mb-2.5">
        <span
          className="text-[length:var(--t-xs)] font-bold px-2.5 py-1 rounded-lg"
          style={
            unchanged
              ? { background: "rgba(52,211,153,0.15)", color: "#34d399" }
              : { background: "rgba(251,191,36,0.15)", color: "#fbbf24" }
          }
        >
          {unchanged ? "REGIME UNCHANGED" : "REGIME DRIFT"}
        </span>
      </div>
      <p className="text-[length:var(--t-sm)] text-slate-300 leading-relaxed">{highlighted}</p>
    </div>
  );
}

// ── Decision Queue ────────────────────────────────────────────────────────────

const Q_STATUS_STYLE: Record<string, { color: string; bg: string }> = {
  ACTIONABLE: { color: "#34d399", bg: "rgba(52,211,153,0.12)" },
  CLOSE:      { color: "#fbbf24", bg: "rgba(251,191,36,0.12)" },
  WAIT:       { color: "rgb(100 116 139)", bg: "rgba(255,255,255,0.05)" },
};

function DecisionQueueList({ rows }: { rows: DecisionQueueRow[] }) {
  if (!rows.length) return <p className="text-[length:var(--t-sm)] text-slate-500">No queue data parsed.</p>;
  return (
    <div className="space-y-1.5">
      {rows.map((r) => {
        const s = Q_STATUS_STYLE[r.status] ?? Q_STATUS_STYLE.WAIT;
        const distPos = r.distancePct.startsWith("+") || r.distancePct.startsWith("-");
        const distColor = r.distancePct.startsWith("+") ? "#34d399" : r.distancePct.startsWith("-") ? "#f87171" : "rgb(148 163 184)";
        return (
          <div
            key={`${r.rank}-${r.ticker}`}
            className="flex items-center gap-3 rounded-xl px-3 py-2.5"
            style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}
          >
            <span
              className="text-[length:var(--t-2xs)] font-bold w-5 h-5 rounded-full flex items-center justify-center shrink-0"
              style={{ background: "rgba(255,255,255,0.08)", color: "rgb(148 163 184)" }}
            >
              {r.rank}
            </span>
            <span className="text-[length:var(--t-sm)] font-bold text-white w-14 shrink-0">{r.ticker}</span>
            <div className="flex-1 min-w-0">
              <span className="text-[length:var(--t-xs)] text-slate-500 tabular-nums">
                ${r.entry} → {r.last}
              </span>
              {r.statusNote && (
                <span className="text-[length:var(--t-2xs)] text-slate-600 ml-1.5">{r.statusNote}</span>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {distPos && (
                <span className="text-[length:var(--t-xs)] font-semibold tabular-nums" style={{ color: distColor }}>
                  {r.distancePct}
                </span>
              )}
              <span className="text-[length:var(--t-2xs)] font-bold px-2 py-0.5 rounded-lg" style={{ background: s.bg, color: s.color }}>
                {r.status}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Catalyst Calendar ─────────────────────────────────────────────────────────

function CatalystDays({ days }: { days: CatalystDay[] }) {
  if (!days.length) return <p className="text-[length:var(--t-sm)] text-slate-500">No catalysts parsed.</p>;
  return (
    <div className="space-y-2">
      {days.map((day) => (
        <div
          key={day.label}
          className="rounded-xl p-3"
          style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)" }}
        >
          <div className="text-[length:var(--t-xs)] font-bold text-slate-400 mb-1.5">{day.label}</div>
          {day.bullets.length === 0 || (day.bullets.length === 1 && day.bullets[0].toLowerCase().includes("no major")) ? (
            <p className="text-[length:var(--t-xs)] text-slate-600">No major catalysts.</p>
          ) : (
            <ul className="space-y-1">
              {day.bullets.map((b, i) => (
                <li key={i} className="text-[length:var(--t-xs)] text-slate-300 leading-relaxed flex items-start gap-1.5">
                  <span style={{ color: "rgb(99 102 241)", marginTop: 3 }}>·</span>
                  <span>{b}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Bottom Line ───────────────────────────────────────────────────────────────

function BottomLineBlock({ text, confidence, tag }: { text: string; confidence: number; tag: string }) {
  const pct = Math.round(confidence * 100);
  return (
    <div
      className="rounded-2xl p-4"
      style={{
        background: "rgba(var(--accent-rgb), 0.06)",
        border: "1px solid rgba(var(--accent-rgb), 0.2)",
      }}
    >
      <p className="text-[length:var(--t-sm)] text-slate-100 leading-relaxed mb-3">{text}</p>
      <div className="flex items-center gap-3">
        <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.08)" }}>
          <div
            className="h-full"
            style={{
              width: `${pct}%`,
              background: "linear-gradient(90deg, rgb(var(--accent-rgb)), var(--accent-bright))",
            }}
          />
        </div>
        <span className="text-[length:var(--t-xs)] font-bold tabular-nums text-white shrink-0">{pct}%</span>
        <span
          className="text-[length:var(--t-2xs)] px-2 py-0.5 rounded"
          style={{ background: "rgba(255,255,255,0.07)", color: "rgb(148 163 184)" }}
        >
          {tag}
        </span>
      </div>
    </div>
  );
}

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="px-4 py-4 border-b border-white/5 space-y-3">
      <div className="label-caps">{label}</div>
      {children}
    </div>
  );
}

// ── Main modal ────────────────────────────────────────────────────────────────

export function WsrLiteDetailModal({
  wsrLite,
  onClose,
}: {
  wsrLite: WsrSummaryRow;
  onClose: () => void;
}) {
  const touchRef = useRef<{ startX: number; startY: number; moving: boolean }>({ startX: 0, startY: 0, moving: false });
  const [dragX, setDragX] = useState(0);

  const onTouchStart = (e: React.TouchEvent) => {
    touchRef.current = { startX: e.touches[0].clientX, startY: e.touches[0].clientY, moving: false };
  };
  const onTouchMove = (e: React.TouchEvent) => {
    const dx = e.touches[0].clientX - touchRef.current.startX;
    const dy = e.touches[0].clientY - touchRef.current.startY;
    if (!touchRef.current.moving) {
      if (Math.abs(dy) > Math.abs(dx) || Math.abs(dx) < 10 || dx <= 0) return;
      touchRef.current.moving = true;
    }
    if (dx > 0) setDragX(dx);
  };
  const onTouchEnd = () => {
    if (touchRef.current.moving && dragX > 80) onClose();
    else setDragX(0);
    touchRef.current.moving = false;
  };

  const parsed = parseWsrLite(wsrLite.raw_md ?? "");
  const dateStr = wsrLite.date.slice(0, 10);

  // Derive a day label from raw_md heading
  const dayMatch = (wsrLite.raw_md ?? "").match(/WSR Lite\s*[—–-]\s*[\d-]+\s+\((\w+)\)/i);
  const dayLabel = dayMatch ? dayMatch[1] : "";

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex flex-col"
      style={{
        background: "#07090f",
        transform: `translateX(${dragX}px)`,
        transition: touchRef.current.moving ? "none" : "transform 0.25s cubic-bezier(0.4,0,0.2,1)",
        opacity: 1 - Math.min(dragX / 400, 0.25),
      }}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 shrink-0"
        style={{
          paddingTop: `calc(var(--safe-top) + 12px)`,
          paddingBottom: 12,
          borderBottom: "1px solid rgba(255,255,255,0.06)",
          background: "rgba(7,9,15,0.9)",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
        }}
      >
        <button
          onClick={onClose}
          className="flex items-center gap-1 py-1 pr-2 active:opacity-60"
          style={{ color: "rgb(var(--accent-rgb))" }}
        >
          <ChevronLeft size={20} />
          <span className="text-[length:var(--t-sm)] font-medium">Back</span>
        </button>
        <div className="text-center">
          <h2 className="text-[length:var(--t-sm)] font-bold text-white leading-tight">⚡ Mid-Week Pulse</h2>
          <p className="text-[length:var(--t-xs)] text-slate-500">{dateStr}{dayLabel ? ` · ${dayLabel}` : ""}</p>
        </div>
        <button onClick={onClose} className="p-2 rounded-xl active:opacity-60" style={{ color: "rgb(100 116 139)" }}>
          <X size={18} />
        </button>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
        <Section label="Trigger Audit">
          <TriggerList rows={parsed.triggers} />
        </Section>

        <Section label="Options Book Traffic Lights">
          <TrafficCards rows={parsed.options} />
        </Section>

        <Section label="Regime Drift">
          <RegimePanel text={parsed.regimeDrift} unchanged={parsed.regimeUnchanged} />
        </Section>

        <Section label="Decision Queue">
          <DecisionQueueList rows={parsed.decisionQueue} />
        </Section>

        <Section label="Catalyst Calendar — Next 3 Days">
          <CatalystDays days={parsed.catalysts} />
        </Section>

        <div className="px-4 py-4 pb-10">
          <div className="label-caps mb-3">Bottom Line</div>
          <BottomLineBlock
            text={parsed.bottomLine.text}
            confidence={parsed.bottomLine.confidence}
            tag={parsed.bottomLine.tag}
          />
        </div>
      </div>
    </div>,
    document.body
  );
}
