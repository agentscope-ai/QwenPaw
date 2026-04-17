import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [
    // Classic JSX runtime: <Card> → React.createElement(Card, ...)
    // React is injected at the top of index.tsx from window.QwenPaw.host,
    // so the JSX transform references the host-provided React — no bundle.
    react({ jsxRuntime: "classic" }),
  ],
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  build: {
    lib: {
      entry: "src/index.tsx",
      formats: ["es"],
      fileName: () => "index.js",
    },
    rollupOptions: {
      external: ["react", "react-dom"],
    },
  },
});
