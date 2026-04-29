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
      manifest: {
        name: "Casaa Finance",
        short_name: "Casaa",
        start_url: "/CasaaFinance/",
        display: "standalone",
        background_color: "#0f172a",
        theme_color: "#0f172a",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" },
        ],
      },
      workbox: {
        // Force the new SW to take over IMMEDIATELY rather than wait for all
        // tabs to close. Critical for PWAs in standalone mode that never
        // fully reload.
        skipWaiting: true,
        clientsClaim: true,
        cleanupOutdatedCaches: true,
        runtimeCaching: [
          {
            urlPattern: /docs\.google\.com\/spreadsheets/,
            handler: "NetworkFirst",
            options: {
              cacheName: "sheet-csv",
              expiration: { maxAgeSeconds: 3600 },
              networkTimeoutSeconds: 8,
            },
          },
        ],
      },
    }),
  ],
});
