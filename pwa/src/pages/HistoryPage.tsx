import { useState } from "react";
import type { SnapshotRow, MacroRow } from "../data";
import { Card } from "../cards/Card";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { TrendingUp, BarChart3, Activity } from "lucide-react";

// ---------- helpers ----------

function shortDate(d: string): string {
  const s = d.slice(0, 10); // YYYY-MM-DD
  const [, m, day] = s.split("-");
  const months = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[Number(m)]} ${Number(day)}`;
}

function fmtUsd(v: number): string {
  return `$${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

// ---------- chart theme ----------

const GRID = { stroke: "rgba(255,255,255,0.04)" };
const AXIS_STYLE = { fontSize: 10, fill: "#64748b" };

function ChartTooltipContent({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number; color: string }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="glass rounded-lg px-3 py-2 text-xs">
      <div className="text-slate-400 mb-1">{label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full" style={{ background: p.color }} />
          <span className="text-slate-300">{p.name}</span>
          <span className="text-white font-semibold tabular-nums ml-auto">
            {typeof p.value === "number" ? p.value.toLocaleString("en-US", { maximumFractionDigits: 2 }) : p.value}
          </span>
        </div>
      ))}
    </div>
  );
}

// ---------- time range filter ----------

type Range = "1M" | "3M" | "6M" | "YTD" | "ALL";

function filterByRange<T extends { date: string }>(rows: T[], range: Range): T[] {
  if (range === "ALL" || !rows.length) return rows;
  const now = new Date();
  let cutoff: Date;
  if (range === "YTD") {
    cutoff = new Date(now.getFullYear(), 0, 1);
  } else {
    const months = range === "1M" ? 1 : range === "3M" ? 3 : 6;
    cutoff = new Date(now);
    cutoff.setMonth(cutoff.getMonth() - months);
  }
  const cutStr = cutoff.toISOString().slice(0, 10);
  return rows.filter((r) => r.date.slice(0, 10) >= cutStr);
}

function RangeSelector({ value, onChange }: { value: Range; onChange: (r: Range) => void }) {
  const ranges: Range[] = ["1M", "3M", "6M", "YTD", "ALL"];
  return (
    <div className="flex gap-1">
      {ranges.map((r) => (
        <button
          key={r}
          onClick={() => onChange(r)}
          className={`px-2.5 py-1 rounded-md text-[10px] font-semibold transition-all ${
            value === r
              ? "bg-indigo-500/20 text-indigo-400 border border-indigo-500/30"
              : "text-slate-500 hover:text-slate-300 border border-transparent"
          }`}
        >
          {r}
        </button>
      ))}
    </div>
  );
}

// ---------- Portfolio Value Chart ----------

function PortfolioChart({
  caspar,
  sarah,
  macro,
  range,
}: {
  caspar: SnapshotRow[];
  sarah: SnapshotRow[];
  macro: MacroRow[];
  range: Range;
}) {
  const fc = filterByRange(caspar, range);
  const fs = filterByRange(sarah, range);
  const fm = filterByRange(macro, range);

  // Build merged data by date
  const macroMap = new Map(fm.map((m) => [m.date.slice(0, 10), Number(m.usd_sgd) || 1]));
  const sarahMap = new Map(fs.map((s) => [s.date.slice(0, 10), Number(s.net_liq) || 0]));

  const chartData = fc.map((c) => {
    const dateKey = c.date.slice(0, 10);
    const casparVal = Number(c.net_liq) || 0;
    const sarahSgd = sarahMap.get(dateKey) ?? 0;
    const rate = macroMap.get(dateKey) ?? 1;
    const sarahUsd = rate > 0 ? sarahSgd / rate : 0;
    return {
      date: shortDate(dateKey),
      Caspar: Math.round(casparVal),
      Sarah: Math.round(sarahUsd),
      Combined: Math.round(casparVal + sarahUsd),
    };
  });

  if (!chartData.length) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-slate-500">
          <TrendingUp size={16} />
          <span className="text-sm">Portfolio history — no data yet</span>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <div className="flex items-center gap-2 mb-4">
        <TrendingUp size={14} className="text-indigo-400" />
        <h3 className="text-sm font-medium text-slate-400">Portfolio Value</h3>
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={chartData}>
          <defs>
            <linearGradient id="gradCaspar" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="gradSarah" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="date" tick={AXIS_STYLE} axisLine={false} tickLine={false} />
          <YAxis tick={AXIS_STYLE} axisLine={false} tickLine={false} tickFormatter={fmtUsd} width={55} />
          <Tooltip content={<ChartTooltipContent />} />
          <Area type="monotone" dataKey="Caspar" stroke="#3b82f6" fill="url(#gradCaspar)" strokeWidth={2} dot={false} />
          <Area type="monotone" dataKey="Sarah" stroke="#8b5cf6" fill="url(#gradSarah)" strokeWidth={2} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </Card>
  );
}

