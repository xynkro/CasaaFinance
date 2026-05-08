/**
 * Local-only decision action journal.
 *
 * The brain emits decision rows weekly (WSR Full) and re-emits mid-week
 * (WSR Lite). Until this module landed, there was no way to record
 * what the user actually DID in response — filled? killed? deferred?
 * The PWA has read-only access to Sheets (gviz CSV), so we journal
 * actions in localStorage and join client-side at render time.
 *
 * v1 scope:
 *   - Mark Filled (with fill_price + qty)
 *   - Mark Killed
 *   - Mark Deferred
 *   - Undo any of the above
 *   - Surface in Decisions cards (status badge)
 *   - Surface in Review › Journal (running P&L)
 *
 * v2 (later):
 *   - Sync to Sheets via a write endpoint (Apps Script Web App or
 *     Cloudflare Worker) so actions persist across devices.
 *   - Per-decision running P&L tracker → hit-rate dashboard.
 *
 * Storage key: `casaa_decision_actions_v1`. Bumped if the shape changes.
 */
import type { DecisionRow } from "../data";

const STORAGE_KEY = "casaa_decision_actions_v1";

export type DecisionActionType = "filled" | "killed" | "deferred";

export interface DecisionAction {
  /** Compound key: `<decisionDate>|<account>|<ticker>|<strategy>|<strike>` */
  decisionKey: string;
  ticker: string;
  account: string;
  strategy: string;
  decisionDate: string;          // YYYY-MM-DD (no audit suffix)
  action: DecisionActionType;
  fillPrice?: number;
  qty?: number;
  notes?: string;
  recordedAt: string;            // ISO timestamp
}

/**
 * Build the compound key for a decision row. Mirrors the upsert key
 * used by `scripts/push_decisions.py`'s `_decision_key()` so a journal
 * action persists across re-emissions of the SAME row (status flip
 * from pending→watching, refreshed thesis text, etc.).
 *
 * Strike is normalised to 2 dp to match the Python side.
 */
export function keyForDecision(d: Pick<DecisionRow, "date" | "account" | "ticker" | "strategy" | "strike">): string {
  const date = (d.date || "").slice(0, 10);
  const account = (d.account || "").toLowerCase();
  const ticker = (d.ticker || "").toUpperCase();
  const strategy = (d.strategy || "").toUpperCase();
  const strikeNum = Number(d.strike);
  const strikeStr = Number.isFinite(strikeNum) && strikeNum !== 0
    ? strikeNum.toFixed(2)
    : "0.00";
  return `${date}|${account}|${ticker}|${strategy}|${strikeStr}`;
}

/**
 * Read all actions from localStorage. Returns an empty map if the
 * storage is missing, malformed, or unavailable (private mode).
 */
export function getActions(): Map<string, DecisionAction> {
  const out = new Map<string, DecisionAction>();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return out;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return out;
    for (const a of parsed) {
      if (a && typeof a.decisionKey === "string" && typeof a.action === "string") {
        out.set(a.decisionKey, a as DecisionAction);
      }
    }
  } catch {
    // ignore — storage disabled / corrupt
  }
  return out;
}

function persist(actions: Map<string, DecisionAction>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...actions.values()]));
  } catch {
    // ignore — quota / disabled
  }
}

/**
 * Upsert a new action (replaces any existing action for the same
 * decision). Returns the updated map so callers can re-render.
 */
export function setAction(action: DecisionAction): Map<string, DecisionAction> {
  const all = getActions();
  all.set(action.decisionKey, action);
  persist(all);
  return all;
}

/** Remove the action for a given key. */
export function clearAction(key: string): Map<string, DecisionAction> {
  const all = getActions();
  all.delete(key);
  persist(all);
  return all;
}

/** Convenience: build + store a Filled action. */
export function markFilled(
  d: Pick<DecisionRow, "date" | "account" | "ticker" | "strategy" | "strike">,
  fillPrice: number,
  qty: number,
  notes?: string,
): Map<string, DecisionAction> {
  return setAction({
    decisionKey: keyForDecision(d),
    ticker: (d.ticker || "").toUpperCase(),
    account: (d.account || "").toLowerCase(),
    strategy: (d.strategy || "").toUpperCase(),
    decisionDate: (d.date || "").slice(0, 10),
    action: "filled",
    fillPrice,
    qty,
    notes,
    recordedAt: new Date().toISOString(),
  });
}

/** Convenience: build + store a Killed action. */
export function markKilled(
  d: Pick<DecisionRow, "date" | "account" | "ticker" | "strategy" | "strike">,
  notes?: string,
): Map<string, DecisionAction> {
  return setAction({
    decisionKey: keyForDecision(d),
    ticker: (d.ticker || "").toUpperCase(),
    account: (d.account || "").toLowerCase(),
    strategy: (d.strategy || "").toUpperCase(),
    decisionDate: (d.date || "").slice(0, 10),
    action: "killed",
    notes,
    recordedAt: new Date().toISOString(),
  });
}

/** Convenience: build + store a Deferred action. */
export function markDeferred(
  d: Pick<DecisionRow, "date" | "account" | "ticker" | "strategy" | "strike">,
  notes?: string,
): Map<string, DecisionAction> {
  return setAction({
    decisionKey: keyForDecision(d),
    ticker: (d.ticker || "").toUpperCase(),
    account: (d.account || "").toLowerCase(),
    strategy: (d.strategy || "").toUpperCase(),
    decisionDate: (d.date || "").slice(0, 10),
    action: "deferred",
    notes,
    recordedAt: new Date().toISOString(),
  });
}

/**
 * P&L for a filled action against a current price. Returns null if
 * the action isn't a fill or if we don't have enough info to compute
 * a P&L (no fill_price, no qty, or no current price).
 *
 * Sign convention: positive = winning, negative = losing. For TRIM /
 * CC (sell-side) entries, callers should flip the sign — caller decides
 * directionality based on `decision.strategy`.
 */
export function fillPnl(
  action: DecisionAction,
  currentPrice: number | undefined,
): { absUsd: number; pct: number } | null {
  if (action.action !== "filled") return null;
  const fp = action.fillPrice;
  const qty = action.qty;
  if (!fp || !qty || !currentPrice || fp <= 0) return null;
  const absUsd = (currentPrice - fp) * qty;
  const pct = ((currentPrice - fp) / fp) * 100;
  return { absUsd, pct };
}
