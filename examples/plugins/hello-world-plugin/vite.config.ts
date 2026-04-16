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
      // React is provided by the host app via the `host` object passed to
      // register(). Do NOT bundle it — the plugin accesses it at runtime.
      external: ["react", "react-dom"],
    },
  },
});
