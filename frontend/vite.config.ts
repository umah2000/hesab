import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    // Same-origin API in development, so session cookies and CSRF work as in production.
    proxy: { "/api": { target: process.env.NEXTCAM_API ?? "http://127.0.0.1:5000", changeOrigin: false } },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
});
