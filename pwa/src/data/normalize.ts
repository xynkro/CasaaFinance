/**
 * data/normalize.ts — numeric coercion, row normalisation, and client-side
 * derivations over fetched rows.
 *
 * Split out of the original monolithic ``src/data.ts``. The public helpers
 * (numeric, numericOrNull, parseOcc, isOccOption, evaluateTrigger,
 * summarizeInsider, summarizeNews, indexLivePrices, lookupTvConsensusMap,
 * lookupRiskParity) are re-exported from ``../data`` so existing importers
 * keep resolving unchanged. ``normalizeSnapshot`` stays an internal helper
 * (consumed by data/dashboard.ts) and is intentionally NOT re-exported from
 * the barrel — it was not part of the original public surface either.
 */
import type {
  SnapshotRow,
  DecisionRow,
  ExposurePostureRow,
  TvConsensus,
  TvSignalRow,
  TriggerEvaluation,
  TriggerState,
  ParsedOcc,
  InsiderTransactionRow,
  InsiderSummary,
  NewsSentimentRow,
  NewsSummary,
  LivePriceRow,
  RiskParityAuditRow,
} from "./types";

// ---------- numeric coercion at the data boundary ----------

/**
 * Coerce a string|undefined sheet cell to a number with a stable fallback.
 * Replaces ad-hoc `Number(x) || 0` / `if (!v) continue` / unguarded `Number()`
 * patterns scattered across consumer cards.
 *
 * Rules:
 * - undefined/null/empty-string → fallback
 * - "NaN" / non-numeric strings → fallback
 * - Anything `Number()` parses successfully → that number (zero is preserved)
 *
 * Fallback default is 0; pass `null` if you need to distinguish "no data"
 * from "zero" (e.g. price-charts that should skip the point entirely).
 */
export function numeric(v: string | undefined | null, fallback = 0): number {
  if (v === undefined || v === null || v === "") return fallback;
  const n = Number(v);
  return Number.isNaN(n) ? fallback : n;
}

/**
 * Same as numeric() but returns null for missing/invalid — useful when
 * the consumer wants to filter the row out entirely rather than show 0.
 */
