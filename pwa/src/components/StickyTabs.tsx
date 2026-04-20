import type { ReactNode } from "react";
import { BookOpen, Newspaper } from "lucide-react";

/**
 * Sticky horizontal tab selector. Pins to `top: 0` within the scrollable
 * ancestor (`.app-content`). The selector stays visible above subsequent
 * content as the user scrolls.
 *
 * For a fuller tab bar with swipe-between, use SwipeTabs. This one is
 * tap-only so the sticky layer behaves predictably on touch devices.
 */

interface Tab {
  key: string;
  label: string;
  icon?: typeof BookOpen;
  badge?: number;
}

export function StickyTabs({
  tabs,
  active,
  onChange,
  right,
}: {
  tabs: Tab[];
  active: string;
  onChange: (key: string) => void;
  right?: ReactNode;
}) {
  return (
    <div className="sticky top-0 z-20 -mx-4 px-4 pt-2 pb-2.5 mb-3">
      {/* Base layer so content behind doesn't bleed through */}
      <div
        className="absolute inset-x-0 top-0 h-full pointer-events-none"
        style={{
          background: "linear-gradient(180deg, rgba(5,9,22,0.92) 0%, rgba(5,9,22,0.78) 70%, rgba(5,9,22,0) 100%)",
          backdropFilter: "blur(14px)",
          WebkitBackdropFilter: "blur(14px)",
        }}
      />

      {/* Tab row */}
      <div className="relative flex items-center gap-2">
        <div className="flex-1 flex items-center gap-1 p-1 rounded-xl border border-white/8"
             style={{
               background: "linear-gradient(135deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.02) 100%)",
               boxShadow: "0 2px 16px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.06)",
             }}>
          {tabs.map((t) => {
            const Icon = t.icon;
            const isActive = t.key === active;
            return (
              <button
                key={t.key}
                onClick={() => onChange(t.key)}
                className={`flex-1 flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg text-sm font-semibold transition-all ${
                  isActive
                    ? "bg-white/12 text-white shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
                style={isActive ? {
                  boxShadow: `inset 0 0 0 1px rgba(var(--accent-rgb), 0.25), 0 4px 12px rgba(var(--accent-rgb), 0.15)`,
                } : undefined}
              >
                {Icon && <Icon size={14} className={isActive ? "" : "opacity-70"} />}
                <span>{t.label}</span>
                {typeof t.badge === "number" && t.badge > 0 && (
                  <span className={`ml-1 min-w-[17px] h-[17px] px-1 rounded-full flex items-center justify-center text-[9px] font-bold ${
                    isActive ? "bg-white text-slate-900" : "bg-white/15 text-slate-200"
                  }`}>
                    {t.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        {right && <div className="shrink-0">{right}</div>}
      </div>
    </div>
  );
}

// Re-export icons for convenience
export { BookOpen, Newspaper };
