import type { DailyPlanRow, NewsSummary } from "../data";
import { Card } from "./Card";
import { ClipboardList, Shield, TrendingUp, Coins, CircleDollarSign, Layers, Flame } from "lucide-react";

function num(v?: string): number {
  const n = Number(v);
  return isNaN(n) ? 0 : n;
}

const LEG_META: Record<string, { label: string; icon: typeof Shield; cls: string }> = {
  core:      { label: "Core",      icon: Layers,            cls: "text-indigo-300" },
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

// Catalyst flag — reuses the news the PWA already computes. Shows ONLY when a
// pick has fresh (24h) news with a non-trivial sentiment. It flags "there's a
// catalyst here, check it" — it does NOT change the pick.
function CatalystChip({ news }: { news?: NewsSummary }) {
  if (!news || (news.count_24h ?? 0) <= 0) return null;
  const best = news.best_score ?? 0;
  const worst = news.worst_score ?? 0;
  if (best < 0.35 && worst > -0.35) return null;   // no strong sentiment → skip
  const neg = worst < -best;
  const cls = neg
    ? "text-rose-300 bg-rose-500/15 border-rose-500/30"
    : "text-amber-300 bg-amber-500/15 border-amber-500/30";
  return (
    <span className={`inline-flex items-center gap-0.5 px-1 py-0.5 rounded text-[length:var(--t-2xs)] font-bold border ${cls}`}
          title={news.latest_headline || "fresh news"}>
      <Flame size={9} /> news
    </span>
  );
}

function PlanRow({ row, news }: { row: DailyPlanRow; news?: NewsSummary }) {
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
          <CatalystChip news={news} />
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

export function TodaysPlanCard({ plan, newsByTicker }: {
  plan: DailyPlanRow[];
  newsByTicker?: Map<string, NewsSummary>;
}) {
  if (!plan.length) return null;
  const newsFor = (t?: string) => newsByTicker?.get((t || "").toUpperCase());
  const rank = (r: DailyPlanRow) => num(r.rank);
  const rows = [...plan].sort((a, b) => rank(a) - rank(b));
  const standing = rows.filter((r) => ["core", "hedge", "protector"].includes((r.leg || "").toLowerCase()));
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
            Standing allocation (core + hedge + protector)
          </div>
          <div className="divide-y divide-white/5">
            {standing.map((r, i) => <PlanRow key={`s${i}`} row={r} news={newsFor(r.ticker)} />)}
          </div>
        </div>
      )}

      {opps.length > 0 && (
        <div className="pt-1.5 border-t border-white/5">
          <div className="text-[length:var(--t-2xs)] text-slate-500 uppercase tracking-wide mb-0.5">
            Opportunities (top growth + income)
          </div>
          <div className="divide-y divide-white/5">
            {opps.map((r, i) => <PlanRow key={`o${i}`} row={r} news={newsFor(r.ticker)} />)}
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
