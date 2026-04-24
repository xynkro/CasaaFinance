import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
  variant = "base",
  noPad = false,
}: {
  children: ReactNode;
  className?: string;
  /** "base" = subtle glass | "bright" = elevated | "accent" = accent-tinted */
  variant?: "base" | "bright" | "accent";
  /** Skip default p-4 padding (for cards that need custom padding or nested sections) */
  noPad?: boolean;
}) {
  const variantClass = {
    base:   "glass",
    bright: "glass-bright",
    accent: "glass-accent",
  }[variant];

  return (
    <div className={`${variantClass} rounded-[18px] ${noPad ? "" : "p-4"} ${className}`}>
      {children}
    </div>
  );
}
