import { useState } from "react";

const STORAGE_KEY = "casaa_pin_ok";

/**
 * PIN session. Lives 7 days from last successful entry. Hook is in /lib so
 * it can sit alongside other hooks without tripping the Fast Refresh rule
 * about mixing component + non-component exports in one file.
 */
export function usePinAuth() {
  const [authed, setAuthed] = useState(() => {
    try {
      const ts = Number(localStorage.getItem(STORAGE_KEY) || "0");
      // Session valid for 7 days
      return ts > 0 && Date.now() - ts < 7 * 86400 * 1000;
    } catch {
      return false;
    }
  });

  const grant = () => {
    localStorage.setItem(STORAGE_KEY, String(Date.now()));
    setAuthed(true);
  };

  return { authed, grant };
}
