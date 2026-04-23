import { Home, Briefcase, CircleDot, Target, Archive, Settings } from "lucide-react";

const TABS = [
  { icon: Home,       label: "Home"      },
  { icon: Briefcase,  label: "Portfolio" },
  { icon: CircleDot,  label: "Options"   },
  { icon: Target,     label: "Decisions" },
  { icon: Archive,    label: "Archive"   },
  { icon: Settings,   label: "Settings"  },
] as const;

export function TabBar({
  active,
  onChange,
  decisionCount,
  defenseAlerts,
}: {
  active: number;
  onChange: (i: number) => void;
  decisionCount?: number;
  defenseAlerts?: number;
}) {
  return (
    <nav className="tabbar-base">
      <div className="flex">
        {TABS.map((tab, i) => {
          const Icon = tab.icon;
          const isActive = active === i;
          const showDecision = tab.label === "Decisions" && decisionCount && decisionCount > 0;
          const showDefense  = tab.label === "Options"   && defenseAlerts && defenseAlerts > 0;

          return (
            <button
              key={tab.label}
              onClick={() => onChange(i)}
              className="flex-1 flex flex-col items-center gap-[3px] pt-2.5 pb-1 relative transition-opacity active:opacity-60"
            >
              {/* Icon wrapper — pill highlight when active */}
              <div className="relative flex items-center justify-center">
                <div
                  className="absolute inset-0 -m-2 rounded-xl transition-all duration-200"
                  style={{
                    background: isActive ? `rgba(var(--accent-rgb), 0.14)` : "transparent",
                    boxShadow: isActive ? `0 0 12px rgba(var(--accent-rgb), 0.18)` : "none",
                  }}
                />
                <Icon
                  size={20}
                  strokeWidth={isActive ? 2.2 : 1.6}
                  className="relative transition-colors duration-200"
                  style={{ color: isActive ? `rgb(var(--accent-rgb))` : "rgb(100 116 139)" }}
                />

                {/* Defense badge */}
                {showDefense && (
                  <span className="absolute -top-1.5 -right-2.5 min-w-[16px] h-[16px] px-[3px] rounded-full bg-red-500 flex items-center justify-center shadow-lg text-[8.5px] font-bold text-white">
                    {defenseAlerts}
                  </span>
                )}

                {/* Decisions badge */}
                {showDecision && (
                  <span className="absolute -top-1.5 -right-2.5 min-w-[16px] h-[16px] px-[3px] rounded-full bg-amber-500 flex items-center justify-center shadow-lg text-[8.5px] font-bold text-black">
                    {decisionCount}
                  </span>
                )}
              </div>

              {/* Label */}
              <span
                className="text-[9px] font-semibold tracking-wide transition-colors duration-200"
                style={{ color: isActive ? `rgb(var(--accent-rgb))` : "rgb(71 85 105)" }}
              >
                {tab.label}
              </span>

              {/* Active dot */}
              {isActive && (
                <span
                  className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[18px] h-[2px] rounded-full"
                  style={{ background: `rgb(var(--accent-rgb))` }}
                />
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
