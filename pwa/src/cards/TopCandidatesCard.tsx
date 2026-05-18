import { useState } from "react";
import type { IvSurfaceScanRow } from "../data";
import { numeric } from "../data";
import { Card } from "./Card";
import { Activity, ChevronDown, ChevronUp } from "lucide-react";

// --------------- helpers ---------------

function rowBg(excess: number): string {
  if (excess > 5) return "bg-emerald-500/10";
  if (excess >= 3) return "bg-emerald-500/5";
  return "";
}

function AssignmentBadge({ risk }: { risk: string }) {
  if (!risk) return null;
  const color =
    risk === "LOW"
      ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
      : risk === "MEDIUM"
        ? "bg-amber-500/20 text-amber-400 border-amber-500/30"
        : "bg-red-500/20 text-red-400 border-red-500/30";
  return (
    <span className={`px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-bold border ${color}`}>
      {risk}
    </span>
  );
}

function TypeBadge({ type }: { type: string }) {
  const color =
    type === "P"
      ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
      : "bg-blue-500/20 text-blue-400 border-blue-500/30";
  return (
    <span className={`px-1.5 py-0.5 rounded text-[length:var(--t-2xs)] font-bold border ${color}`}>
      {type}
    </span>
  );
}

function WarningDots({ row }: { row: IvSurfaceScanRow }) {
  const spread = numeric(row.spread_pct);
  const oi = numeric(row.oi);
  const earningsFlag = (row.earnings_before_expiry ?? "").toUpperCase() === "TRUE";
  const liquidity = spread > 15 || oi < 50;

  if (!liquidity && !earningsFlag) return null;

  return (
    <span className="flex items-center gap-0.5">
      {earningsFlag && <span className="inline-block w-1.5 h-1.5 rounded-full bg-red-400" title="Earnings before expiry" />}
      {liquidity && <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400" title="Wide spread or thin OI" />}
    </span>
  );
}

// --------------- row ---------------

function CandidateRow({
  row,
  onSelect,
}: {
  row: IvSurfaceScanRow;
  onSelect?: (r: IvSurfaceScanRow) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const excess = numeric(row.iv_excess);
  const delta = numeric(row.delta);
  const yld = numeric(row.ann_yield_pct);
  const oi = numeric(row.oi);
  const dte = numeric(row.dte);
  const strike = numeric(row.strike);
  const bid = numeric(row.bid);
  const ask = numeric(row.ask);
  const spread = numeric(row.spread_pct);
  const vol = numeric(row.volume);
  const spot = numeric(row.spot);
  const iv = numeric(row.iv);
  const ivFitted = numeric(row.iv_fitted);

  return (
    <button
      type="button"
      onClick={() => {
        setExpanded((e) => !e);
        if (onSelect) onSelect(row);
      }}
      className={`w-full text-left glass rounded-xl p-3 active:bg-white/3 transition-colors space-y-1.5 ${rowBg(excess)}`}
    >
      {/* Main row */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="text-[length:var(--t-sm)] font-bold text-white">{row.ticker ?? "—"}</span>
          <TypeBadge type={row.type ?? "P"} />
          <span className="text-[length:var(--t-2xs)] tabular-nums text-slate-300 font-semibold">
            ${strike.toFixed(0)}
          </span>
          <span className="text-[length:var(--t-2xs)] text-slate-500">{row.expiry ?? ""}</span>
          <WarningDots row={row} />
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`text-[length:var(--t-sm)] font-bold tabular-nums ${
              excess >= 5 ? "text-emerald-400" : excess >= 3 ? "text-lime-400" : "text-slate-300"
            }`}
          >
            +{excess.toFixed(1)}pp
          </span>
          <AssignmentBadge risk={row.assignment_risk ?? ""} />
        </div>
      </div>

      {/* Secondary metrics */}
      <div className="flex gap-3 text-[length:var(--t-2xs)] text-slate-500 tabular-nums">
        <span>{dte}d</span>
        <span>Δ{delta.toFixed(2)}</span>
        <span>{yld.toFixed(0)}% ann</span>
        <span>OI {oi.toLocaleString()}</span>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="pt-2 border-t border-white/5 space-y-1.5">
          <div className="grid grid-cols-4 gap-1.5 text-[length:var(--t-2xs)]">
            <div>
              <div className="text-slate-600">Bid</div>
              <div className="tabular-nums text-slate-300 font-semibold">${bid.toFixed(2)}</div>
            </div>
            <div>
              <div className="text-slate-600">Ask</div>
              <div className="tabular-nums text-slate-300 font-semibold">${ask.toFixed(2)}</div>
            </div>
            <div>
              <div className="text-slate-600">Spread</div>
              <div className={`tabular-nums font-semibold ${spread > 15 ? "text-amber-400" : "text-slate-300"}`}>
                {spread.toFixed(1)}%
              </div>
            </div>
            <div>
              <div className="text-slate-600">Volume</div>
              <div className="tabular-nums text-slate-300 font-semibold">{vol.toLocaleString()}</div>
            </div>
          </div>
          <div className="grid grid-cols-4 gap-1.5 text-[length:var(--t-2xs)]">
            <div>
              <div className="text-slate-600">Spot</div>
              <div className="tabular-nums text-slate-300 font-semibold">${spot.toFixed(2)}</div>
            </div>
            <div>
              <div className="text-slate-600">IV</div>
              <div className="tabular-nums text-slate-300 font-semibold">{(iv * 100).toFixed(1)}%</div>
            </div>
            <div>
              <div className="text-slate-600">Fitted</div>
              <div className="tabular-nums text-slate-300 font-semibold">{(ivFitted * 100).toFixed(1)}%</div>
            </div>
            <div>
              <div className="text-slate-600">Earnings</div>
              <div className={`tabular-nums font-semibold ${
                (row.earnings_before_expiry ?? "").toUpperCase() === "TRUE" ? "text-red-400" : "text-slate-300"
              }`}>
                {(row.earnings_before_expiry ?? "").toUpperCase() === "TRUE" ? "Yes" : "No"}
              </div>
            </div>
          </div>
        </div>
      )}
    </button>
  );
}

