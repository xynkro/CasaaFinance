import type { LivePriceRow, PositionRow, TechnicalScoreRow } from "../data";
import { numeric, numericOrNull } from "../data";
import { Card } from "./Card";
import { LayoutGrid } from "lucide-react";

/**
 * Market Map — TradingView-style sector-heatmap treemap over OUR universe:
 * tiles sized by position weight (combined |mkt_val| across both accounts),
 * coloured by today's % change from the 5-min TV live-price feed. One glance
 * answers "who's selling, what's the movement like" across portfolio +
 * watchlist without opening a single chart.
 *
 * Pragmatic treemap: no d3 — a dense CSS grid with three size classes
 * (top-4 weights 2×2, next-6 2×1, rest 1×1). Watchlist (tech-scan tickers
 * not already held) renders as uniform small tiles below. Tickers without
 * a live price are skipped; if the live feed is empty the card renders null.
 */

interface Tile {
  ticker: string;
  pct: number;     // day change %, percent units (e.g. +1.5)
  weight: number;  // combined |mkt_val| across accounts (0 for watchlist)
}

// ---- colour scale -----------------------------------------------------------
// Continuous red → dark-neutral → green, clamped at ±3% (heatmap convention).
// Per-channel lerp from slate-900 toward red-600 / green-600 by |pct| / 3, so
// magnitude maps to saturation while white text stays readable at both ends.

const MID: [number, number, number] = [15, 23, 42];   // #0f172a — ~0%
const NEG: [number, number, number] = [220, 38, 38];  // #dc2626 — ≤ −3%
const POS: [number, number, number] = [22, 163, 74];  // #16a34a — ≥ +3%

function heatColor(pct: number): string {
  const t = Math.max(-1, Math.min(1, pct / 3));
  const to = t >= 0 ? POS : NEG;
  const k = Math.abs(t);
  const [r, g, b] = MID.map((c, i) => Math.round(c + (to[i] - c) * k));
  return `rgb(${r} ${g} ${b})`;
}

function fmtPct(pct: number): string {
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

// ---- freshness --------------------------------------------------------------
// live_prices `updated_at` is the SGT-anchored audit suffix "YYYY-MM-DDTHHMMSS"
// (no colons in the time part) — same format PnlCard's freshness chip parses.

function parseSgtAudit(s: string): Date | null {
  if (!s) return null;
  const m = s.match(/^(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})(\d{2})$/);
  if (m) {
    const d = new Date(`${m[1]}T${m[2]}:${m[3]}:${m[4]}+08:00`);
    return isNaN(d.getTime()) ? null : d;
  }
  const d = new Date(s); // fallback: already-colon-separated ISO
  return isNaN(d.getTime()) ? null : d;
}

function fmtAgo(s: string): { short: string; full: string; stale: boolean } {
  const d = parseSgtAudit(s);
  if (!d) return { short: "", full: s, stale: false };
  const min = Math.max(0, Math.round((Date.now() - d.getTime()) / 60000));
  const full = d.toLocaleString("en-SG", {
    timeZone: "Asia/Singapore",
    hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short",
  });
  let short: string;
  if (min < 1) short = "just now";
  else if (min < 60) short = `${min}m ago`;
  else if (min < 24 * 60) short = `${Math.floor(min / 60)}h ago`;
  else short = `${Math.floor(min / (24 * 60))}d ago`;
  // Live feed runs on a 5-min cron — >10 min means the feed is lagging.
  return { short, full, stale: min > 10 };
}

// ---- tiles ------------------------------------------------------------------

type SizeClass = "lg" | "md" | "sm";

/** Treemap-ish tiers: top-4 weights 2×2, next-6 2×1, rest 1×1. */
function sizeFor(rank: number): SizeClass {
  if (rank < 4) return "lg";
  if (rank < 10) return "md";
  return "sm";
}

const SPAN: Record<SizeClass, string> = {
  lg: "col-span-2 row-span-2",
  md: "col-span-2 row-span-1",
  sm: "col-span-1 row-span-1",
};
const TICKER_CLS: Record<SizeClass, string> = {
  lg: "text-[length:var(--t-base)]",
  md: "text-[length:var(--t-xs)]",
  sm: "text-[length:var(--t-2xs)]",
};
const PCT_CLS: Record<SizeClass, string> = {
  lg: "text-[length:var(--t-sm)]",
  md: "text-[length:var(--t-2xs)]",
  sm: "text-[length:var(--t-2xs)]",
};

function TileBox({ tile, size }: { tile: Tile; size: SizeClass }) {
  return (
    <div
      className={`${SPAN[size]} rounded-md border border-white/10 flex flex-col items-center justify-center overflow-hidden px-0.5`}
      style={{ background: heatColor(tile.pct) }}
      title={`${tile.ticker} ${fmtPct(tile.pct)}`}
    >
      <span className={`${TICKER_CLS[size]} font-bold text-white leading-tight truncate max-w-full`}>
        {tile.ticker}
      </span>
      <span className={`${PCT_CLS[size]} font-tabular font-semibold text-white/85 leading-tight`}>
        {fmtPct(tile.pct)}
      </span>
    </div>
  );
}

