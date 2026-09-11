import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
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
