import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  base: "/CasaaFinance/",
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
        runtimeCaching: [
          {
            urlPattern: /docs\.google\.com\/spreadsheets/,
            handler: "StaleWhileRevalidate",
            options: { cacheName: "sheet-csv", expiration: { maxAgeSeconds: 86400 } },
          },
        ],
      },
    }),
  ],
});
