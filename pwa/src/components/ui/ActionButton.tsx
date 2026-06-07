import type { ButtonHTMLAttributes, ReactNode } from "react";

/**
 * ActionButton — the standard tappable button used for secondary actions
 * (Retry, "Use a different account", inline card actions). Wraps the
 * recurring `rounded-xl + active:scale + hover:border + focus-visible:ring`
 * recipe so every button is keyboard-accessible and touch-friendly by default.
 *
 * @example
 * <ActionButton icon={<RefreshCw size={15} />} onClick={refetch}>Retry</ActionButton>
 * <ActionButton variant="primary" fullWidth onClick={confirm}>Confirm</ActionButton>
 *
 * Props / best-practice notes:
 * - Extends native <button> props, so `onClick`, `disabled`, `type`,
 *   `aria-*`, `aria-busy`, etc. all pass straight through.
 * - `variant`:
 *     "surface" (default) — glassy neutral (surface-bright + border-bright),
 *     "primary"           — solid white-on-dark CTA (matches sign-in button),
 *     "ghost"             — transparent, hover-tinted (dense inline actions).
 * - `size`: "md" (default) or "sm" (compact list rows).
 * - Always renders a real <button> with a visible focus-visible ring, so it
 *   is reachable and operable by keyboard — never wrap a div with onClick.
 * - `fullWidth` stretches to the container (phone-first full-bleed buttons).
 * - Theming: existing surface/border tokens + white focus ring. No new colors.
 */
export interface ActionButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  /** Leading icon (decorative). */
  icon?: ReactNode;
  variant?: "surface" | "primary" | "ghost";
  size?: "md" | "sm";
  fullWidth?: boolean;
}

export function ActionButton({
  children,
  icon,
  variant = "surface",
  size = "md",
  fullWidth = false,
  className = "",
  ...rest
}: ActionButtonProps) {
  const sizeClass =
    size === "sm"
      ? "px-3 py-1.5 text-[length:var(--t-2xs)]"
      : "px-4 py-2.5 text-[length:var(--t-sm)]";

  const variantClass = {
    surface: "text-slate-100 hover:border-white/25",
    primary: "bg-white text-slate-800",
    ghost: "text-slate-300 hover:bg-white/5 border border-transparent",
  }[variant];

  const focusRing =
    variant === "primary"
      ? "focus-visible:ring-white/60"
      : "focus-visible:ring-white/30";

  // Inline style only for variants that lean on glass-surface tokens.
  const surfaceStyle =
    variant === "surface"
      ? { background: "var(--surface-bright)", border: "1px solid var(--border-bright)" }
      : undefined;

  return (
    <button
      {...rest}
      className={`inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all active:scale-95 disabled:opacity-60 disabled:active:scale-100 focus-visible:outline-none focus-visible:ring-2 ${sizeClass} ${variantClass} ${focusRing} ${
        fullWidth ? "w-full" : ""
      } ${className}`}
      style={surfaceStyle}
    >
      {icon}
      {children}
    </button>
  );
}
