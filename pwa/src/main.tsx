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

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
