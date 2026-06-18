/**
 * RegimeStamp — "is today a day I'm even allowed to put this trade on?"
 * (UI audit #5, the explicit post-mortem requirement: regime state wherever
 * recs appear.)
 *
 * One compact chip-row composing the three gate vocabularies that previously
 * lived on three different pages (or nowhere):
 *
 *   exposurePosture.recommendation — red CASH_PRIORITY / amber REDUCE_ONLY /
 *                                    green NEW_ENTRY_ALLOWED, + ceiling %
 *   gexRegime premium gate         — amber SELL_CAUTION / green SELL_OK
 *                                    (most conservative row wins)
 *   scanMeta.regime                — STANDARD / CAUTION / HALTED
 *                                    (previously displayed NOWHERE)
 *
 * Mounted INSIDE every rec-rendering card (DecisionCard, TodaysPlanCard,
 * HarvestPicksCard, ScanResultsCard, TopCandidatesCard) — one stamp per card,
 * so a pending CSP visibly differs between NEW_ENTRY_ALLOWED and
 * CASH_PRIORITY days. Renders null when none of the three feeds has data.
 */
import type { ExposurePostureRow, GexRegimeRow, ScanMetaRow } from "../data";
import { Chip, CHIP_TONE as TONE } from "./ui";

const POSTURE_CFG: Record<string, { cls: string; label: string }> = {
  CASH_PRIORITY: { cls: TONE.red, label: "CASH PRIORITY" },
  REDUCE_ONLY: { cls: TONE.amber, label: "REDUCE ONLY" },
  NEW_ENTRY_ALLOWED: { cls: TONE.emerald, label: "NEW ENTRY OK" },
};

const SCAN_CFG: Record<string, { cls: string; label: string }> = {
  STANDARD: { cls: TONE.slate, label: "SCAN STANDARD" },
  CAUTION: { cls: TONE.amber, label: "SCAN CAUTION" },
  HALTED: { cls: TONE.red, label: "SCAN HALTED" },
};

/** Most conservative premium gate across the index rows (SPY + QQQ). */
function premiumGate(gexRegime?: GexRegimeRow[] | null): "SELL_CAUTION" | "SELL_OK" | null {
  const gates = (gexRegime ?? []).map((r) => (r.premium_gate ?? "").toUpperCase());
  if (gates.includes("SELL_CAUTION")) return "SELL_CAUTION";
  if (gates.includes("SELL_OK")) return "SELL_OK";
  return null;
}

/**
 * Named gates currently suppressing new premium/entries — drives the
 * "recs are gated, not a quiet scan" honesty copy (mirrors the Telegram 🔇
 * banner: "Standing down ... is the discipline, not a glitch").
 */
export function suppressionReasons(
  posture?: ExposurePostureRow | null,
  gexRegime?: GexRegimeRow[] | null,
  scanMeta?: ScanMetaRow | null,
): string[] {
  const out: string[] = [];
  if ((posture?.recommendation ?? "").toUpperCase() === "CASH_PRIORITY") {
    out.push("CASH_PRIORITY (exposure coach)");
  }
  if (premiumGate(gexRegime) === "SELL_CAUTION") {
    out.push("SELL_CAUTION (gamma gate)");
  }
  if ((scanMeta?.regime ?? "").toUpperCase() === "HALTED") {
    out.push("HALTED (scan regime)");
  }
  return out;
}

export function RegimeStamp({
  posture,
  gexRegime,
  scanMeta,
  className = "",
}: {
  posture?: ExposurePostureRow | null;
  gexRegime?: GexRegimeRow[] | null;
  scanMeta?: ScanMetaRow | null;
  className?: string;
}) {
  const chips: React.ReactNode[] = [];

  const rec = (posture?.recommendation ?? "").toUpperCase();
  const postureCfg = POSTURE_CFG[rec];
  if (postureCfg) {
    const ceil = Number(posture?.exposure_ceiling_pct);
    chips.push(
      <Chip
        key="posture"
        tone="bold"
        tabular
        className={`border ${postureCfg.cls}`}
        title={posture?.rationale || undefined}
      >
        {postureCfg.label}
        {Number.isFinite(ceil) && ceil > 0 ? ` · ceil ${ceil.toFixed(0)}%` : ""}
      </Chip>,
    );
  }

  const gate = premiumGate(gexRegime);
  if (gate) {
    chips.push(
      <Chip
        key="gate"
        tone="bold"
        className={`border ${gate === "SELL_OK" ? TONE.emerald : TONE.amber}`}
      >
        {gate === "SELL_OK" ? "SELL OK" : "SELL CAUTION"}
      </Chip>,
    );
  }

  const scan = (scanMeta?.regime ?? "").toUpperCase();
  const scanCfg = SCAN_CFG[scan] ?? (scan ? SCAN_CFG.CAUTION : undefined);
  if (scanCfg) {
    chips.push(
      <Chip key="scan" tone="bold" className={`border ${scanCfg.cls}`}>
        {scanCfg.label}
      </Chip>,
    );
  }

  if (!chips.length) return null;
  return <div className={`flex items-center flex-wrap gap-1 ${className}`}>{chips}</div>;
}
