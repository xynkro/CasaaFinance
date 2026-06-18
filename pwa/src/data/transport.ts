/**
 * data/transport.ts — the sheet/Firestore fetch layer.
 *
 * Owns the Google Sheet identity (SHEET_ID + per-tab GIDs), the two CSV URL
 * builders, the data-source flag, and the two generic fetchers (fetchTab by
 * GID, fetchTabByName by sheet name) including the Firestore branch.
 *
 * Split out of the original monolithic ``src/data.ts``. ``fetchTab`` and
 * ``fetchTabByName`` are re-exported from ``../data`` so existing importers
 * keep resolving unchanged.
 */
import Papa from "papaparse";

const SHEET_ID = "1N2AAx1GqTi23Qlq6MZkQoYfQOY7An1K0vvPx65YBiQc";

export function csvUrl(gid: string): string {
  return `https://docs.google.com/spreadsheets/d/${SHEET_ID}/gviz/tq?tqx=out:csv&gid=${gid}`;
}

/** Fetch by sheet name instead of GID — for tabs whose GID isn't known. */
export function csvUrlByName(sheetName: string): string {
  return `https://docs.google.com/spreadsheets/d/${SHEET_ID}/gviz/tq?tqx=out:csv&sheet=${encodeURIComponent(sheetName)}`;
}

export const GIDS: Record<string, string> = {
  daily_brief_latest: "1490893125",
  snapshot_caspar: "1233934747",
  snapshot_sarah: "1953218382",
  positions_caspar: "981534946",
  positions_sarah: "444641294",
  decision_queue: "1744723757",
  options: "326503132",
  technical_scores: "657341624",
  wheel_next_leg: "805863395",
  exit_plans: "515412556",
  options_defense: "1717646002",
  wsr_summary: "607663282",
  macro: "447436838",
  wsr_archive: "1065773181",
  // Quant regime layer — populated by regime-signals.yml daily 22:00 UTC.
  // regime_signals: market_breadth + ftd + distribution_day + macro_regime
  // exposure_posture: exposure-coach output (ceiling, recommendation, headroom)
  regime_signals: "1037039714",
  exposure_posture: "1572953132",
  // screen_candidates created on first Sunday cron run — placeholder until then.
  screen_candidates: "1773922612",
  // TradingView 26-indicator consensus, populated daily by tv-signals.yml.
  // One row per (ticker, interval) — both 1d and 1W. The DecisionCard reads
  // the latest 1d + 1W row per ticker for the consensus chip.
  tv_signals: "1954107259",
  // Risk Parity LITE — diversification hygiene audit. Written daily at
  // 22:45 UTC by risk-parity-audit.yml. 8 asset classes × 2 accounts =
  // 16 rows per run. Live GID resolved via gspread on 2026-05-07.
  risk_parity_audit: "1398209766",
  // Live price feed — written every 5 min by tv-prices.yml using
  // TradingView's public scanner endpoint. UPSERT semantics, one row
  // per portfolio ticker. PWA Portfolio overlays this on positions for
  // near-realtime mkt_val/UPL display.
  live_prices: "666282627",
  // Finnhub-powered tabs (Phase 1-3 of Strategy reliability rollout).
  // earnings_calendar: per (ticker, year, quarter) UPSERT, 30-day
  //   lookahead, filtered to portfolio + watchlist (~84 tickers). Drives
  //   the Earnings badge on Decision cards + "This week" Home widget.
  // economic_calendar: medium+high impact macro events for next 14
  //   days, US/EU/CN/JP/SG only. Drives "Macro this week" Home widget.
  // news_sentiment: company-news rows last 14 days per ticker with
  //   heuristic sentiment score. Drives the news dot on Decision cards.
  // insider_transactions: SEC Form 4 filings last 90 days per ticker.
  //   Drives the insider flow icon when last 7d net is meaningful.
  // analyst_consensus: latest Wall Street recommendation distribution
  //   per ticker. Drives the analyst chip on Decision cards.
  earnings_calendar: "1062081514",
  economic_calendar: "1783608533",
  news_sentiment: "1115837697",
  insider_transactions: "511704782",
  analyst_consensus: "991986564",
  // Anthropic API usage + cost log per brain run. Populated by
  // scripts/api_usage_scrape.py parsing claude-code-action's result
  // JSON. Settings tab renders MTD spend + per-workflow breakdown.
  api_usage: "1292394805",
  gov_confluence_signals: "1590812475",
  congress_trades: "870416250",
  snapshot_alpaca: "2094087184",
  positions_alpaca: "1331088115",
  harvest_scan: "1619087431",
  iv_surface_scan: "1665887293",
};

// Data source flag. 'gviz' (default) = public Google Sheet CSV; 'firestore'
// = private Firestore mirror behind Google sign-in. Anything other than the
// exact string 'firestore' falls back to gviz so the public path keeps
// working until cutover. firebase.ts is loaded via dynamic import ONLY in
// firestore mode, so the gviz default never pulls in (or initialises) the
// Firebase SDK.
const DATA_SOURCE = import.meta.env.VITE_DATA_SOURCE;
const USE_FIRESTORE = DATA_SOURCE === "firestore";

/** Prefetch every Firestore tab in ONE collection read so the per-tab fetches
 *  below hit memory instead of ~40 separate round-trips (the cellular slow-load
 *  fix). No-op in gviz mode. Best-effort: on failure the per-tab reads just go
 *  individually as before. */
export async function prefetchDashboard(): Promise<void> {
  if (!USE_FIRESTORE) return;
  const { prefetchAllTabs } = await import("../lib/firebase");
  await prefetchAllTabs();
}

export async function fetchTab<T>(tab: keyof typeof GIDS): Promise<T[]> {
  // fetchTab's key IS the sheet tab name (= Firestore doc id), so it maps
  // straight onto the mirror doc.
  if (USE_FIRESTORE) {
    const { readFirestoreTab } = await import("../lib/firebase");
    return readFirestoreTab<T>(tab as string);
  }
  const res = await fetch(csvUrl(GIDS[tab]));
  if (!res.ok) throw new Error(`Sheet fetch failed: ${tab} (${res.status})`);
  const text = await res.text();
  const { data } = Papa.parse<T>(text, { header: true, skipEmptyLines: true });
  return data;
}

/** Fetch a tab by sheet name (for tabs without a known GID). */
export async function fetchTabByName<T>(sheetName: string): Promise<T[]> {
  // The sheet name is also the Firestore doc id under the mirror contract.
  if (USE_FIRESTORE) {
    const { readFirestoreTab } = await import("../lib/firebase");
    return readFirestoreTab<T>(sheetName);
  }
  const res = await fetch(csvUrlByName(sheetName));
  if (!res.ok) throw new Error(`Sheet fetch failed: ${sheetName} (${res.status})`);
  const text = await res.text();
  const { data } = Papa.parse<T>(text, { header: true, skipEmptyLines: true });
  return data;
}
