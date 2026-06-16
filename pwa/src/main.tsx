import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";

// PWA auto-reload on new build. vite-plugin-pwa (registerType:'autoUpdate' +
// skipWaiting + clientsClaim) installs and activates a new service worker, but
// that does NOT swap the already-loaded JS — an always-open standalone PWA keeps
// serving the OLD bundle until a full reload. So force a reload the moment a new
// SW takes control. `hadController` is captured at load time so the very first
// install (no prior controller) doesn't trigger a spurious first-visit refresh.
// Without this, a cached build once pinned the app weeks behind every deploy.
if ("serviceWorker" in navigator) {
  const hadController = !!navigator.serviceWorker.controller;
  let reloading = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (reloading || !hadController) return;
    reloading = true;
    window.location.reload();
  });
}

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
