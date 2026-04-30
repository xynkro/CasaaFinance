import { useState, useEffect, useCallback } from "react";

export interface Settings {
  currency: "USD" | "SGD" | "both";
  compactCards: boolean;
  showDecisions: boolean;
  defaultTab: number;
  bgDarkness: number;        // 0-100, applied as overlay opacity
  bgBlur: number;            // 0-30px extra blur
  fontSize: number;          // 12-20, base font size in px
  cardOpacity: number;       // 0-100, glass card background opacity
  // NEW — user-adjustable safe area overrides
  ignoreSafeArea: boolean;   // if true, apply manual values below instead of env(safe-area-inset-*)
  safeAreaTop: number;       // 0-60px, manual top padding
  safeAreaBottom: number;    // 0-60px, manual bottom padding
  tabBarHeight: number;      // 48-80px
  accentColor: "bloomberg" | "terminal_green" | "indigo" | "emerald" | "amber" | "pink" | "cyan";  // NEW — accent hue
}

const DEFAULTS: Settings = {
  currency: "both",
  compactCards: false,
  showDecisions: true,
  defaultTab: 0,
  bgDarkness: 70,
  bgBlur: 0,
  fontSize: 16,
  cardOpacity: 50,
  ignoreSafeArea: true,
  safeAreaTop: 8,
  safeAreaBottom: 8,
  tabBarHeight: 60,
  accentColor: "bloomberg",
};

const KEY = "casaa_settings_v2";

function load(): Settings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return DEFAULTS;
  }
}

function save(s: Settings) {
  localStorage.setItem(KEY, JSON.stringify(s));
}

const ACCENT_MAP = {
  bloomberg:      { rgb: "255,140,0",   hex: "#ff8c00", bright: "#ffa733" },
  terminal_green: { rgb: "39,213,127",  hex: "#27d57f", bright: "#5ce29c" },
  indigo:         { rgb: "129,140,248", hex: "#818cf8", bright: "#a5b4fc" },
  emerald:        { rgb: "52,211,153",  hex: "#34d399", bright: "#6ee7b7" },
  amber:          { rgb: "251,191,36",  hex: "#fbbf24", bright: "#fcd34d" },
  pink:           { rgb: "244,114,182", hex: "#f472b6", bright: "#f9a8d4" },
  cyan:           { rgb: "34,211,238",  hex: "#22d3ee", bright: "#67e8f9" },
};

/** Apply settings as CSS custom properties on :root */
export function applyTheme(s: Settings) {
  const root = document.documentElement;
  root.style.setProperty("--bg-darkness", `${s.bgDarkness / 100}`);
  root.style.setProperty("--bg-blur", `${s.bgBlur}px`);
  root.style.setProperty("--base-font", `${s.fontSize}px`);
  root.style.setProperty("--card-opacity", `${s.cardOpacity / 100}`);
  // Safe area override
  if (s.ignoreSafeArea) {
    root.style.setProperty("--safe-top", `${s.safeAreaTop}px`);
    root.style.setProperty("--safe-bottom", `${s.safeAreaBottom}px`);
  } else {
    root.style.setProperty("--safe-top", "env(safe-area-inset-top, 0px)");
    root.style.setProperty("--safe-bottom", "env(safe-area-inset-bottom, 0px)");
  }
  root.style.setProperty("--tabbar-h", `calc(var(--safe-bottom) + ${s.tabBarHeight}px)`);
  root.style.setProperty("--header-h", `calc(var(--safe-top) + 52px)`);
  // Accent color
  const accent = ACCENT_MAP[s.accentColor] ?? ACCENT_MAP.bloomberg;
  root.style.setProperty("--accent-rgb", accent.rgb);
  root.style.setProperty("--accent", accent.hex);
  root.style.setProperty("--accent-bright", accent.bright);
}

export function useSettings() {
  const [settings, setSettings] = useState<Settings>(load);

  useEffect(() => {
    save(settings);
    applyTheme(settings);
  }, [settings]);

  useEffect(() => { applyTheme(settings); }, []);

  const update = useCallback((patch: Partial<Settings>) => {
    setSettings((prev) => ({ ...prev, ...patch }));
  }, []);

  return { settings, update };
}
