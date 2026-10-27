import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";
import { readFileSync } from "fs";

// plugin.json is the single source of truth for the shipped version; inject it
// at build time so the header can render it without an extra runtime request.
const creatorVersion: string = JSON.parse(
  readFileSync(path.resolve(__dirname, "../plugin.json"), "utf-8"),
).version;

export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  define: {
    __CREATOR_VERSION__: JSON.stringify(creatorVersion ?? ""),
  },
  server: {
    proxy: {
      "/api/qwenpaw-creator": {
        target: process.env.CREATOR_BACKEND_URL || "http://127.0.0.1:18110",
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: [{ find: "@", replacement: path.resolve(__dirname, "src") }],
  },
  build: {
    outDir: "dist/app",
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/lucide-react/")) return "icons-vendor";
          return id.includes("node_modules") ? "vendor" : undefined;
        },
      },
    },
  },
});
