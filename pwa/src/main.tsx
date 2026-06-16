import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";

// NOTE: the old controllerchange→reload service-worker handler was removed.
// The SW is now self-destroying (see vite.config.ts) — there is no precaching
// SW to manage, so the app always loads fresh from the network. Without a SW
// serving a stale bundle, the forced-reload-on-SW-takeover dance is both
// unnecessary and was itself causing the second-load breakage on iOS.

// Recover from a STALE dynamic-import chunk. After a deploy, GitHub Pages
// replaces the hashed chunk files; a still-open PWA (or a stale-cached index)
// then references a chunk that 404s. A lazy import (FirebaseGate, page bundles)
// that fails this way HANGS its <Suspense> forever — the infinite spinner with
// no data. Vite fires `vite:preloadError` on window when this happens; reload
// ONCE to pull the fresh index + chunks. A sessionStorage timestamp prevents a
// reload loop if the chunk is genuinely gone — after one retry we let the error
// propagate to the root ErrorBoundary, which shows a manual "reload" screen
// instead of spinning.
window.addEventListener("vite:preloadError", (event) => {
  const KEY = "casaa:lastChunkReload";
  const now = Date.now();
  const last = Number(sessionStorage.getItem(KEY) || "0");
  if (now - last > 10_000) {
    sessionStorage.setItem(KEY, String(now));
    event.preventDefault(); // we handle it via reload, not an unhandled throw
    window.location.reload();
  }
  // else: within the retry window → let it throw → ErrorBoundary catches it.
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
