import type { ReactNode } from "react";
import { BookOpen, Newspaper } from "lucide-react";

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
    <div className="sticky top-0 z-20 -mx-4 px-4 pt-3 pb-2.5 mb-1">
      {/* Deep frosted backdrop with fade-out bottom */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: "linear-gradient(180deg, rgba(5,7,13,0.97) 0%, rgba(5,7,13,0.90) 70%, transparent 100%)",
          backdropFilter: "blur(24px)",
          WebkitBackdropFilter: "blur(24px)",
        }}
      />

      {/* Tab row */}
      <div className="relative flex items-center gap-2">
        {/* Segmented control container */}
        <div
          className="flex-1 flex p-[3px] rounded-2xl gap-[3px]"
          style={{
            background: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.075)",
            boxShadow: "inset 0 1px 0 rgba(255,255,255,0.05), inset 0 -1px 0 rgba(0,0,0,0.1)",
          }}
        >
          {tabs.map((t) => {
            const Icon = t.icon;
            const isActive = t.key === active;
            return (
              <button
                key={t.key}
                onClick={() => onChange(t.key)}
                className="flex-1 flex items-center justify-center gap-1.5 py-2 px-2.5 rounded-[14px] transition-all duration-250"
                style={{
                  WebkitTapHighlightColor: "transparent",
                  background: isActive
                    ? "linear-gradient(145deg, rgba(255,255,255,0.12) 0%, rgba(255,255,255,0.07) 100%)"
                    : "transparent",
                  color: isActive ? "#f1f5f9" : "rgb(71 85 105)",
                  border: isActive
                    ? "1px solid rgba(255,255,255,0.11)"
                    : "1px solid transparent",
                  boxShadow: isActive
                    ? `inset 0 1px 0 rgba(255,255,255,0.10), 0 1px 8px rgba(0,0,0,0.2), 0 0 0 0.5px rgba(var(--accent-rgb),0.18), 0 2px 14px rgba(var(--accent-rgb),0.10)`
                    : "none",
                  fontSize: "12.5px",
                  fontWeight: isActive ? 650 : 500,
                  letterSpacing: isActive ? "-0.01em" : "0",
                  transitionTimingFunction: "cubic-bezier(0.2, 0, 0, 1)",
                }}
              >
                {Icon && (
                  <Icon
                    size={12}
                    style={{
                      opacity: isActive ? 1 : 0.5,
                      color: isActive ? `rgb(var(--accent-rgb))` : "currentColor",
                      transition: "color 0.2s, opacity 0.2s",
                    }}
                  />
                )}
                <span>{t.label}</span>
                {typeof t.badge === "number" && t.badge > 0 && (
                  <span
                    className="flex items-center justify-center rounded-full font-bold"
                    style={{
                      minWidth: 15,
                      height: 15,
                      padding: "0 3px",
                      fontSize: "8px",
                      background: isActive ? `rgb(var(--accent-rgb))` : "rgba(255,255,255,0.14)",
                      color: isActive ? "#fff" : "rgb(148 163 184)",
                      boxShadow: isActive ? `0 0 8px rgba(var(--accent-rgb),0.5)` : "none",
                      transition: "background 0.2s, box-shadow 0.2s",
                    }}
                  >
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

export { BookOpen, Newspaper };
