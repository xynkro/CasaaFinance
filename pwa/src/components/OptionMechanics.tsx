/**
 * OptionMechanics — the four wheel-mechanics numbers, computed client-side and
 * rendered as ONE compact chip strip on every SHORT option row (UI audit #3).
 *
 * The trading rules ("close at 50% profit", "act at 21 DTE", "defend near the
 * short strike", "know the max loss") lived in glossary prose and backend
 * sheets while the rows showed none of the four numbers — or showed them with
 * wrong thresholds (WheelCard ambered DTE only at ≤7). This strip is the one
 * formula, one component fix:
 *
 *   captured%   = (credit − last) / credit   — emerald + "50% rule" at ≥50
 *   DTE pill    — amber at ≤21 ("21d rule"), red at ≤7
 *   dist-strike = signed by right: P → (u−k)/u, C → (k−u)/u
 *                 amber ≤5%, red ≤2% or breached (ITM)
 *   max loss    = (strike − credit) × 100 × |qty|  (CSP only)
 *                 covered calls show credit kept instead — no naked max-loss math
 *
 * Every chip degrades independently: a blank input renders NO chip for that
 * number (never NaN, never a fabricated 0). Inputs are plain numbers — call
 * sites convert sheet strings via `numOrUndef` so blank ≠ zero.
 */
import { Chip, CHIP_TONE as TONE } from "./ui";

// Hardcoded mechanics thresholds — deliberately NOT user-configurable
// (post-mortem rule: the numbers that were paid for in losses don't drift).
export const PROFIT_TARGET_PCT = 50; // close-at-50%-profit rule
export const DTE_ACT = 21;           // act-at-21-DTE rule
export const DTE_URGENT = 7;
export const STRIKE_WARN_PCT = 5;    // cushion to short strike — amber
export const STRIKE_DANGER_PCT = 2;  // cushion to short strike — red

/** Sheet-string → number, where blank/garbage means MISSING (not 0). */
export function numOrUndef(v: string | number | undefined | null): number | undefined {
  if (v === undefined || v === null || v === "") return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

/**
 * Shared DTE color class for row headers — red ≤7, amber ≤21 (the 21d rule),
 * slate otherwise. WheelCard previously ambered only at ≤7, two weeks past
 * the mechanical action point.
 */
export function dteClass(dte: number | undefined): string {
  if (dte === undefined || dte < 0) return "text-slate-500";
  if (dte <= DTE_URGENT) return "text-red-400 font-bold";
  if (dte <= DTE_ACT) return "text-amber-400 font-bold";
  return "text-slate-500";
}

/** Days-to-expiry from a wire expiry ("YYYYMMDD" or "YYYY-MM-DD"). */
export function dteFromExpiry(expiry?: string): number | undefined {
  if (!expiry) return undefined;
  const digits = expiry.slice(0, 10).replace(/-/g, "");
  if (!/^\d{8}$/.test(digits)) return undefined;
  const y = Number(digits.slice(0, 4));
  const m = Number(digits.slice(4, 6));
  const d = Number(digits.slice(6, 8));
  if (!y || m < 1 || m > 12 || !d) return undefined;
  const exp = new Date(y, m - 1, d);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((exp.getTime() - today.getTime()) / 86_400_000);
}

/** Compact money: $18.9k / $450. */
function fmtUsd(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1000) return `$${(abs / 1000).toFixed(1)}k`;
  return `$${abs.toFixed(0)}`;
}

export function OptionMechanics({
  credit,
  last,
  dte,
  strike,
  underlying,
  right,
  qty,
  leg,
  className = "",
}: {
  /** Premium per share received (sign ignored). */
  credit?: number;
  /** Current option price per share (sign ignored). undefined = no quote → no captured chip. */
  last?: number;
  dte?: number;
  strike?: number;
  underlying?: number;
  /** "P" | "C" — signs the distance-to-strike. */
  right?: string;
  /** Contracts (sign ignored; missing/0 → 1). */
  qty?: number;
  /** "CSP" → max-loss chip; "CC" → credit-kept chip; anything else → neither. */
  leg?: string;
  className?: string;
}) {
  const chips: React.ReactNode[] = [];
  const cr = credit !== undefined ? Math.abs(credit) : undefined;
  const px = last !== undefined ? Math.abs(last) : undefined;
  const contracts = Math.max(1, Math.abs(qty ?? 1));
  const r = (right ?? "").toUpperCase();

  // 1 — captured % (the close-at-50% rule). Clamped at 0 below; can exceed 100
  // on dirty data rather than lying by capping.
  if (cr !== undefined && cr > 0 && px !== undefined) {
    const raw = ((cr - px) / cr) * 100;
    const pct = Math.max(0, raw);
    const hit = pct >= PROFIT_TARGET_PCT;
    chips.push(
      <Chip key="capt" tone="bold" tabular className={`border ${hit ? TONE.emerald : TONE.slate}`}>
        {pct.toFixed(0)}% capt{hit ? " · 50% rule" : ""}
      </Chip>,
    );
  }

  // 2 — DTE pill (the act-at-21-DTE rule).
  if (dte !== undefined && dte >= 0) {
    const tone = dte <= DTE_URGENT ? TONE.red : dte <= DTE_ACT ? TONE.amber : TONE.slate;
    chips.push(
      <Chip key="dte" tone="bold" tabular className={`border ${tone}`}>
        {dte}d{dte <= DTE_ACT ? " · 21d rule" : " DTE"}
      </Chip>,
    );
  }

  // 3 — distance to short strike, signed by right (defend trigger).
  if (strike !== undefined && strike > 0 && underlying !== undefined && underlying > 0 && (r === "P" || r === "C")) {
    const dist = (r === "P" ? underlying - strike : strike - underlying) / underlying * 100;
    const breached = dist <= 0;
    const tone = dist <= STRIKE_DANGER_PCT ? TONE.red : dist <= STRIKE_WARN_PCT ? TONE.amber : TONE.slate;
    chips.push(
      <Chip key="dist" tone="bold" tabular className={`border ${tone}`}>
        {breached ? `strike breached ${Math.abs(dist).toFixed(1)}%` : `${dist.toFixed(1)}% to strike`}
      </Chip>,
    );
  }

  // 4 — max loss (CSP) / credit kept (CC). No naked max-loss math for calls.
  if (leg === "CSP" && strike !== undefined && strike > 0 && cr !== undefined) {
    const maxLoss = (strike - cr) * 100 * contracts;
    if (maxLoss > 0) {
      chips.push(
        <Chip key="risk" tabular className={`border ${TONE.slate}`}>
          max loss {fmtUsd(maxLoss)}
        </Chip>,
      );
    }
  } else if (leg === "CC" && cr !== undefined && cr > 0) {
    chips.push(
      <Chip key="risk" tabular className={`border ${TONE.slate}`}>
        credit kept {fmtUsd(cr * 100 * contracts)}
      </Chip>,
    );
  }

  if (!chips.length) return null;
  return <div className={`flex items-center flex-wrap gap-1 ${className}`}>{chips}</div>;
}
