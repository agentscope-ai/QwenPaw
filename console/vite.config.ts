import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // Empty = same-origin; frontend and backend served together, no hardcoded host.
  const apiBaseUrl = env.BASE_URL ?? "";

  // BACKEND_URL: prefer OS env var (set by `copaw dev` at runtime) over .env
  // file, so the dev command can pass a dynamic port without editing any file.
  const backendUrl =
    process.env.BACKEND_URL || env.BACKEND_URL || "http://localhost:8088";

  return {
    define: {
      BASE_URL: JSON.stringify(apiBaseUrl),
      TOKEN: JSON.stringify(env.TOKEN || ""),
      MOBILE: false,
    },
    plugins: [react()],
    css: {
      modules: {
        localsConvention: "camelCase",
        generateScopedName: "[name]__[local]__[hash:base64:5]",
      },
      preprocessorOptions: {
        less: {
          javascriptEnabled: true,
        },
      },
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      host: "0.0.0.0",
      port: 5173,
      proxy: {
        // In dev mode, forward all /api requests to the Python backend so
        // you can run `npm run dev` and get hot-reload without rebuilding.
        // Override the target via BACKEND_URL env var or .env.development.
        "/api": {
          target: backendUrl,
          changeOrigin: true,
        },
      },
    },
    optimizeDeps: {
      include: ["diff"],
    },
  };
});
