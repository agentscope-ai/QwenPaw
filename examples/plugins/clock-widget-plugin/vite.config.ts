import { defineConfig } from "vite";

export default defineConfig({
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  build: {
    lib: {
      entry: "src/index.ts",
      // ESM format — loaded via Blob URL + dynamic import() by the host app
      formats: ["es"],
      fileName: () => "index.js",
    },
    rollupOptions: {
      // React/ReactDOM are provided by the host via window.__HOST_CONTEXT__.
      // Do NOT bundle them.
      // dayjs is a plain JS lib with no React dependency — bundle it directly.
      external: ["react", "react-dom"],
    },
  },
});
