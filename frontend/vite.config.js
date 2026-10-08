import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  worker: { format: "es" },
  server: { proxy: { "/api": "http://localhost:8000" } },
  build: {
    rollupOptions: {
      input: { main: resolve(import.meta.dirname, "index.html"), app: resolve(import.meta.dirname, "app/index.html") },
    },
  },
});
