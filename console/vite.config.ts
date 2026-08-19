/// <reference types="vitest" />
import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// Vitest-only plugin: transforms .css imports inside node_modules to empty
// stubs. This prevents errors from packages like @agentscope-ai/icons that
// import CSS.
//
// It must never run for real builds: stubbing node_modules CSS also strips
// monaco-editor's stylesheet, which makes the hidden `.monaco-editor
// .inputarea` textarea render with browser default styles (a big white box
// over the code) and breaks cursor positioning in Coding Mode (issue #6547).
const cssStubPlugin: Plugin = {
  name: "css-stub",
  transform(_code: string, id: string) {
    if (id.includes("node_modules") && id.endsWith(".css")) {
      return { code: "export default {}" };
    }
  },
};

export default defineConfig(({ command, mode }) => {
  // Vitest resolves the config as a dev server (`serve`) with mode "test",
  // while `vite build --mode test` is a real build that needs real CSS.
  const isVitest = command === "serve" && mode === "test";
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
    plugins: [react(), ...(isVitest ? [cssStubPlugin] : [])],
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
          target: "http://localhost:8088",
          changeOrigin: false,
        },
      },
    },
    test: {
      globals: true,
      environment: "jsdom",
      testTimeout: 15_000,
      setupFiles: ["./src/test/setup.ts"],
      css: true,
      // all @agentscope-ai/* packages excluded from inline — they are large / have CSS imports
      // aliases below redirect each to a stub or compiled entry
      deps: {
        inline: [/@agentscope-ai\/(?!icons|chat|design)/],
      },
      alias: {
        // Preserve vendor deep imports before aliasing the package entrypoint.
        "@agentscope-ai/chat/lib": path.resolve(
          __dirname,
          "node_modules/@agentscope-ai/chat/lib",
        ),
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
        "@tauri-apps/api/core": path.resolve(
          __dirname,
          "src/test/tauri-mock.ts",
        ),
        "@tauri-apps/plugin-dialog": path.resolve(
          __dirname,
          "src/test/tauri-mock.ts",
        ),
      },
      exclude: [
        "**/node_modules/**",
        "**/dist/**",
        // 旧测试用 node:test，与 vitest 不兼容，待迁移
        "**/testConnectionMessage.test.ts",
        // ChatPage test causes worker crash - pre-existing issue, needs more mock setup
        "**/pages/Chat/ChatPage.test.tsx",
        // Tauri modules require @tauri-apps/api which only exists in desktop builds
        "**/src/tauri/**",
      ],
      coverage: {
        provider: "v8",
        reporter: ["text", "html", "json", "json-summary", "lcov", "cobertura"],
        include: ["src/**/*.{ts,tsx}"],
        exclude: [
          "src/test/**",
          "src/tauri/**",
          "src/**/*.d.ts",
          "src/main.tsx",
          "src/vite-env.d.ts",
        ],
        thresholds: {
          statements: 5,
          branches: 4,
          functions: 3,
          lines: 5,
        },
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
            if (
              id.includes("node_modules/@ant-design/plots/") ||
              id.includes("node_modules/@antv/")
            ) {
              return "charts-vendor";
            }
            if (
              id.includes("node_modules/monaco-editor/") ||
              id.includes("node_modules/@monaco-editor/")
            ) {
              return "editor-vendor";
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
          },
        },
      },
    },
  };
});
