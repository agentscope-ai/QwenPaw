import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // Empty = same-origin; frontend and backend served together, no hardcoded host.
  const apiBaseUrl = env.BASE_URL ?? "";
  const devProxyTarget = env.DEV_API_PROXY_TARGET || "http://127.0.0.1:8088";

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
        "/api": {
          target: devProxyTarget,
          changeOrigin: true,
        },
      },
    },
    optimizeDeps: {
      include: ["diff"],
    },
  };
});
