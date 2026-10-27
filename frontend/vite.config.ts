/// <reference types="vitest" />
import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Em desenvolvimento, /api e /health vão para a API local (mesma origem: sem CORS).
const apiTarget = process.env.FOGO_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
      // Manual do usuário: docs/ fica fora do front (o GitHub também o exibe).
      "@docs": path.resolve(__dirname, "../docs"),
    },
  },
  server: {
    port: 5173,
    fs: { allow: [".", "../docs"] },
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
      "/health": { target: apiTarget, changeOrigin: true },
    },
  },
  build: {
    sourcemap: true,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          map: ["leaflet", "react-leaflet", "react-leaflet-cluster", "leaflet.heat"],
          charts: ["recharts"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
