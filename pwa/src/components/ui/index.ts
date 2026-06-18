/**
 * ui/ — the FinancePWA reusable primitive library.
 *
 * One documented, accessible, phone-first component per genuinely-repeated
 * inline UI pattern found across the 41 cards + pages. Everything here is
 * themed exclusively through the existing tokens (--t-* type scale,
 * .glass surfaces, slate/emerald/red/indigo Tailwind tokens) — consolidation
 * and hardening, never a redesign.
 *
 * Import from the barrel:
 *   import { Chip, ConvictionDots, StatusPill, DeltaText } from "../components/ui";
 *
 * Async / data-state primitives (LoadingState, EmptyState, ErrorState,
 * NotAuthorized, SignInScreen) live in ../AsyncStates and are re-exported here
 * so the whole UI layer is reachable from one path. AsyncStates' original
 * importers (importing directly from "../components/AsyncStates") keep working.
 */
export { ConvictionDots, type ConvictionDotsProps } from "./ConvictionDots";
export { Chip, type ChipProps } from "./Chip";
export { CHIP_TONE } from "./tones";
export { StatusPill, type StatusPillProps } from "./StatusPill";
export {
  DECISION_STATUS,
  resolveStatus,
  type DecisionStatusConfig,
} from "./statusConfig";
export { DeltaText, type DeltaTextProps } from "./DeltaText";
export { SectionLabel, type SectionLabelProps } from "./SectionLabel";
export { ActionButton, type ActionButtonProps } from "./ActionButton";

// Re-export the async-state family so ui/ is the single import surface.
export {
  LoadingState,
  EmptyState,
  ErrorState,
  NotAuthorized,
  SignInScreen,
} from "../AsyncStates";
