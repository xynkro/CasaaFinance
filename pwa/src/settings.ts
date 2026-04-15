import { useState, useEffect, useCallback } from "react";

export interface Settings {
  currency: "USD" | "SGD" | "both";
  compactCards: boolean;
  showDecisions: boolean;
  defaultTab: number;
  bgDarkness: number;     // 0-100, applied as overlay opacity
  bgBlur: number;         // 0-30px extra blur
  fontSize: number;       // 12-20, base font size in px
  cardOpacity: number;    // 0-100, glass card background opacity
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
};

const KEY = "casaa_settings";

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

/** Apply settings as CSS custom properties on :root */
export function applyTheme(s: Settings) {
  const root = document.documentElement;
  root.style.setProperty("--bg-darkness", `${s.bgDarkness / 100}`);
  root.style.setProperty("--bg-blur", `${s.bgBlur}px`);
  root.style.setProperty("--base-font", `${s.fontSize}px`);
  root.style.setProperty("--card-opacity", `${s.cardOpacity / 100}`);
}

export function useSettings() {
  const [settings, setSettings] = useState<Settings>(load);

  useEffect(() => {
    save(settings);
    applyTheme(settings);
  }, [settings]);

  // Apply on mount
  useEffect(() => { applyTheme(settings); }, []);

  const update = useCallback((patch: Partial<Settings>) => {
    setSettings((prev) => ({ ...prev, ...patch }));
  }, []);

  return { settings, update };
}