/** "Nup · Mdn" breadth chip for a section header. */
function Breadth({ tiles }: { tiles: Tile[] }) {
  const up = tiles.filter((t) => t.pct > 0).length;
  const down = tiles.filter((t) => t.pct < 0).length;
  return (
    <span className="text-[length:var(--t-2xs)] font-tabular">
      <span className="text-emerald-400/70">{up}↑</span>
      <span className="text-slate-600"> · </span>
      <span className="text-red-400/70">{down}↓</span>
    </span>
  );
}

// ---- card -------------------------------------------------------------------

export function MarketMapCard({
  livePrices,
  livePricesUpdatedAt,
  casparPositions,
  sarahPositions,
  technicalScores,
}: {
  livePrices: Map<string, LivePriceRow>;
  livePricesUpdatedAt: string;
  casparPositions: PositionRow[];
  sarahPositions: PositionRow[];
  technicalScores: TechnicalScoreRow[];
}) {
  // No live feed yet (first deploy / fetch failure) → no card, no stub.
  if (livePrices.size === 0) return null;

  // Portfolio: union of both accounts' equity rows, weight = Σ|mkt_val|.
  // Caspar books USD, Sarah SGD — the raw sum is deliberately unconverted;
  // tile AREA only needs relative importance, not an FX-precise number.
  const weightByTicker = new Map<string, number>();
  for (const p of [...casparPositions, ...sarahPositions]) {
    const t = (p.ticker || "").trim().toUpperCase();
    if (!t) continue;
    weightByTicker.set(t, (weightByTicker.get(t) ?? 0) + Math.abs(numeric(p.mkt_val)));
  }

  const portfolio: Tile[] = [];
  for (const [ticker, weight] of weightByTicker) {
    const lp = livePrices.get(ticker);
    const pct = lp ? numericOrNull(lp.change_pct) : null;
    if (pct === null) continue; // no live price (or blank change) → skip tile
    portfolio.push({ ticker, pct, weight });
  }
  portfolio.sort((a, b) => b.weight - a.weight || a.ticker.localeCompare(b.ticker));

  // Watchlist: tech-scan universe minus anything already held. The live feed
  // currently covers portfolio tickers (plus lingering ex-holdings), so this
  // section self-prunes to whatever has a price — and hides when empty.
  const seen = new Set<string>();
  const watchlist: Tile[] = [];
  for (const row of technicalScores) {
    const t = (row.ticker || "").trim().toUpperCase();
    if (!t || weightByTicker.has(t) || seen.has(t)) continue;
    seen.add(t);
    const lp = livePrices.get(t);
    const pct = lp ? numericOrNull(lp.change_pct) : null;
    if (pct === null) continue;
    watchlist.push({ ticker: t, pct, weight: 0 });
  }
  watchlist.sort((a, b) => b.pct - a.pct); // green → red: breadth at a glance

  if (portfolio.length === 0 && watchlist.length === 0) return null;

  const ago = fmtAgo(livePricesUpdatedAt);

  return (
    <Card>
      {/* Header: title + feed freshness + colour legend */}
      <div className="flex items-center gap-2 mb-2.5">
        <LayoutGrid size={14} className="text-sky-400" />
        <span className="text-[length:var(--t-xs)] font-semibold text-slate-300 uppercase tracking-wide">
          Market Map
        </span>
        {ago.short && (
          <time
            className="text-[length:var(--t-2xs)] font-tabular"
            title={ago.full}
            style={{ color: ago.stale ? "#fbbf24" : "rgb(100 116 139)" }}
          >
            {ago.short}
          </time>
        )}
        <div className="ml-auto flex items-center gap-1">
          <span className="text-[length:var(--t-2xs)] font-tabular text-slate-600">−3%</span>
          <div
            className="h-1.5 w-10 rounded-full"
            style={{ background: "linear-gradient(to right, #dc2626, #0f172a, #16a34a)" }}
          />
          <span className="text-[length:var(--t-2xs)] font-tabular text-slate-600">+3%</span>
        </div>
      </div>

      {/* Portfolio mosaic — tile area ≈ position weight */}
      {portfolio.length > 0 && (
        <>
          <div className="flex items-center justify-between mb-1">
            <span className="label-caps">Portfolio</span>
            <Breadth tiles={portfolio} />
          </div>
          <div className="grid grid-cols-4 auto-rows-[44px] gap-1 grid-flow-dense">
            {portfolio.map((t, i) => (
              <TileBox key={t.ticker} tile={t} size={sizeFor(i)} />
            ))}
          </div>
        </>
      )}

      {/* Watchlist — uniform small tiles, sorted green → red */}
      {watchlist.length > 0 && (
        <>
          <div className={`flex items-center justify-between mb-1 ${portfolio.length > 0 ? "mt-3" : ""}`}>
            <span className="label-caps">Watchlist</span>
            <Breadth tiles={watchlist} />
          </div>
          <div className="grid grid-cols-4 auto-rows-[44px] gap-1">
            {watchlist.map((t) => (
              <TileBox key={t.ticker} tile={t} size="sm" />
            ))}
          </div>
        </>
      )}
    </Card>
  );
}
