/**
 * CHIP_TONE — the four semantic chip tints (bg / text / border Tailwind
 * classes) shared by RegimeStamp, OptionMechanics, and other chip strips.
 * One source of truth so a tint tweak (e.g. slate-500/10 → /15) is a single
 * edit instead of a hand-synced copy that silently drifts.
 */
export const CHIP_TONE = {
  emerald: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  amber: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  red: "bg-red-500/15 text-red-400 border-red-500/30",
  slate: "bg-slate-500/10 text-slate-400 border-slate-500/20",
};
