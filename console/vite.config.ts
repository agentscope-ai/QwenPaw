import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // Empty = same-origin; frontend and backend served together, no hardcoded host.
  // Use a dedicated Vite-prefixed key so unrelated shell BASE_URL values don't leak into the build.
  const apiBaseUrl = env.VITE_API_BASE_URL ?? "";

  const hmrConfig = env.VITE_HMR_HOST ? {
    host: env.VITE_HMR_HOST,
    protocol: env.VITE_HMR_PROTOCOL || "wss",
    clientPort: parseInt(env.VITE_HMR_CLIENT_PORT || "443"),
  } : undefined;

  return {
    base: '/console/',
    define: {
      VITE_API_BASE_URL: JSON.stringify(apiBaseUrl),
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
      allowedHosts: ["copaw-comokiki.gd.ddnsto.com"],
      hmr: hmrConfig,
    },
    optimizeDeps: {
      include: ["diff"],
    },
    // build: {
    //   // Output to CoPaw's console directory,
    //   // so we don't need to copy files manually after build.
    //   outDir: path.resolve(__dirname, "../src/copaw/console"),
    //   emptyOutDir: true,
    // },
  };
});
