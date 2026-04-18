import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

export default defineConfig(({ mode }) => {
  const rootDir = fileURLToPath(new URL(".", import.meta.url));
  const env = loadEnv(mode, rootDir, "");

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    base: env.VITE_BASE_PATH || "/",
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            markdown: [
              "react-markdown",
              "remark-gfm",
              "rehype-highlight",
              "rehype-raw",
              "highlight.js",
              "react-syntax-highlighter",
            ],
            mermaid: ["mermaid"],
            router: ["react-router-dom"],
            i18n: ["i18next", "react-i18next"],
          },
        },
      },
    },
    optimizeDeps: {
      include: [
        "react",
        "react-dom",
        "react-router-dom",
        "i18next",
        "react-i18next",
      ],
    },
  };
});
