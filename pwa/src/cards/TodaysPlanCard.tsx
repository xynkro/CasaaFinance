import type { DailyPlanRow } from "../data";
import { Card } from "./Card";
import { ClipboardList, Shield, TrendingUp, Coins, CircleDollarSign } from "lucide-react";

function num(v?: string): number {
  const n = Number(v);
  return isNaN(n) ? 0 : n;
}

const LEG_META: Record<string, { label: string; icon: typeof Shield; cls: string }> = {
  hedge:     { label: "Hedge",     icon: Shield,            cls: "text-violet-300" },
  protector: { label: "Protector", icon: Coins,             cls: "text-sky-300" },
  growth:    { label: "Growth",    icon: TrendingUp,        cls: "text-emerald-300" },
  income:    { label: "Income",    icon: CircleDollarSign,  cls: "text-amber-300" },
};

// "" = pending; the auto-trader writes the outcome back per row.
function StatusPill({ status }: { status?: string }) {
  const s = (status || "").toLowerCase();
  let cls = "text-slate-500 bg-slate-500/10 border-slate-500/20";
  let label = "pending";
  if (s.startsWith("filled")) { cls = "text-emerald-300 bg-emerald-500/15 border-emerald-500/30"; label = "filled"; }
  else if (s.startsWith("held")) { cls = "text-sky-300 bg-sky-500/15 border-sky-500/30"; label = "held"; }
  else if (s.startsWith("skipped")) { cls = "text-slate-400 bg-slate-500/10 border-slate-500/25"; label = "skipped"; }
  else if (s.startsWith("failed")) { cls = "text-rose-300 bg-rose-500/15 border-rose-500/30"; label = "failed"; }
  return (
    <span className={`px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-bold border ${cls}`}>
      {label}
    </span>
  );
}

function PlanRow({ row }: { row: DailyPlanRow }) {
  const meta = LEG_META[(row.leg || "").toLowerCase()] ?? LEG_META.growth;
  const Icon = meta.icon;
  return (
    <div className="flex items-start gap-2 py-1.5">
      <Icon size={13} className={`${meta.cls} mt-0.5 shrink-0`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[length:var(--t-sm)] font-bold text-white">{row.ticker}</span>
          <span className={`text-[length:var(--t-2xs)] font-semibold ${meta.cls}`}>{meta.label}</span>
          <span className="text-[length:var(--t-2xs)] text-slate-500 tabular-nums">{row.detail}</span>
          <StatusPill status={row.fill_status} />
        </div>
        {row.reason && (
          <p className="text-[length:var(--t-2xs)] text-slate-600 leading-snug line-clamp-1">{row.reason}</p>
        )}
      </div>
      <span className="text-[length:var(--t-2xs)] text-slate-600 tabular-nums shrink-0">
        {num(row.conviction) > 0 ? `${Math.round(num(row.conviction))}` : ""}
      </span>
    </div>
  );
}

export function TodaysPlanCard({ plan }: { plan: DailyPlanRow[] }) {
  if (!plan.length) return null;
  const rank = (r: DailyPlanRow) => num(r.rank);
  const rows = [...plan].sort((a, b) => rank(a) - rank(b));
  const standing = rows.filter((r) => ["hedge", "protector"].includes((r.leg || "").toLowerCase()));
  const opps = rows.filter((r) => ["growth", "income"].includes((r.leg || "").toLowerCase()));
  const filled = rows.filter((r) => (r.fill_status || "").toLowerCase().startsWith("filled")).length;

  return (
    <Card>
      <div className="flex items-center gap-2 mb-2">
        <ClipboardList size={15} className="text-amber-400" />
        <h3 className="text-[length:var(--t-sm)] font-semibold text-slate-200">Today's Plan</h3>
        <span className="text-[length:var(--t-2xs)] text-slate-600">
          what the bot trades · {filled}/{rows.length} filled
        </span>
      </div>
      <p className="text-[length:var(--t-2xs)] text-slate-600 mb-2 -mt-1">
        One source of truth — the auto-trader executes exactly this list, nothing else.
      </p>

      {standing.length > 0 && (
        <div className="mb-1">
          <div className="text-[length:var(--t-2xs)] text-slate-500 uppercase tracking-wide mb-0.5">
            Standing allocation (hedge + protector)
          </div>
          <div className="divide-y divide-white/5">
            {standing.map((r, i) => <PlanRow key={`s${i}`} row={r} />)}
          </div>
        </div>
      )}

      {opps.length > 0 && (
        <div className="pt-1.5 border-t border-white/5">
          <div className="text-[length:var(--t-2xs)] text-slate-500 uppercase tracking-wide mb-0.5">
            Opportunities (top growth + income)
          </div>
          <div className="divide-y divide-white/5">
            {opps.map((r, i) => <PlanRow key={`o${i}`} row={r} />)}
          </div>
        </div>
      )}
      {opps.length === 0 && (
        <p className="text-[length:var(--t-2xs)] text-slate-600 pt-1.5 border-t border-white/5">
          No fresh growth/income opportunities today — holding the standing allocation only.
        </p>
      )}
    </Card>
  );
}
