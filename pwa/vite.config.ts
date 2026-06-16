import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  base: "/CasaaFinance/",
  build: { chunkSizeWarningLimit: 700 },
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      // SELF-DESTROYING SERVICE WORKER — the precaching SW repeatedly broke
      // loads on iOS standalone: the FIRST open worked (served from network)
      // and installed the SW; the SECOND open (now SW-controlled) spun forever
      // on a stale/partial cached app shell; a full delete fixed it until the
      // SW reinstalled. The aggressive skipWaiting + clientsClaim + forced
      // controllerchange-reload (added earlier to beat a *stale-pin* problem)
      // is what caused the breakage — so the app oscillated between
      // pinned-stale and broken-load.
      //
      // This app NEEDS the network anyway (live Firestore), so offline shell
      // caching buys nothing. `selfDestroying` ships a SW that unregisters
      // itself and clears every cache on each device, removing the broken SW
      // for good and reverting to plain, always-fresh network loads. The
      // manifest below (home-screen install, icons, standalone display) is
      // unaffected — only the caching layer goes away.
      selfDestroying: true,
      manifest: {
        name: "Casaa Finance",
        short_name: "Casaa",
        start_url: "/CasaaFinance/",
        display: "standalone",
        background_color: "#0f172a",
        theme_color: "#0f172a",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          { src: "icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
    }),
  ],
});
