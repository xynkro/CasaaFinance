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
    <div className="sticky top-0 z-20 -mx-4 px-4 pt-2.5 pb-2 mb-2">
      {/* Frosted backdrop */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: "linear-gradient(180deg, rgba(7,9,15,0.96) 0%, rgba(7,9,15,0.85) 75%, transparent 100%)",
          backdropFilter: "blur(18px)",
          WebkitBackdropFilter: "blur(18px)",
        }}
      />

      {/* Tab row */}
      <div className="relative flex items-center gap-2">
        {/* Pill container */}
        <div
          className="flex-1 flex p-1 rounded-2xl gap-1"
          style={{
            background: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.07)",
            boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)",
          }}
        >
          {tabs.map((t) => {
            const Icon = t.icon;
            const isActive = t.key === active;
            return (
              <button
                key={t.key}
                onClick={() => onChange(t.key)}
                className="flex-1 flex items-center justify-center gap-1.5 py-2 px-3 rounded-xl text-[13px] font-semibold transition-all duration-200"
                style={{
                  background: isActive ? "rgba(255,255,255,0.1)" : "transparent",
                  color: isActive ? "#f1f5f9" : "rgb(100 116 139)",
                  border: isActive ? "1px solid rgba(255,255,255,0.1)" : "1px solid transparent",
                  boxShadow: isActive
                    ? `inset 0 0 0 0.5px rgba(var(--accent-rgb),0.22), 0 2px 12px rgba(var(--accent-rgb),0.12)`
                    : "none",
                }}
              >
                {Icon && (
                  <Icon size={13} style={{ opacity: isActive ? 1 : 0.6 }} />
                )}
                <span>{t.label}</span>
                {typeof t.badge === "number" && t.badge > 0 && (
                  <span
                    className="min-w-[16px] h-[16px] px-1 rounded-full flex items-center justify-center text-[8.5px] font-bold"
                    style={{
                      background: isActive ? `rgb(var(--accent-rgb))` : "rgba(255,255,255,0.15)",
                      color: isActive ? "#fff" : "rgb(148 163 184)",
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
