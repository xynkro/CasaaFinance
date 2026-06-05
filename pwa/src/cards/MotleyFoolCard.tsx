import { useState } from "react";
import type { CuratedPickRow } from "../data";
import { Card } from "./Card";
import { BookOpen, ChevronDown, ChevronUp } from "lucide-react";

// Reference-only surface for Motley Fool Stock Advisor Scorecard names. This is
// an ENGINE INPUT, not a signal — nothing here is auto-traded. The card lists
// each active reference pick: ticker · MF risk type · return-vs-S&P · Moneyball
// Superscore. Renders null when empty (no first-deploy stub).

function fmtPct(v?: string): { text: string; cls: string } {
  const n = Number(v);
  if (!v || isNaN(n)) return { text: "—", cls: "text-slate-600" };
  const cls = n > 0 ? "text-emerald-300" : n < 0 ? "text-rose-300" : "text-slate-500";
  return { text: `${n > 0 ? "+" : ""}${n.toFixed(1)}%`, cls };
}

function ReferenceRow({ row }: { row: CuratedPickRow }) {
  const vsSp = fmtPct(row.return_vs_sp);
  const moneyball = row.moneyball_score?.trim();
  return (
    <div className="flex items-center gap-2 py-2 border-b border-white/5 last:border-0">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[length:var(--t-sm)] font-bold text-white">{row.ticker}</span>
          {row.mf_type && (
            <span className="text-[length:var(--t-2xs)] font-semibold text-fuchsia-300">{row.mf_type}</span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0 text-right">
        <div className="flex flex-col items-end leading-tight">
          <span className={`text-[length:var(--t-xs)] font-semibold tabular-nums ${vsSp.cls}`}>{vsSp.text}</span>
          <span className="text-[length:var(--t-2xs)] text-slate-600">vs S&amp;P</span>
        </div>
        {moneyball && (
          <div className="flex flex-col items-end leading-tight">
            <span className="text-[length:var(--t-xs)] font-semibold text-sky-300 tabular-nums">{moneyball}</span>
            <span className="text-[length:var(--t-2xs)] text-slate-600">Superscore</span>
          </div>
        )}
      </div>
    </div>
  );
}

export function MotleyFoolCard({ reference }: { reference: CuratedPickRow[] }) {
  const [showAll, setShowAll] = useState(false);

  if (!reference.length) return null;

  const display = showAll ? reference : reference.slice(0, 8);
  const hasMore = reference.length > 8;

  return (
    <Card>
      <div className="flex items-center gap-2 mb-2">
        <BookOpen size={14} className="text-fuchsia-400" />
        <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Motley Fool</h2>
        <span className="text-[length:var(--t-2xs)] text-slate-600">Stock Advisor Scorecard</span>
      </div>

      <p className="text-[length:var(--t-2xs)] text-slate-600 mb-2 leading-relaxed">
        Motley Fool Stock Advisor — reference only, not auto-traded.
      </p>

      <div>
        {display.map((r, i) => (
          <ReferenceRow key={`${r.ticker}-${i}`} row={r} />
        ))}
      </div>

      {hasMore && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="flex items-center justify-center gap-1 w-full pt-2 mt-1 border-t border-white/5 text-[length:var(--t-xs)] text-indigo-400 font-medium"
        >
          <span>{showAll ? "Show less" : `Show all ${reference.length}`}</span>
          {showAll ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>
      )}
    </Card>
  );
}