export function numericOrNull(v: string | undefined | null): number | null {
  if (v === undefined || v === null || v === "") return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

/**
 * Normalize snapshot rows from either account's CSV headers into the
 * generic SnapshotRow shape.  Caspar's sheet uses `net_liq_usd` / `cash`,
 * Sarah's uses `net_liq_sgd` / `cash_sgd` / `upl_sgd`, but the frontend
 * expects `net_liq` / `cash` / `upl` everywhere.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function normalizeSnapshot(rows: any[]): SnapshotRow[] {
  return rows.map((r) => ({
    date: r.date ?? "",
    net_liq: r.net_liq ?? r.net_liq_usd ?? r.net_liq_sgd ?? "0",
    cash: r.cash ?? r.cash_sgd ?? "0",
    upl: r.upl ?? r.upl_sgd ?? "0",
    upl_pct: r.upl_pct ?? "0",
  }));
}

// ---------- trigger evaluation ----------

/**
 * Derive a real-time trigger state from a decision row + live data.
 *
 * The brain writes a "watching" row with `entry` set to the price level
 * it wants to act at, and an `accumulation_plan` that may reference
 * regime gates (NEW_ENTRY_ALLOWED) or TV signal gates (TV daily=BUY).
 * This function compares live data against those gates so the PWA can
 * show "ACT NOW" the moment the conditions are met — instead of
 * waiting for the next WSR re-emission to flip status to pending.
 */
/**
 * Parse the gates JSON field on a decision row. Returns an empty array
 * for empty / malformed input (the evaluator then falls back to the
 * legacy accumulation_plan string parsing).
 */
function parseStructuredGates(gatesStr: string | undefined): string[] {
  if (!gatesStr) return [];
  try {
    const parsed = JSON.parse(gatesStr);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((g): g is string => typeof g === "string" && g.length > 0);
  } catch {
    return [];
  }
}

/**
 * Evaluate a single gate against live data. Returns a non-empty string
 * describing the block when the gate is NOT satisfied, or empty string
 * when it passes. Unknown gate types pass through with a "manual gate"
 * note so the user knows there's something to check.
 *
 * Recognised gate types:
 *   - exposure:<value>      e.g. "exposure:NEW_ENTRY_ALLOWED"
 *   - tv_daily:<value>      e.g. "tv_daily:BUY"   (matches BUY or STRONG_BUY)
 *   - tv_weekly:<value>     same shape as tv_daily
 *   - earnings_clear        no value; flagged manual (PWA doesn't have DTE-aware ticker map yet)
 *   - regime_above:<score>  not yet wired — passes with note
 */
function evaluateGate(
  gate: string,
  exposurePosture: ExposurePostureRow | null,
  tvConsensus: TvConsensus | undefined,
): string {
  const [rawType, ...rest] = gate.split(":");
  const type = (rawType || "").trim().toLowerCase();
  const required = rest.join(":").trim().toUpperCase();

  if (type === "exposure") {
    const rec = exposurePosture?.recommendation?.toUpperCase();
    if (!rec) return `exposure unknown, need ${required}`;
    if (rec !== required) return `exposure ${rec}, need ${required}`;
    return "";
  }
  if (type === "tv_daily") {
    const tvRec = (tvConsensus?.daily?.recommendation || "").toUpperCase();
    if (!tvRec) return `TV daily unknown, need ${required}`;
    // BUY required matches both BUY and STRONG_BUY; SELL matches both SELL forms.
    const ok = required === "BUY"
      ? tvRec.includes("BUY")
      : required === "SELL"
      ? tvRec.includes("SELL")
      : tvRec === required;
    return ok ? "" : `TV daily=${tvRec}, need ${required}`;
  }
  if (type === "tv_weekly") {
    const tvRec = (tvConsensus?.weekly?.recommendation || "").toUpperCase();
    if (!tvRec) return `TV weekly unknown, need ${required}`;
    const ok = required === "BUY"
      ? tvRec.includes("BUY")
      : required === "SELL"
      ? tvRec.includes("SELL")
      : tvRec === required;
    return ok ? "" : `TV weekly=${tvRec}, need ${required}`;
  }
  if (type === "earnings_clear") {
    // Brain has already filtered DTE conflicts at decision-emit time;
    // nothing to re-check client-side. Pass.
    return "";
  }
  // Unknown gate — surface as manual check instead of silently passing.
  return `manual gate: ${gate}`;
}

export function evaluateTrigger(
  decision: DecisionRow,
  currentPrice: number | undefined,
  exposurePosture: ExposurePostureRow | null,
  tvConsensus: TvConsensus | undefined,
): TriggerEvaluation {
  const empty: TriggerEvaluation = {
    state: "dormant",
    reason: "",
    blockingGates: [],
  };

  if ((decision.status || "").toLowerCase() !== "watching") return empty;

  const entry = Number(decision.entry);
  if (!entry || !currentPrice) return { ...empty, reason: "no price data" };

  const strategy = (decision.strategy || "").toUpperCase();
  // Direction: BUY_DIP / CSP / LONG_PUT-on-puts wait for the underlying
  // to drop to the entry level. TRIM / CC wait for it to rise.
  const isBuy = strategy === "BUY_DIP" || strategy === "CSP" || strategy === "PMCC";
  const isSell = strategy === "TRIM" || strategy === "CC";
  if (!isBuy && !isSell) return { ...empty, reason: "non-directional strategy" };

  // Signed distance: positive = trigger already crossed; negative = still away.
  const pctToTrigger = isBuy
    ? (currentPrice - entry) / entry        // BUY: need price ≤ entry → 0 or negative when triggered
    : (entry - currentPrice) / entry;       // SELL: need price ≥ entry → 0 or negative when triggered

  // Detect blocking gates. Prefer the structured `gates` JSON field
  // (Phase 6 — brain emits a list[str] like ["exposure:NEW_ENTRY_ALLOWED",
  // "tv_daily:BUY"]). Fall back to the legacy accumulation_plan string
  // includes for rows written before the gates column existed.
  const gates: string[] = [];
  const structuredGates = parseStructuredGates(decision.gates);

  if (structuredGates.length > 0) {
    for (const g of structuredGates) {
      const block = evaluateGate(g, exposurePosture, tvConsensus);
      if (block) gates.push(block);
    }
  } else {
    // Legacy fallback for pre-Phase-6 rows.
    const planLower = (decision.accumulation_plan || "").toLowerCase();
    if (
      planLower.includes("new_entry_allowed") ||
      planLower.includes("cash_priority blocks") ||
      planLower.includes("ceiling ≥") ||
      planLower.includes("exposure_ceiling")
    ) {
      const rec = exposurePosture?.recommendation;
      if (rec && rec !== "NEW_ENTRY_ALLOWED") {
        gates.push(`exposure ${rec}, need NEW_ENTRY_ALLOWED`);
      }
    }
    if (
      planLower.includes("tv daily=buy") ||
      planLower.includes("tv daily flips") ||
      planLower.includes("tv daily=str")
    ) {
      const tvRec = (tvConsensus?.daily?.recommendation || "").toUpperCase();
      if (tvRec && !tvRec.includes("BUY")) {
        gates.push(`TV daily=${tvRec}, need BUY`);
      }
    }
  }

  // State machine
  // - triggered: pctToTrigger ≤ 0  (price has crossed the trigger threshold)
  // - close:     pctToTrigger ≤ 0.03  (within 3% — getting interesting)
  // - dormant:   pctToTrigger > 0.03
  let state: TriggerState;
  if (pctToTrigger <= 0) {
    state = gates.length === 0 ? "act_now" : "ready";
  } else if (pctToTrigger <= 0.03) {
    state = "close";
  } else {
    state = "dormant";
  }

  const reason = (() => {
    const tag = isBuy ? "drop to" : "rise to";
    const pricePct = (Math.abs(pctToTrigger) * 100).toFixed(1);
    if (state === "act_now") {
      return `Trigger hit — ${isBuy ? "buy" : "trim"} at $${currentPrice.toFixed(2)} (entry $${entry.toFixed(2)})`;
    }
    if (state === "ready") {
      return `Trigger hit but gated: ${gates.join(" · ")}`;
    }
    if (state === "close") {
      return `${pricePct}% to ${tag} $${entry.toFixed(2)}`;
    }
    return `${pricePct}% from trigger $${entry.toFixed(2)}`;
  })();

  return {
    state,
    reason,
    triggerPrice: entry,
    currentPrice,
    pctToTrigger,
    blockingGates: gates,
  };
}

// ---------- OCC option symbol parsing ----------

const OCC_RE = /^([A-Z]{1,6})(\d{6})([CP])(\d{8})$/;

/** Parse an OCC option symbol → contract, or null if it's not an option. */
export function parseOcc(symbol: string): ParsedOcc | null {
  const m = OCC_RE.exec((symbol || "").toUpperCase());
  if (!m) return null;
  const [, root, yymmdd, right, strikeMilli] = m;
  return {
    underlying: root,
    expiry: `20${yymmdd.slice(0, 2)}-${yymmdd.slice(2, 4)}-${yymmdd.slice(4, 6)}`,
    right: right as "C" | "P",
    strike: Number(strikeMilli) / 1000,
  };
}

export function isOccOption(symbol: string): boolean {
  return OCC_RE.test((symbol || "").toUpperCase());
}

// ---------- per-ticker derivations / summaries ----------

export function summarizeInsider(
  rows: InsiderTransactionRow[],
  windowDays = 7,
): Map<string, InsiderSummary> {
  const out = new Map<string, InsiderSummary>();
  if (!rows.length) return out;
  const cutoff = new Date();
  cutoff.setUTCDate(cutoff.getUTCDate() - windowDays);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  for (const r of rows) {
    if (!r.ticker || (r.transaction_date || "") < cutoffStr) continue;
    const t = r.ticker.toUpperCase();
    const value = Number(r.value_usd) || 0;
    const side = (r.side || "").toLowerCase();
    let entry = out.get(t);
    if (!entry) {
      entry = {
        ticker: t, net_buy_value: 0, buy_count: 0, sell_count: 0,
        largest_value: 0, largest_name: "", latest_date: r.transaction_date,
      };
      out.set(t, entry);
    }
    if (side === "buy") {
      entry.net_buy_value += value;
      entry.buy_count += 1;
    } else if (side === "sell" || side === "issuer_sale") {
      entry.net_buy_value -= value;
      entry.sell_count += 1;
    }
    if (value > entry.largest_value) {
      entry.largest_value = value;
      entry.largest_name = r.name;
    }
    if ((r.transaction_date || "") > entry.latest_date) {
      entry.latest_date = r.transaction_date;
    }
  }
  return out;
}

export function summarizeNews(rows: NewsSentimentRow[]): Map<string, NewsSummary> {
  const out = new Map<string, NewsSummary>();
  if (!rows.length) return out;
  const now = new Date();
  const t24 = new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString().slice(0, 13);
  const t72 = new Date(now.getTime() - 72 * 60 * 60 * 1000).toISOString().slice(0, 13);
  for (const r of rows) {
    const t = (r.ticker || "").toUpperCase();
    if (!t) continue;
    const score = Number(r.sentiment_score) || 0;
    let entry = out.get(t);
    if (!entry) {
      entry = {
        ticker: t,
        latest_datetime: r.datetime,
        latest_headline: r.headline,
        latest_score: score,
        worst_score: score,
        best_score: score,
        count_24h: 0,
        count_72h: 0,
      };
      out.set(t, entry);
    }
    if ((r.datetime || "") > entry.latest_datetime) {
      entry.latest_datetime = r.datetime;
      entry.latest_headline = r.headline;
      entry.latest_score = score;
    }
    if (score < entry.worst_score) entry.worst_score = score;
    if (score > entry.best_score) entry.best_score = score;
    // crude time bucketing using ISO-prefix string compare
    const dtIso = r.datetime?.replace(/(\d{4}-\d{2}-\d{2})T(\d{2}).*/, "$1T$2");
    if (dtIso && dtIso >= t24) entry.count_24h += 1;
    if (dtIso && dtIso >= t72) entry.count_72h += 1;
  }
  return out;
}

/**
 * Build a ticker→LivePriceRow map for fast lookup. Empty/missing ticker
 * rows skipped. The map's `latest_updated_at` returns the most recent
 * timestamp across all rows (for the freshness chip).
 */
export function indexLivePrices(rows: LivePriceRow[]): {
  byTicker: Map<string, LivePriceRow>;
  latestUpdatedAt: string;
} {
  const byTicker = new Map<string, LivePriceRow>();
  let latestUpdatedAt = "";
  for (const r of rows) {
    const t = (r.ticker || "").toUpperCase();
    if (!t) continue;
    byTicker.set(t, r);
    if (r.updated_at && r.updated_at > latestUpdatedAt) {
      latestUpdatedAt = r.updated_at;
    }
  }
  return { byTicker, latestUpdatedAt };
}

/**
 * Build a per-ticker map: ticker -> { daily, weekly } using only the LATEST
 * row per (ticker, interval). The cron writes one row per ticker per day
 * per interval, so the latest row is the source of truth.
 */
export function lookupTvConsensusMap(rows: TvSignalRow[]): Map<string, TvConsensus> {
  const out = new Map<string, TvConsensus>();
  if (!rows.length) return out;
  // Group by (ticker, interval), keeping the row with the largest date.
  const latest = new Map<string, TvSignalRow>();
  for (const r of rows) {
    if (!r.ticker || !r.interval) continue;
    const key = `${r.ticker.toUpperCase()}|${r.interval}`;
    const prev = latest.get(key);
    if (!prev || (r.date ?? "") > (prev.date ?? "")) {
      latest.set(key, r);
    }
  }
  for (const [key, row] of latest) {
    const [ticker, interval] = key.split("|");
    if (!out.has(ticker)) out.set(ticker, {});
    const entry = out.get(ticker)!;
    if (interval === "1h") entry.hourly = row;
    else if (interval === "1d") entry.daily = row;
    else if (interval === "1W") entry.weekly = row;
  }
  return out;
}

/**
 * lookupRiskParity — group an audit-row list by account.
 *
 * Returns:
 *   - byClass:  Map<asset_class, RiskParityAuditRow> for the requested account
 *   - topOver:  rows where rebalance_action == OVERWEIGHT, sorted by
 *               delta_pct DESC (largest positive first), max 3
 *   - topUnder: rows where rebalance_action == UNDERWEIGHT, sorted by
 *               delta_pct ASC (most negative first), max 3
 *
 * The signals.ts helpers consume this to build the brain prompt's
 * `risk_parity` regime_anchor sub-object and the PWA card uses it for the
 * 8-bar layout. Empty input → empty maps + arrays.
 */
export function lookupRiskParity(
  account: string,
  rows: RiskParityAuditRow[],
): { byClass: Map<string, RiskParityAuditRow>; topOver: RiskParityAuditRow[]; topUnder: RiskParityAuditRow[] } {
  const accLower = account.toLowerCase();
  const byClass = new Map<string, RiskParityAuditRow>();
  const over: RiskParityAuditRow[] = [];
  const under: RiskParityAuditRow[] = [];

  for (const r of rows) {
    if ((r.account ?? "").toLowerCase() !== accLower) continue;
    if (r.asset_class && !byClass.has(r.asset_class)) byClass.set(r.asset_class, r);
    const action = (r.rebalance_action ?? "").toUpperCase();
    if (action === "OVERWEIGHT") over.push(r);
    else if (action === "UNDERWEIGHT") under.push(r);
  }

  over.sort((a, b) => numeric(b.delta_pct) - numeric(a.delta_pct));
  under.sort((a, b) => numeric(a.delta_pct) - numeric(b.delta_pct));

  return { byClass, topOver: over.slice(0, 3), topUnder: under.slice(0, 3) };
}
