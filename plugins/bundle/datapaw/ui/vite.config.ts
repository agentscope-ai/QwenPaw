import react from "@vitejs/plugin-react";
import path from "path";
import { defineConfig, type Plugin } from "vite";
import { fileURLToPath } from "url";

const root = path.dirname(fileURLToPath(import.meta.url));
const frontendSrc = path.resolve(root, "../frontend/src");
const r = (p: string) => path.resolve(root, p);

function inlineCssAsStyleTag(): Plugin {
  return {
    name: "datapaw-ui:inline-css",
    enforce: "post",
    generateBundle(_options, bundle) {
      const cssAssets = Object.entries(bundle).filter(
        ([name, asset]) => asset.type === "asset" && name.endsWith(".css"),
      ) as [string, { type: "asset"; source: string | Uint8Array }][];
      if (cssAssets.length === 0) return;

      const entryChunk = Object.values(bundle).find(
        (c) => c.type === "chunk" && (c as { isEntry?: boolean }).isEntry,
      ) as { type: "chunk"; code: string } | undefined;
      if (!entryChunk) return;

      const css = cssAssets
        .map(([, asset]) =>
          typeof asset.source === "string"
            ? asset.source
            : new TextDecoder().decode(asset.source),
        )
        .join("\n");

      const banner =
        `(function(){` +
        `if(typeof document==="undefined")return;` +
        `if(document.querySelector("style[data-datapaw-ui-plugin]"))return;` +
        `var s=document.createElement("style");` +
        `s.setAttribute("data-datapaw-ui-plugin","true");` +
        `s.textContent=${JSON.stringify(css)};` +
        `document.head.appendChild(s);` +
        `})();\n`;

      entryChunk.code = banner + entryChunk.code;
      for (const [name] of cssAssets) delete bundle[name];
    },
  };
}

export default defineConfig({
  define: {
    VITE_API_BASE_URL: JSON.stringify(""),
    TOKEN: JSON.stringify(""),
    MOBILE: false,
    __DATAPAW_PLUGIN_EMBED__: true,
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  plugins: [react(), inlineCssAsStyleTag()],
  css: {
    modules: {
      localsConvention: "camelCase",
      generateScopedName: "datapaw__[name]__[local]__[hash:base64:5]",
    },
    preprocessorOptions: {
      less: { javascriptEnabled: true },
    },
  },
  resolve: {
    alias: [
      { find: "@", replacement: frontendSrc },
      { find: /^react$/, replacement: path.resolve(frontendSrc, "shims/react.ts") },
      {
        find: /^react-dom$/,
        replacement: path.resolve(frontendSrc, "shims/react-dom.ts"),
      },
      {
        find: /^react-dom\/client$/,
        replacement: path.resolve(frontendSrc, "shims/react-dom-client.ts"),
      },
      {
        find: /^react\/jsx-runtime$/,
        replacement: path.resolve(frontendSrc, "shims/react-jsx-runtime.ts"),
      },
      {
        find: /^react\/jsx-dev-runtime$/,
        replacement: path.resolve(frontendSrc, "shims/react-jsx-runtime.ts"),
      },
    ],
  },
  build: {
    lib: {
      entry: r("src/index.ts"),
      formats: ["es"],
      fileName: () => "index.js",
    },
    outDir: r("dist"),
    emptyOutDir: true,
    cssCodeSplit: false,
    sourcemap: false,
    chunkSizeWarningLimit: 8000,
    rollupOptions: {
      external: [],
      output: { inlineDynamicImports: true },
    },
  },
});
