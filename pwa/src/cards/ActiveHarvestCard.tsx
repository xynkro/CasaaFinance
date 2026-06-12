import type { OptionRow, HarvestScanRow } from "../data";
import { Card } from "./Card";
import { Sprout, TrendingUp, TrendingDown, AlertTriangle } from "lucide-react";
import { OptionMechanics } from "../components/OptionMechanics";

export interface ActiveHarvest {
  position: OptionRow;
  pick?: HarvestScanRow;
  profitPct: number;
  status: "WINNING" | "FLAT" | "TESTED" | "STOP";
}

export function matchHarvestPositions(
  options: OptionRow[],
  picks: HarvestScanRow[],
): ActiveHarvest[] {
  const cspPositions = options.filter(
    (o) => o.right === "P" && Number(o.qty) < 0 && (o.wheel_leg === "CSP" || !o.wheel_leg),
  );

  return cspPositions.map((pos) => {
    const pick = picks.find(
      (p) =>
        p.ticker === pos.ticker &&
        Math.abs(Number(p.strike) - Number(pos.strike)) < 0.5 &&
        p.expiry === pos.expiry,
    );

    const credit = Math.abs(Number(pos.credit)) || 0;
    const last = Math.abs(Number(pos.last)) || 0;
    const profitPct = credit > 0 ? ((credit - last) / credit) * 100 : 0;

    const strike = Number(pos.strike);
    const underlying = Number(pos.underlying_last);
    const distPct = strike > 0 && underlying > 0 ? ((underlying - strike) / strike) * 100 : 999;

    let status: ActiveHarvest["status"] = "FLAT";
    if (profitPct >= 40) status = "WINNING";
    if (distPct < 3) status = "TESTED";
    if (profitPct < -100) status = "STOP";

    return { position: pos, pick, profitPct, status };
  });
}

const STATUS_STYLE: Record<string, { bg: string; text: string; label: string }> = {
  WINNING: { bg: "border-emerald-500/20", text: "text-emerald-400", label: "Winning" },
  FLAT:    { bg: "border-slate-500/10",   text: "text-slate-400",   label: "Open" },
  TESTED:  { bg: "border-amber-500/20",   text: "text-amber-400",   label: "Tested" },
  STOP:    { bg: "border-red-500/20",      text: "text-red-400",     label: "Stop zone" },
};

function ProfitBar({ pct }: { pct: number }) {
  const clamped = Math.max(-100, Math.min(100, pct));
  const width = Math.abs(clamped);
  const color = clamped >= 50 ? "bg-emerald-500" : clamped >= 0 ? "bg-emerald-500/60" : "bg-red-500/60";
  return (
    <div className="w-full h-1.5 rounded-full bg-white/5 overflow-hidden">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${width}%` }} />
    </div>
  );
}

function HarvestPositionRow({ h }: { h: ActiveHarvest }) {
  const { position: pos, pick, profitPct, status } = h;
  const s = STATUS_STYLE[status];
  const credit = Math.abs(Number(pos.credit)) || 0;
  const upl = Number(pos.upl) || 0;
  const dte = Number(pos.dte) || 0;
  const strike = Number(pos.strike) || 0;
  const conv = pick ? Number(pick.conviction) || 0 : 0;

  return (
    <div className={`border rounded-xl p-3 space-y-2 ${s.bg}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {status === "WINNING" && <TrendingUp size={12} className="text-emerald-400" />}
          {status === "TESTED" && <AlertTriangle size={12} className="text-amber-400" />}
          {status === "STOP" && <TrendingDown size={12} className="text-red-400" />}
          <span className="font-bold text-[length:var(--t-sm)]">{pos.ticker}</span>
          <span className="text-[length:var(--t-2xs)] text-slate-500">${strike.toFixed(0)}P</span>
          <span className="text-[length:var(--t-2xs)] text-slate-600">{dte}d</span>
        </div>
        <span className={`text-[length:var(--t-2xs)] font-semibold px-1.5 py-0.5 rounded ${s.text} bg-white/3`}>
          {s.label}
        </span>
      </div>

      <ProfitBar pct={profitPct} />

      {/* Mechanics strip — captured % (50% rule) / DTE pill (21d act, 7d urgent)
          / distance-to-strike / max loss. Computed from credit/last/qty/strike/
          expiry/right; chips drop out individually on missing inputs. */}
      <OptionMechanics
        credit={Number(pos.credit) || undefined}
        last={Number(pos.last) || undefined}
        dte={dte}
        strike={strike}
        underlying={Number(pos.underlying_last) || undefined}
        right={pos.right}
        qty={Number(pos.qty) || undefined}
        leg="CSP"
      />

      <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-[length:var(--t-2xs)] text-slate-500">
        <span>Credit <span className="text-slate-300 tabular-nums">${credit.toFixed(2)}</span></span>
        <span>P&L <span className={`tabular-nums font-semibold ${upl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
          {upl >= 0 ? "+" : ""}${upl.toFixed(0)}
        </span></span>
        <span>Decay <span className={`tabular-nums font-semibold ${profitPct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
          {profitPct.toFixed(0)}%
        </span></span>
        {conv > 0 && <span>Conv <span className="text-slate-300 tabular-nums">{conv}</span></span>}
        <span className="text-slate-600 uppercase">{pos.account}</span>
      </div>
    </div>
  );
}

export function ActiveHarvestCard({ harvests }: { harvests: ActiveHarvest[] }) {
  if (!harvests.length) return null;

  const winning = harvests.filter((h) => h.status === "WINNING").length;
  const tested = harvests.filter((h) => h.status === "TESTED" || h.status === "STOP").length;

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Sprout size={14} className="text-emerald-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Active Harvests</h2>
        </div>
        <div className="flex items-center gap-2 text-[length:var(--t-2xs)]">
          <span className="text-slate-400 tabular-nums">{harvests.length} open</span>
          {winning > 0 && <span className="text-emerald-400 tabular-nums">{winning} winning</span>}
          {tested > 0 && (
            <>
              <span className="text-slate-600">·</span>
              <span className="text-amber-400 tabular-nums">{tested} tested</span>
            </>
          )}
        </div>
      </div>
      <div className="space-y-2">
        {harvests
          .sort((a, b) => {
            const order = { STOP: 0, TESTED: 1, WINNING: 2, FLAT: 3 };
            return (order[a.status] ?? 9) - (order[b.status] ?? 9);
          })
          .map((h, i) => (
            <HarvestPositionRow key={`${h.position.ticker}-${h.position.strike}-${i}`} h={h} />
          ))}
      </div>
    </Card>
  );
}
