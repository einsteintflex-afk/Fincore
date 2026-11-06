/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    proxy: Object.fromEntries(["/api", "/docs", "/redoc"].map((p) => [p, { target: process.env.VITE_API_PROXY ?? "http://localhost:8000", changeOrigin: true }])),
  },
  build: { sourcemap: true, chunkSizeWarningLimit: 1200 },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"], css: false },
});
