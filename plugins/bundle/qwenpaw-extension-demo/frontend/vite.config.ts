import react from "@vitejs/plugin-react";
import { resolve } from "path";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react({ jsxRuntime: "classic" })],
  build: {
    lib: {
      entry: resolve(__dirname, "src/index.tsx"),
      formats: ["es"],
      fileName: () => "index.js",
    },
    outDir: resolve(__dirname, "dist"),
    emptyOutDir: true,
    rollupOptions: {
      // host provides React/ReactDOM/antd via window.QwenPaw.host
      external: ["react", "react-dom"],
    },
  },
});