// ---------- Macro Chart ----------

type MacroMetric = "vix" | "spx" | "dxy" | "us_10y" | "usd_sgd";

const MACRO_CONFIG: Record<MacroMetric, { label: string; color: string }> = {
  spx: { label: "S&P 500", color: "#10b981" },
  vix: { label: "VIX", color: "#f59e0b" },
  dxy: { label: "DXY", color: "#6366f1" },
  us_10y: { label: "US 10Y", color: "#ef4444" },
  usd_sgd: { label: "USD/SGD", color: "#06b6d4" },
};

function MacroChart({ macro, range }: { macro: MacroRow[]; range: Range }) {
  const [metric, setMetric] = useState<MacroMetric>("spx");
  const filtered = filterByRange(macro, range);
  const cfg = MACRO_CONFIG[metric];

  const chartData = filtered.map((m) => ({
    date: shortDate(m.date.slice(0, 10)),
    value: Number(m[metric]) || 0,
  }));

  if (!chartData.length) {
    return (
      <Card>
        <div className="flex items-center gap-2 text-slate-500">
          <Activity size={16} />
          <span className="text-sm">Macro history — no data yet</span>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Activity size={14} className="text-indigo-400" />
          <h3 className="text-sm font-medium text-slate-400">Macro</h3>
        </div>
      </div>

      {/* Metric pills */}
      <div className="flex gap-1.5 mb-4 overflow-x-auto no-scrollbar -mx-1 px-1">
        {(Object.keys(MACRO_CONFIG) as MacroMetric[]).map((key) => {
          const c = MACRO_CONFIG[key];
          const isActive = metric === key;
          return (
            <button
              key={key}
              onClick={() => setMetric(key)}
              className={`shrink-0 px-2.5 py-1 rounded-md text-[10px] font-semibold transition-all border ${
                isActive
                  ? "border-white/15 bg-white/5 text-white"
                  : "border-transparent text-slate-500"
              }`}
            >
              {c.label}
            </button>
          );
        })}
      </div>

      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={chartData}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="date" tick={AXIS_STYLE} axisLine={false} tickLine={false} />
          <YAxis tick={AXIS_STYLE} axisLine={false} tickLine={false} width={50} domain={["auto", "auto"]} />
          <Tooltip content={<ChartTooltipContent />} />
          <Line
            type="monotone"
            dataKey="value"
            name={cfg.label}
            stroke={cfg.color}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: cfg.color }}
          />
        </LineChart>
      </ResponsiveContainer>
    </Card>
  );
}

// ---------- P&L Change Chart ----------

function PnlChart({ caspar, range }: { caspar: SnapshotRow[]; range: Range }) {
  const filtered = filterByRange(caspar, range);

  const chartData = filtered.map((c) => ({
    date: shortDate(c.date.slice(0, 10)),
    pct: Number((Number(c.upl_pct) * 100).toFixed(2)),
  }));

  if (!chartData.length) return null;

  return (
    <Card>
      <div className="flex items-center gap-2 mb-4">
        <BarChart3 size={14} className="text-indigo-400" />
        <h3 className="text-sm font-medium text-slate-400">Caspar UPL %</h3>
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <AreaChart data={chartData}>
          <defs>
            <linearGradient id="gradPnl" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#10b981" stopOpacity={0.25} />
              <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="date" tick={AXIS_STYLE} axisLine={false} tickLine={false} />
          <YAxis tick={AXIS_STYLE} axisLine={false} tickLine={false} tickFormatter={(v: number) => `${v}%`} width={40} />
          <Tooltip content={<ChartTooltipContent />} />
          <Area type="monotone" dataKey="pct" name="UPL %" stroke="#10b981" fill="url(#gradPnl)" strokeWidth={2} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </Card>
  );
}

// ---------- Page ----------

export function HistoryPage({
  casparHistory,
  sarahHistory,
  macroHistory,
}: {
  casparHistory: SnapshotRow[];
  sarahHistory: SnapshotRow[];
  macroHistory: MacroRow[];
}) {
  const [range, setRange] = useState<Range>("ALL");

  return (
    <div className="px-4 pb-4 flex flex-col gap-4">
      {/* Range selector */}
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider">Time Range</h3>
        <RangeSelector value={range} onChange={setRange} />
      </div>

      <div className="fade-up fade-up-1">
        <PortfolioChart caspar={casparHistory} sarah={sarahHistory} macro={macroHistory} range={range} />
      </div>
      <div className="fade-up fade-up-2">
        <PnlChart caspar={casparHistory} range={range} />
      </div>
      <div className="fade-up fade-up-3">
        <MacroChart macro={macroHistory} range={range} />
      </div>
    </div>
  );
}
