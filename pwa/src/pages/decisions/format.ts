/**
 * decisions/format.ts — shared formatters, strategy constants, the status-sort
 * helpers, and the live-price resolver used across the Decisions page
 * sub-components.
 *
 * Split out of the original monolithic ``DecisionsPage.tsx`` so the card,
 * tab-bar, and page shell can share one source of truth without circular
 * imports. Pure helpers — no JSX.
 */
import type { PositionRow, TechnicalScoreRow, LivePriceRow } from "../../data";

export const OPTIONS_STRATEGIES = ["CSP", "CC", "PMCC", "LONG_CALL", "LONG_PUT"];

export function fmtMoney(v: string | number | undefined): string {
  if (v === undefined || v === "") return "—";
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/**
 * Mantissa-aware money formatter for sub-cent option premiums.
 * Below $0.10 we render 4 decimals so $0.0095 doesn't get rounded to $0.01.
 */
export function fmtMoneyMantissa(v: string | number | undefined): string {
  if (v === undefined || v === "") return "—";
  const n = Number(v);
  if (isNaN(n)) return "—";
  if (n > 0 && n < 0.1) {
    return `$${n.toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;
  }
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function fmtPct(v: string | number | undefined): string {
  if (v === undefined || v === "") return "—";
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `${n.toFixed(1)}%`;
}

// Sort key: pending → watching → filled → killed/expired → unknown
const STATUS_SORT_RANK: Record<string, number> = {
  pending: 0,
  watching: 1,
  filled: 2,
  killed: 3,
  expired: 3,
};

export function statusSortKey(status: string | undefined): number {
  return STATUS_SORT_RANK[(status ?? "").toLowerCase()] ?? 4;
}

export type AccountTab = "caspar" | "sarah";
export type SubTab = "all" | "options" | "stocks";

/**
 * Resolve the live current price for a decision ticker. Priority order
 * matches the freshness of each feed:
 *
 *   1. live_prices    (TV scanner, 5-min refresh — freshest)
 *   2. positions      (yahoo-grab, 15-min refresh — only held tickers)
 *   3. technical_scores (daily close — fallback for non-portfolio names)
 *
 * Before live_prices was wired here, the trigger evaluator could be 15 min
 * stale (positions cron) which made "ACT NOW" lag the actual price cross.
 * Now it lags 5 min at most — same as the underlying feed.
 *
 * Returns undefined if the ticker isn't anywhere — overlay then renders nothing.
 */
export function lookupCurrentPrice(
  ticker: string,
  casparPositions: PositionRow[],
  sarahPositions: PositionRow[],
  technicalScores: TechnicalScoreRow[],
  livePrices: Map<string, LivePriceRow>,
): number | undefined {
  if (!ticker) return undefined;
  const t = ticker.toUpperCase();

  // 1. Live prices — freshest source we have (5-min cron)
  const live = livePrices.get(t);
  if (live) {
    const n = Number(live.last);
    if (!isNaN(n) && n > 0) return n;
  }

  // 2. Position rows (yahoo-grab, 15-min)
  const fromPos = (rows: PositionRow[]) => rows.find((r) => r.ticker?.toUpperCase() === t);
  const cas = fromPos(casparPositions);
  if (cas) {
    const n = Number(cas.last);
    if (!isNaN(n) && n > 0) return n;
  }
  const sar = fromPos(sarahPositions);
  if (sar) {
    const n = Number(sar.last);
    if (!isNaN(n) && n > 0) return n;
  }

  // 3. Technical scores (daily close)
  const tech = technicalScores.find((r) => r.ticker?.toUpperCase() === t);
  if (tech) {
    const n = Number(tech.close);
    if (!isNaN(n) && n > 0) return n;
  }
  return undefined;
}
