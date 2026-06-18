/**
 * dashboardCache — stale-while-revalidate persistence for the dashboard.
 *
 * Killing the service worker (to end the second-load spinner) removed ALL
 * caching, so every cold open re-fetched all 41 Firestore docs before the app
 * could show anything — the "takes ages after closing it" report. This caches
 * the last good DashboardData in localStorage so a reopen paints instantly
 * from cache, then refreshes in the background.
 *
 * DashboardData carries several Map fields (livePrices, tvSignals,
 * *ByTicker) that plain JSON would silently flatten to {} — so we round-trip
 * Maps as tagged entry arrays.
 */
import type { DashboardData } from "../data";

const KEY = "casaa_dashboard_cache_v1";

function replacer(_k: string, v: unknown): unknown {
  return v instanceof Map ? { __map: [...v.entries()] } : v;
}

function reviver(_k: string, v: unknown): unknown {
  if (v && typeof v === "object" && Array.isArray((v as { __map?: unknown }).__map)) {
    return new Map((v as { __map: [unknown, unknown][] }).__map);
  }
  return v;
}

/** Last good dashboard, or null (no cache / corrupt / schema drift). */
export function readDashboardCache(): DashboardData | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    return JSON.parse(raw, reviver) as DashboardData;
  } catch {
    return null;
  }
}

export function writeDashboardCache(data: DashboardData): void {
  try {
    // Never cache an error payload — it would pin a broken/empty view on the
    // next reopen. Only successful fetches are worth re-showing.
    if (data?.error) return;
    localStorage.setItem(KEY, JSON.stringify(data, replacer));
  } catch {
    // QuotaExceeded / serialization failure → skip silently. The app still
    // works from the live fetch; it just loses the instant-reopen win.
  }
}
