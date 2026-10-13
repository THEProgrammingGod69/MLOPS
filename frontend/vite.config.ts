import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The UI always calls same-origin /api/v1/*. In development Vite proxies it to the
// FastAPI service; in production nginx (Docker) or FastAPI itself (/ui) serves both.
const apiTarget = process.env.VITE_API_PROXY ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    port: 5173,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
      "/docs": { target: apiTarget, changeOrigin: true },
      "/openapi.json": { target: apiTarget, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
});
