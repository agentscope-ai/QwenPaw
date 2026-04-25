/// <reference types="vitest" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// Vitest plugin: transforms .css imports inside node_modules to empty stubs.
// This prevents errors from packages like @agentscope-ai/icons that import CSS.
const cssStubPlugin = {
  name: "css-stub",
  transform(_code: string, id: string) {
    if (id.includes("node_modules") && id.endsWith(".css")) {
      return { code: "export default {}" };
    }
  },
};

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
    plugins: [react(), cssStubPlugin],
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
    test: {
      globals: true,
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      css: true,
      // all @agentscope-ai/* packages excluded from inline — they are large / have CSS imports
      // aliases below redirect each to a stub or compiled entry
      deps: {
        inline: [/@agentscope-ai\/(?!icons|chat|design)/],
      },
      alias: {
        // chat is aliased to a tiny stub to avoid OOM from the 2.3MB real package
        // Tests that need specific behavior override with vi.mock('@agentscope-ai/chat', factory)
        "@agentscope-ai/chat": path.resolve(__dirname, "src/test/chat-mock.ts"),
        // design is aliased to a stub to avoid hanging from its 3MB lib
        "@agentscope-ai/design": path.resolve(
          __dirname,
          "src/test/design-mock.ts",
        ),
        "@agentscope-ai/icons": path.resolve(
          __dirname,
          "src/test/icons-mock.ts",
        ),
      },
      exclude: [
        "**/node_modules/**",
        "**/dist/**",
        // 旧测试用 node:test，与 vitest 不兼容，待迁移
        "**/testConnectionMessage.test.ts",
        // ChatPage test causes worker crash - pre-existing issue, needs more mock setup
        "**/pages/Chat/ChatPage.test.tsx",
      ],
      coverage: {
        provider: "v8",
        reporter: ["text", "html", "json", "lcov"],
        include: ["src/**/*.{ts,tsx}"],
        exclude: [
          "src/test/**",
          "src/**/*.d.ts",
          "src/main.tsx",
          "src/vite-env.d.ts",
        ],
        // 第一阶段：记录基线，不强制卡点
        // 后续稳定后可开启：thresholds: { statements: 60, functions: 60 }
      },
    },
    optimizeDeps: {
      include: ["diff"],
    },
    build: {
      // Output to QwenPaw's console directory,
      // so we don't need to copy files manually after build.
      // outDir: path.resolve(__dirname, "../src/qwenpaw/console"),
      // emptyOutDir: true,
      cssCodeSplit: true,
      sourcemap: mode !== "production",
      chunkSizeWarningLimit: 1000,
      rollupOptions: {
        output: {
          manualChunks(id) {
            // React core
            if (
              id.includes("node_modules/react/") ||
              id.includes("node_modules/react-dom/") ||
              id.includes("node_modules/react-router-dom/") ||
              id.includes("node_modules/scheduler/")
            ) {
              return "react-vendor";
            }
            // Ant Design + AgentScope design system (merged to avoid circular deps)
            if (
              id.includes("node_modules/antd/") ||
              id.includes("node_modules/antd-style/") ||
              id.includes("node_modules/@ant-design/") ||
              id.includes("node_modules/@agentscope-ai/")
            ) {
              return "ui-vendor";
            }
            // i18n
            if (
              id.includes("node_modules/i18next/") ||
              id.includes("node_modules/react-i18next/")
            ) {
              return "i18n-vendor";
            }
            // Markdown rendering
            if (
              id.includes("node_modules/react-markdown/") ||
              id.includes("node_modules/remark-gfm/") ||
              id.includes("node_modules/rehype") ||
              id.includes("node_modules/remark") ||
              id.includes("node_modules/unified/") ||
              id.includes("node_modules/mdast") ||
              id.includes("node_modules/hast") ||
              id.includes("node_modules/micromark")
            ) {
              return "markdown-vendor";
            }
            // Drag and drop
            if (id.includes("node_modules/@dnd-kit/")) {
              return "dnd-vendor";
            }
            // Utilities (dayjs, zustand, ahooks, etc.)
            if (
              id.includes("node_modules/dayjs/") ||
              id.includes("node_modules/zustand/") ||
              id.includes("node_modules/ahooks/") ||
              id.includes("node_modules/@vvo/tzdb/")
            ) {
              return "utils-vendor";
            }
          },
        },
      },
    },
  };
});
