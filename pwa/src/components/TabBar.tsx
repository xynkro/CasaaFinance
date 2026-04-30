import { useRef, useEffect, useState } from "react";
import { Home, Briefcase, CircleDot, Target, LineChart, Settings } from "lucide-react";

const TABS = [
  { icon: Home,       label: "Home"      },
  { icon: Briefcase,  label: "Portfolio" },
  { icon: CircleDot,  label: "Options"   },
  { icon: Target,     label: "Decisions" },
  { icon: LineChart,  label: "Review"    },
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
  const btnRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [pill, setPill] = useState({ left: 0, width: 0, ready: false });

  // Track the floating pill position
  useEffect(() => {
    const el = btnRefs.current[active];
    if (!el) return;
    setPill({ left: el.offsetLeft + 6, width: el.offsetWidth - 12, ready: true });
  }, [active]);

  return (
    <nav className="tabbar-base">
      <div className="relative flex px-0.5">

        {/* Floating accent blob behind active tab */}
        {pill.ready && (
          <div
            className="absolute top-1.5 rounded-[14px] pointer-events-none"
            style={{
              left: pill.left,
              width: pill.width,
              height: "calc(100% - 10px)",
              background: `radial-gradient(ellipse at 50% 30%, rgba(var(--accent-rgb), 0.16) 0%, rgba(var(--accent-rgb), 0.06) 100%)`,
              border: "1px solid rgba(var(--accent-rgb), 0.10)",
              transition: "left 0.32s cubic-bezier(0.4, 0, 0.2, 1), width 0.32s cubic-bezier(0.4, 0, 0.2, 1)",
            }}
          />
        )}

        {TABS.map((tab, i) => {
          const Icon = tab.icon;
          const isActive = active === i;
          const showDecision = tab.label === "Decisions" && !!decisionCount && decisionCount > 0;
          const showDefense  = tab.label === "Options"   && !!defenseAlerts && defenseAlerts > 0;

          return (
            <button
              key={tab.label}
              ref={(el) => { btnRefs.current[i] = el; }}
              onClick={() => onChange(i)}
              className="flex-1 flex flex-col items-center gap-[3px] pt-2 pb-1.5 relative"
              style={{ WebkitTapHighlightColor: "transparent" }}
            >
              {/* Top-edge indicator */}
              <div
                className="absolute top-0 left-1/2 -translate-x-1/2 rounded-b-full overflow-hidden"
                style={{
                  width: isActive ? 24 : 0,
                  height: 3,
                  background: `linear-gradient(90deg,
                    rgba(var(--accent-rgb), 0.5),
                    rgb(var(--accent-rgb)),
                    rgba(var(--accent-rgb), 0.5)
                  )`,
                  boxShadow: isActive ? `0 1px 10px rgba(var(--accent-rgb), 0.7)` : "none",
                  transition: "width 0.28s cubic-bezier(0.34, 1.56, 0.64, 1)",
                }}
              />

              {/* Icon container */}
              <div className="relative flex items-center justify-center mt-0.5">
                <Icon
                  size={21}
                  strokeWidth={isActive ? 2.15 : 1.55}
                  style={{
                    color: isActive ? `rgb(var(--accent-rgb))` : "rgb(71 85 105)",
                    transform: isActive ? "scale(1.1) translateY(-1px)" : "scale(1) translateY(0)",
                    filter: isActive
                      ? `drop-shadow(0 0 7px rgba(var(--accent-rgb), 0.55))`
                      : "none",
                    transition: "color 0.22s, transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.22s, stroke-width 0.22s",
                  }}
                />

                {/* Defense alert badge */}
                {showDefense && (
                  <span
                    className="absolute -top-2 -right-2.5 min-w-[15px] h-[15px] px-[3px] rounded-full flex items-center justify-center text-[8px] font-bold text-white pop-in"
                    style={{
                      background: "#ef4444",
                      boxShadow: "0 0 10px rgba(239,68,68,0.55), 0 1px 3px rgba(0,0,0,0.3)",
                    }}
                  >
                    {defenseAlerts}
                  </span>
                )}

                {/* Decision badge */}
                {showDecision && (
                  <span
                    className="absolute -top-2 -right-2.5 min-w-[15px] h-[15px] px-[3px] rounded-full flex items-center justify-center text-[8px] font-bold pop-in"
                    style={{
                      background: "#f59e0b",
                      color: "#0a0a0a",
                      boxShadow: "0 0 10px rgba(245,158,11,0.55), 0 1px 3px rgba(0,0,0,0.3)",
                    }}
                  >
                    {decisionCount}
                  </span>
                )}
              </div>

              {/* Label */}
              <span
                style={{
                  fontSize: "var(--t-2xs)",
                  fontWeight: isActive ? 700 : 500,
                  letterSpacing: "0.04em",
                  color: isActive ? `rgb(var(--accent-rgb))` : "rgb(56 68 84)",
                  transition: "color 0.22s, font-weight 0.22s",
                }}
              >
                {tab.label}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
