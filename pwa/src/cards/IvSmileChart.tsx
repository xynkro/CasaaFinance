import { useState, useMemo, useCallback } from "react";
import type { IvSurfaceScanRow } from "../data";
import { numeric } from "../data";
import {
  ComposedChart,
  Scatter,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

// ---------- types ----------

interface IvSmileChartProps {
  contracts: IvSurfaceScanRow[]; // pre-filtered to one ticker + one expiry
  spot: number; // current stock price (for reference line)
}

interface ChartPoint {
  strike: number;
  iv: number;
  ivFitted: number;
  ivExcess: number;
  fill: string;
  r: number;
  // raw fields for tooltip
  delta: string;
  oi: string;
  annYield: string;
  bid: string;
  ask: string;
  type: string;
}

// ---------- constants ----------

const GRID = { stroke: "rgba(255,255,255,0.04)" };
const AXIS_STYLE = { fontSize: 10, fill: "#64748b" } as const;
const FITTED_STROKE = "#8b5cf6";

// ---------- helpers ----------

function dotColor(ivExcess: number): string {
  if (ivExcess > 3) return "#10b981"; // rich — sell
  if (ivExcess < -3) return "#ef4444"; // cheap — skip
  return "#64748b"; // fair
}

function dotRadius(ivExcess: number): number {
  return Math.min(8, 3 + Math.abs(ivExcess));
}

// ---------- custom tooltip ----------

interface SmileTooltipProps {
  active?: boolean;
  payload?: Array<{ payload: ChartPoint }>;
}

function SmileTooltip({ active, payload }: SmileTooltipProps) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  if (!d) return null;

  const rows: [string, string][] = [
    ["Strike", d.strike.toFixed(1)],
    ["IV", `${d.iv.toFixed(1)}%`],
    ["IV excess", `${d.ivExcess > 0 ? "+" : ""}${d.ivExcess.toFixed(1)} pp`],
    ["Delta", d.delta],
    ["OI", Number(d.oi).toLocaleString()],
    ["Ann. Yield", `${d.annYield}%`],
    ["Bid / Ask", `${d.bid} / ${d.ask}`],
  ];

  return (
    <div className="glass rounded-lg px-3 py-2 text-[length:var(--t-xs)] min-w-[160px]">
      <div className="text-slate-400 mb-1 text-[length:var(--t-2xs)]">
        {d.type === "P" ? "Put" : "Call"} {d.strike}
      </div>
      {rows.map(([label, val]) => (
        <div key={label} className="flex justify-between gap-3">
          <span className="text-slate-400">{label}</span>
          <span className="text-white font-semibold tabular-nums">{val}</span>
        </div>
      ))}
    </div>
  );
}

// ---------- custom dot ----------

interface DotProps {
  cx?: number;
  cy?: number;
  payload?: ChartPoint;
  onClick?: (pt: ChartPoint) => void;
}

function SmileDot({ cx, cy, payload, onClick }: DotProps) {
  if (cx == null || cy == null || !payload) return null;
  return (
    <circle
      cx={cx}
      cy={cy}
      r={payload.r}
      fill={payload.fill}
      fillOpacity={0.85}
      stroke={payload.fill}
      strokeWidth={1}
      style={{ cursor: "pointer" }}
      onClick={() => onClick?.(payload)}
    />
  );
}

// ---------- component ----------

export function IvSmileChart({ contracts, spot }: IvSmileChartProps) {
  const [selected, setSelected] = useState<ChartPoint | null>(null);

  const data = useMemo(() => {
    const pts: ChartPoint[] = contracts.map((c) => {
      const ivRaw = numeric(c.iv) * 100;
      const ivFittedRaw = numeric(c.iv_fitted) * 100;
      const ivExcess = numeric(c.iv_excess);
      return {
        strike: numeric(c.strike),
        iv: ivRaw,
        ivFitted: ivFittedRaw,
        ivExcess,
        fill: dotColor(ivExcess),
        r: dotRadius(ivExcess),
        delta: c.delta ?? "—",
        oi: c.oi ?? "0",
        annYield: c.ann_yield_pct ?? "—",
        bid: c.bid ?? "—",
        ask: c.ask ?? "—",
        type: c.type ?? "?",
      };
    });
    pts.sort((a, b) => a.strike - b.strike);
    return pts;
  }, [contracts]);

  const handleDotClick = useCallback((pt: ChartPoint) => {
    setSelected((prev) => (prev?.strike === pt.strike ? null : pt));
  }, []);

  if (!data.length) {
    return (
      <div className="text-slate-500 text-[length:var(--t-xs)] text-center py-6">
        No contracts for this expiry
      </div>
    );
  }

  return (
    <div className="relative">
      <ResponsiveContainer width="100%" height={250}>
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" {...GRID} />
          <XAxis
            dataKey="strike"
            type="number"
            domain={["dataMin - 1", "dataMax + 1"]}
            tick={AXIS_STYLE}
            tickLine={false}
            axisLine={false}
            label={{
              value: "Strike",
              position: "insideBottomRight",
              offset: -4,
              style: { ...AXIS_STYLE, fontSize: 9 },
            }}
          />
          <YAxis
            dataKey="iv"
            type="number"
            tick={AXIS_STYLE}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => `${v.toFixed(0)}%`}
            width={42}
          />

          {/* Spot reference line */}
          <ReferenceLine
            x={spot}
            stroke="#94a3b8"
            strokeDasharray="4 4"
            label={{
              value: "Spot",
              position: "top",
              style: { fill: "#94a3b8", fontSize: 9 },
            }}
          />

          {/* Fitted IV curve */}
          <Line
            dataKey="ivFitted"
            type="monotone"
            stroke={FITTED_STROKE}
            strokeDasharray="6 3"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />

          {/* Actual IV scatter */}
          <Scatter
            dataKey="iv"
            isAnimationActive={false}
            shape={<SmileDot onClick={handleDotClick} />}
          />

          <Tooltip
            content={<SmileTooltip />}
            cursor={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Popover on selected contract */}
      {selected && (
        <div
          className="absolute top-2 right-2 glass rounded-lg px-3 py-2 text-[length:var(--t-xs)] min-w-[170px] z-10 border border-white/10"
          onClick={() => setSelected(null)}
        >
          <div className="text-slate-400 text-[length:var(--t-2xs)] mb-1">
            {selected.type === "P" ? "Put" : "Call"} {selected.strike} &mdash; tap to dismiss
          </div>
          {(
            [
              ["Strike", selected.strike.toFixed(1)],
              ["IV", `${selected.iv.toFixed(1)}%`],
              [
                "IV excess",
                `${selected.ivExcess > 0 ? "+" : ""}${selected.ivExcess.toFixed(1)} pp`,
              ],
              ["Delta", selected.delta],
              ["OI", Number(selected.oi).toLocaleString()],
              ["Ann. Yield", `${selected.annYield}%`],
              ["Bid / Ask", `${selected.bid} / ${selected.ask}`],
            ] as [string, string][]
          ).map(([label, val]) => (
            <div key={label} className="flex justify-between gap-3">
              <span className="text-slate-400">{label}</span>
              <span className="text-white font-semibold tabular-nums">{val}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
