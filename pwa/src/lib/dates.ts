/**
 * Canonical date helpers — formerly duplicated 6× across modals/pages/cards.
 *
 * Two formats supported (matching what the prior copy-paste copies emitted):
 *   - shortDate("2026-04-30")       → "Apr 30"          (HistoryPage / ClosedDecisionsCard)
 *   - shortDateLong("2026-04-30")   → "30 Apr 2026"     (Archive/Brief/Wsr/Lite modals)
 *
 * Both accept any ISO-ish string and slice the first 10 chars (YYYY-MM-DD)
 * before parsing — so "2026-04-30T15:23:00Z" works the same as "2026-04-30".
 */
const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Apr 30" — used by chart axes and compact list rows. */
export function shortDate(d: string): string {
  const s = d.slice(0, 10);
  const [, m, day] = s.split("-");
  if (!m || !day) return s;
  return `${MONTHS[Number(m)]} ${Number(day)}`;
}

/** "30 Apr 2026" — used by modal headers / archive rows where the year matters. */
export function shortDateLong(d: string): string {
  const s = d.slice(0, 10);
  const [y, m, day] = s.split("-");
  if (!y || !m || !day) return s;
  return `${Number(day)} ${MONTHS[Number(m)]} ${y}`;
}

/**
 * Canonical option-expiry formatter — formerly duplicated 5× across cards/pages
 * with three divergent output formats. Each prior copy is reproduced exactly via
 * `opts`, so no rendered string changes.
 *
 * Accepts both wire formats the backend emits:
 *   - "YYYY-MM-DD"  (parseOcc output, scan rows)
 *   - "YYYYMMDD"    (8-digit, raw scan / decision rows)
 *
 * Output styles:
 *   - "monDay" (default) → "Apr 30"   — HarvestPicksCard, ScanResultsCard,
 *                                        PaperTradingView, UoaFlowCard
 *   - "slash"            → "04/30"     — DecisionsPage
 *
 * `empty` is the placeholder for falsy/empty input (the prior copies disagreed:
 * some returned "—", some returned ""). Unparseable-but-non-empty input is
 * returned verbatim, matching every prior copy.
 */
const FMT_EXPIRY_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export interface FmtExpiryOpts {
  /** Output format. Default "monDay" ("Apr 30"). "slash" → "04/30". */
  style?: "monDay" | "slash";
  /** Placeholder for falsy/empty input. Default "" (some call sites use "—"). */
  empty?: string;
  /**
   * Parsing-fidelity flags. The five prior copies diverged on edge inputs;
   * these reproduce each one BYTE-FOR-BYTE so no rendered string can change.
   * Defaults match the strictest/most-complete copy (HarvestPicks/ScanResults).
   */
  /** Accept 8-digit "YYYYMMDD" in monDay style. Default true. (false → paper/uoa) */
  accept8?: boolean;
  /** monDay: require the dash form to split into EXACTLY 3 parts. Default false. (true → uoa) */
  strict3?: boolean;
  /** monDay: reject a falsy/zero year (`!y`). Default true. (false → paper/uoa) */
  requireYear?: boolean;
  /** monDay: reject months outside 1..12. Default true. (false → paper) */
  requireMonthRange?: boolean;
}

export function fmtExpiry(raw: string | undefined, opts: FmtExpiryOpts = {}): string {
  const {
    style = "monDay",
    empty = "",
    accept8 = true,
    strict3 = false,
    requireYear = true,
    requireMonthRange = true,
  } = opts;
  if (!raw) return empty;

  // "slash" mirrors DecisionsPage exactly: ONLY 8-digit numeric "YYYYMMDD" is
  // reformatted (string slices, no numeric parse); everything else — including
  // already-dashed "YYYY-MM-DD" — is returned verbatim.
  if (style === "slash") {
    if (raw.length === 8 && /^\d+$/.test(raw)) {
      return `${raw.slice(4, 6)}/${raw.slice(6, 8)}`;
    }
    return raw;
  }

  // "monDay": parse year/month/day from "YYYY-MM-DD" (and "YYYYMMDD" if accept8).
  // Anything else is returned verbatim, matching every prior copy.
  let y: number, m: number, d: number;
  if (raw.includes("-")) {
    const parts = raw.split("-").map(Number);
    if (strict3 && parts.length !== 3) return raw;
    [y, m, d] = parts;
  } else if (accept8 && raw.length === 8 && /^\d+$/.test(raw)) {
    y = Number(raw.slice(0, 4));
    m = Number(raw.slice(4, 6));
    d = Number(raw.slice(6, 8));
  } else {
    return raw;
  }
  if ((requireYear && !y) || !m || !d || (requireMonthRange && (m < 1 || m > 12))) {
    return raw;
  }
  // 1-indexed month table: FMT_EXPIRY_MONTHS[m] === SHORT_MONTHS[m-1]. When the
  // month-range check is disabled (paper) an out-of-range m yields "undefined",
  // exactly as the prior `SHORT_MONTHS[m-1]` did.
  return `${FMT_EXPIRY_MONTHS[m]} ${d}`;
}

/**
 * Whole-day difference between today (local) and the given ISO-ish date.
 *
 * Accepts any string whose first 10 characters parse as YYYY-MM-DD — the
 * brain emits timestamps like "2026-05-04T202524" (no colons), so we slice
 * before parsing rather than handing the raw string to `new Date`.
 *
 * Returns a non-negative integer:
 *   - 0  → today (or future date — we don't bother distinguishing)
 *   - 1  → yesterday
 *   - 7  → one week ago
 *
 * Used by the Decisions tab age chip to flag stale brain prose.
 */
export function daysAgo(iso: string): number {
  const s = (iso ?? "").slice(0, 10);
  const [y, m, day] = s.split("-");
  if (!y || !m || !day) return 0;
  const then = new Date(Number(y), Number(m) - 1, Number(day));
  const now = new Date();
  // Zero out the time-of-day on `now` so partial days don't tip the count.
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diffMs = today.getTime() - then.getTime();
  if (diffMs <= 0) return 0;
  return Math.floor(diffMs / 86_400_000);
}