// --------------- card ---------------

const DEFAULT_COUNT = 15;

export function TopCandidatesCard({
  contracts,
  onSelectContract,
}: {
  contracts: IvSurfaceScanRow[];
  onSelectContract?: (row: IvSurfaceScanRow) => void;
}) {
  const [showAll, setShowAll] = useState(false);

  // Filter: only rich premium (iv_excess > 0), default to LOW assignment risk
  const [riskFilter, setRiskFilter] = useState<"ALL" | "LOW" | "MEDIUM" | "HIGH">("LOW");

  const filtered = contracts
    .filter((r) => numeric(r.iv_excess) > 0)
    .filter((r) => riskFilter === "ALL" || (r.assignment_risk ?? "").toUpperCase() === riskFilter)
    .sort((a, b) => numeric(b.iv_excess) - numeric(a.iv_excess));

  const display = showAll ? filtered : filtered.slice(0, DEFAULT_COUNT);
  const hasMore = filtered.length > DEFAULT_COUNT;

  if (!contracts.length) {
    return (
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <Activity size={14} className="text-emerald-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Top Candidates</h2>
        </div>
        <p className="text-[length:var(--t-xs)] text-slate-500 py-4 text-center">
          No IV surface scan data available.
        </p>
      </Card>
    );
  }

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Activity size={14} className="text-emerald-400" />
          <h2 className="text-[length:var(--t-sm)] font-medium text-slate-400">Top Candidates</h2>
        </div>
        <span className="text-[length:var(--t-2xs)] text-slate-600 tabular-nums">
          {filtered.length} contract{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Risk filter toggles */}
      <div className="flex gap-1.5 mb-3">
        {(["LOW", "MEDIUM", "HIGH", "ALL"] as const).map((level) => (
          <button
            key={level}
            type="button"
            onClick={() => setRiskFilter(level)}
            className={`px-2 py-0.5 rounded text-[length:var(--t-2xs)] font-semibold transition-colors ${
              riskFilter === level
                ? "bg-indigo-500/25 text-indigo-300 border border-indigo-500/40"
                : "text-slate-500 border border-white/5 active:bg-white/5"
            }`}
          >
            {level}
          </button>
        ))}
      </div>

      <div className="space-y-2">
        {display.map((r, i) => (
          <CandidateRow
            key={`${r.ticker}-${r.type}-${r.strike}-${r.expiry}-${i}`}
            row={r}
            onSelect={onSelectContract}
          />
        ))}
      </div>

      {!filtered.length && (
        <p className="text-[length:var(--t-xs)] text-slate-500 py-4 text-center">
          No candidates match the current filter.
        </p>
      )}

      {hasMore && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="flex items-center justify-center gap-1 w-full pt-3 mt-3 border-t border-white/5 text-[length:var(--t-xs)] text-indigo-400 font-medium"
        >
          <span>{showAll ? "Show less" : `Show all ${filtered.length}`}</span>
          {showAll ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>
      )}
    </Card>
  );
}
