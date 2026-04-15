import { useState, useEffect, useCallback } from "react";

export interface Settings {
  currency: "USD" | "SGD" | "both";
  compactCards: boolean;
  showDecisions: boolean;
  defaultTab: number;
}

const DEFAULTS: Settings = {
  currency: "both",
  compactCards: false,
  showDecisions: true,
  defaultTab: 0,
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

export function useSettings() {
  const [settings, setSettings] = useState<Settings>(load);

  useEffect(() => {
    save(settings);
  }, [settings]);

  const update = useCallback((patch: Partial<Settings>) => {
    setSettings((prev) => ({ ...prev, ...patch }));
  }, []);

  return { settings, update };
}
