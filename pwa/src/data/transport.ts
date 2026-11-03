/**
 * data/transport.ts — the Firestore read layer.
 *
 * Every tab lives in the private Firestore mirror behind Google sign-in. A tab's
 * sheet name is also its Firestore doc id.
 */

/** Prefetch every Firestore tab in ONE collection read so the per-tab fetches
 *  below hit memory instead of ~40 separate round-trips (the cellular slow-load
 *  fix). Best-effort: on failure the per-tab reads just go individually. */
export async function prefetchDashboard(): Promise<void> {
  const { prefetchAllTabs } = await import("../lib/firebase");
  await prefetchAllTabs();
}

export async function fetchTab<T>(tab: string): Promise<T[]> {
  const { readFirestoreTab } = await import("../lib/firebase");
  return readFirestoreTab<T>(tab);
}

/** Same as fetchTab; kept as its own name for callers that read optional tabs. */
export const fetchTabByName = fetchTab;
