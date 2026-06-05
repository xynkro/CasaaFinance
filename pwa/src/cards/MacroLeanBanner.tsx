import type { MacroLeanRow } from "../data";
import { Card } from "./Card";
import { Landmark } from "lucide-react";

// hawkish/risk_off = defensive (trims growth) → amber; dovish/risk_on = growth
// tailwind → emerald; neutral → slate.
function leanStyle(lean: string): { label: string; cls: string; effect: string } {
  switch (lean) {
    case "hawkish":
      return { label: "HAWKISH", cls: "text-amber-300 bg-amber-500/15 border-amber-500/30",
               effect: "plan trims growth adds · favours income" };
    case "risk_off":
      return { label: "RISK-OFF", cls: "text-rose-300 bg-rose-500/15 border-rose-500/30",
               effect: "plan trims growth · defensive tilt" };
    case "dovish":
      return { label: "DOVISH", cls: "text-emerald-300 bg-emerald-500/15 border-emerald-500/30",
               effect: "plan leans into growth" };
    case "risk_on":
      return { label: "RISK-ON", cls: "text-emerald-300 bg-emerald-500/15 border-emerald-500/30",
               effect: "plan leans into growth" };
    default:
      return { label: "NEUTRAL", cls: "text-slate-400 bg-slate-500/10 border-slate-500/20",
               effect: "no tilt" };
  }
}

export function MacroLeanBanner({ macroLean }: { macroLean: MacroLeanRow | null }) {
  if (!macroLean || !macroLean.net_lean) return null;
  const s = leanStyle((macroLean.net_lean || "").toLowerCase());
  return (
    <Card>
      <div className="flex items-center gap-2 mb-1.5">
        <Landmark size={14} className="text-amber-400" />
        <span className="text-[length:var(--t-xs)] font-semibold text-slate-300 uppercase tracking-wide">
          Macro Lean
        </span>
        <span className="text-[length:var(--t-2xs)] text-slate-600">today's releases · tilts the plan</span>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-bold border ${s.cls}`}>
          {s.label}
        </span>
        <span className="text-[length:var(--t-2xs)] text-slate-400">{s.effect}</span>
      </div>
      {macroLean.summary && (
        <p className="mt-1.5 text-[length:var(--t-2xs)] text-slate-500 leading-relaxed">
          {macroLean.summary}
        </p>
      )}
    </Card>
  );
}
