import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { vitePatchable } from "./vite-plugin-patchable";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // Empty = same-origin; frontend and backend served together, no hardcoded host.
  // Use a dedicated Vite-prefixed key so unrelated shell BASE_URL values don't leak into the build.
  const apiBaseUrl = env.VITE_API_BASE_URL ?? "";

  return {
    define: {
      VITE_API_BASE_URL: JSON.stringify(apiBaseUrl),
      TOKEN: JSON.stringify(env.TOKEN || ""),
      MOBILE: false,
    },
    plugins: [
      react(),
      vitePatchable({
        include: ["src/pages"],
        registryOutput: "src/plugins/generated/registerHostModules.ts",
        registryImport: "../moduleRegistry",
        requireMarker: false, // 注册所有文件，不需要 @patchable 标记
        verbose: true,
      }),
    ],
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
    },
    optimizeDeps: {
      include: ["diff"],
    },
    build: {
      target: "esnext",
      cssCodeSplit: true,
      sourcemap: mode !== "production",
      chunkSizeWarningLimit: 2000, // Increase limit since we're not manually chunking
      rollupOptions: {
        output: {
          // Let Vite/Rollup automatically handle chunking to avoid circular dependencies
        },
      },
    },
  };
});
