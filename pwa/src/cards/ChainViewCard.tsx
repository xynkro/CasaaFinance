import type { IvSurfaceScanRow } from "../data";
import { numeric } from "../data";
import { Card } from "./Card";
import { Table2 } from "lucide-react";

interface ChainViewCardProps {
  contracts: IvSurfaceScanRow[]; // pre-filtered to one ticker + one expiry
  spot: number;                   // current stock price
}

// ---------- helpers ----------

function rowBgByExcess(excess: number): string {
  if (excess > 5) return "bg-emerald-500/10";
  if (excess > 3) return "bg-emerald-500/5";
  if (excess < -3) return "bg-red-500/5";
  return "";
}

function warnBg(spreadPct: number, oi: number, volume: number): string {
  if (spreadPct > 15 || oi < 50 || volume < 10) return "bg-amber-500/15";
  return "";
}

function isItm(type: string, strike: number, spot: number): boolean {
  if (type === "P") return strike > spot;
  if (type === "C") return strike < spot;
  return false;
}

// ---------- column header ----------

const COLS = ["Strike", "Ty", "IV%", "+pp", "Dl", "Bid/Ask", "OI", "Yld%"] as const;

// ---------- component ----------

export function ChainViewCard({ contracts, spot }: ChainViewCardProps) {
  if (contracts.length === 0) {
    return (
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <Table2 size={14} className="text-blue-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Option Chain</h2>
        </div>
        <p className="text-[length:var(--t-xs)] text-slate-500 text-center py-4">
          No contracts for this expiry
        </p>
      </Card>
    );
  }

  // Sort by strike ascending
  const sorted = [...contracts].sort(
    (a, b) => numeric(a.strike) - numeric(b.strike),
  );

  // Find where to insert spot divider (first strike >= spot)
  const dividerIdx = sorted.findIndex((c) => numeric(c.strike) >= spot);

  return (
    <Card noPad>
      {/* Header */}
      <div className="flex items-center justify-between px-4 pt-4 pb-2">
        <div className="flex items-center gap-2">
          <Table2 size={14} className="text-blue-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Option Chain</h2>
        </div>
        <span className="text-[length:var(--t-2xs)] text-slate-500 tabular-nums">
          {sorted.length} contracts
        </span>
      </div>

      {/* Scrollable table */}
      <div className="overflow-x-auto -mx-0 px-0 pb-4">
        <div className="min-w-[520px]">
          {/* Column headers */}
          <div className="grid grid-cols-[auto_28px_1fr_1fr_1fr_1fr_1fr_1fr] gap-x-2 px-4 py-1.5 text-[length:var(--t-2xs)] text-slate-500 font-medium border-b border-white/5">
            {COLS.map((h) => (
              <span key={h} className={h === "Strike" ? "font-semibold" : "text-right"}>
                {h}
              </span>
            ))}
          </div>

          {/* Rows */}
          {sorted.map((c, idx) => {
            const strike = numeric(c.strike);
            const ivPct = numeric(c.iv) * 100;
            const excess = numeric(c.iv_excess);
            const delta = Math.abs(numeric(c.delta));
            const bid = numeric(c.bid);
            const ask = numeric(c.ask);
            const oi = numeric(c.oi);
            const vol = numeric(c.volume);
            const spreadPct = numeric(c.spread_pct);
            const yld = numeric(c.ann_yield_pct);
            const type = c.type ?? "?";
            const itm = isItm(type, strike, spot);

            // Row shading: iv_excess > ITM > default
            const excessBg = rowBgByExcess(excess);
            const itmBg = itm && !excessBg ? "bg-white/5" : "";
            const rowBg = excessBg || itmBg;

            // Insert spot divider before this row if appropriate
            const showDivider = dividerIdx >= 0 && idx === dividerIdx;

            return (
              <div key={`${c.ticker}-${c.type}-${c.strike}-${idx}`}>
                {showDivider && (
                  <div className="flex items-center gap-2 px-4 py-0.5">
                    <div className="flex-1 border-t border-amber-500/30" />
                    <span className="text-[length:var(--t-2xs)] text-amber-400/70 font-medium tabular-nums shrink-0">
                      Spot {spot.toFixed(2)}
                    </span>
                    <div className="flex-1 border-t border-amber-500/30" />
                  </div>
                )}
                <div
                  className={`grid grid-cols-[auto_28px_1fr_1fr_1fr_1fr_1fr_1fr] gap-x-2 px-4 py-1 text-[length:var(--t-2xs)] items-center ${rowBg}`}
                >
                  {/* Strike */}
                  <span className="font-semibold text-white tabular-nums">
                    {strike.toFixed(strike % 1 === 0 ? 0 : 1)}
                  </span>

                  {/* Type badge */}
                  <span
                    className={`text-center rounded px-1 py-px text-[length:var(--t-3xs)] font-bold leading-none ${
                      type === "P"
                        ? "bg-emerald-500/15 text-emerald-400"
                        : type === "C"
                          ? "bg-blue-500/15 text-blue-400"
                          : "bg-slate-500/15 text-slate-400"
                    }`}
                  >
                    {type}
                  </span>

                  {/* IV% */}
                  <span className="text-right tabular-nums text-slate-300">
                    {ivPct > 0 ? ivPct.toFixed(1) : "—"}
                  </span>

                  {/* IV excess (+pp) */}
                  <span
                    className={`text-right tabular-nums ${
                      excess > 3
                        ? "text-emerald-400"
                        : excess < -3
                          ? "text-red-400"
                          : "text-slate-400"
                    }`}
                  >
                    {excess > 0 ? "+" : ""}
                    {excess.toFixed(1)}
                  </span>

                  {/* Delta */}
                  <span className="text-right tabular-nums text-slate-400">
                    {delta > 0 ? delta.toFixed(2) : "—"}
                  </span>

                  {/* Bid/Ask */}
                  <span
                    className={`text-right tabular-nums text-slate-300 ${warnBg(spreadPct, oi, vol)}`}
                  >
                    {bid.toFixed(2)}/{ask.toFixed(2)}
                  </span>

                  {/* OI */}
                  <span
                    className={`text-right tabular-nums text-slate-400 ${
                      oi < 50 ? "bg-amber-500/15" : ""
                    }`}
                  >
                    {oi > 0 ? oi.toLocaleString() : "—"}
                  </span>

                  {/* Yield% */}
                  <span
                    className={`text-right tabular-nums ${
                      yld >= 15
                        ? "text-emerald-400 font-semibold"
                        : yld >= 10
                          ? "text-emerald-400"
                          : "text-slate-400"
                    }`}
                  >
                    {yld > 0 ? yld.toFixed(1) : "—"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}
