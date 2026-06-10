// -----------------------------------------------------------------------------
// DataPaw plugin frontend — Vite build config
//
// This is the build for the *plugin bundle* that gets shipped at
// `plugins/bundle/datapaw/dist/index.js` and is dynamically `import()`-ed
// by the host console at runtime via a same-origin Blob URL.
//
// Key constraints (mirrors plugins/bundle/qwenpaw-pet/frontend/vite.config.ts
// and PLUGIN_REFACTOR.md):
//
//   1. The bundle MUST NOT contain a second copy of React. Two Reacts in
//      the same window = "Invalid Hook Call". So `react` / `react-dom` /
//      `react-dom/client` / `react/jsx-runtime` / `react/jsx-dev-runtime`
//      are *aliased* to shim files under `src/shims/` that simply re-export
//      from `window.QwenPaw.host.React` / `.ReactDOM`.
//
//   2. The bundle is loaded via `import(blobUrl)` so any bare specifier
//      left in the output (e.g. `import x from "antd"`) would fail to
//      resolve — there is no importmap. Therefore antd, @ant-design/icons,
//      react-router-dom, i18next, @agentscope-ai/*, dayjs, etc. are all
//      bundled in. Yes the bundle is multi-MB; this is the cost of
//      packaging a full standalone SPA as a plugin.
//
//   3. The plugin loader executes the bundle inside the already-running
//      host console, so `document` / `window` are real. The bundle itself
//      does NOT call `createRoot()` — it registers a *route* via
//      `window.QwenPaw.registerRoutes(...)` (see src/index.tsx) and the
//      host mounts our App component when the user navigates to it.
// -----------------------------------------------------------------------------

import react from "@vitejs/plugin-react";
import path from "path";
import { defineConfig, type Plugin } from "vite";
import { fileURLToPath, URL } from "url";

const r = (p: string) => fileURLToPath(new URL(p, import.meta.url));

/**
 * Inline every emitted CSS asset into the entry chunk as a runtime
 * `<style>` tag injection, then delete the original CSS asset.
 *
 * The plugin loader (`console/src/plugins/usePluginLoader.ts`) only fetches
 * `dist/index.js` via Blob URL + dynamic `import()`; sibling files like
 * `dist/style.css` are never loaded. Without inlining we end up with an
 * unstyled antd, broken layouts, etc. — exactly the symptom we want to
 * avoid.
 *
 * The injection is a no-op on the server (SSR / pre-render), idempotent
 * across re-evaluations (data-attribute guard), and lazy-safe (runs at
 * import time, before any component mounts).
 */
function inlineCssAsStyleTag(): Plugin {
  return {
    name: "datapaw:inline-css",
    enforce: "post",
    generateBundle(_options, bundle) {
      const cssAssets = Object.entries(bundle).filter(
        ([name, asset]) => asset.type === "asset" && name.endsWith(".css"),
      ) as [string, { type: "asset"; source: string | Uint8Array }][];
      if (cssAssets.length === 0) return;

      const entryChunk = Object.values(bundle).find(
        (c) => c.type === "chunk" && (c as any).isEntry,
      ) as { type: "chunk"; code: string } | undefined;
      if (!entryChunk) return;

      // Concatenate all CSS sources (preserve order — vite emits in deps order).
      const css = cssAssets
        .map(([, asset]) =>
          typeof asset.source === "string"
            ? asset.source
            : new TextDecoder().decode(asset.source),
        )
        .join("\n");

      const cssLiteral = JSON.stringify(css);
      const banner =
        `(function(){` +
        `if(typeof document==="undefined")return;` +
        `if(document.querySelector("style[data-datapaw-plugin]"))return;` +
        `var s=document.createElement("style");` +
        `s.setAttribute("data-datapaw-plugin","true");` +
        `s.textContent=${cssLiteral};` +
        `document.head.appendChild(s);` +
        `})();\n`;

      entryChunk.code = banner + entryChunk.code;

      for (const [name] of cssAssets) {
        delete bundle[name];
      }
    },
  };
}

export default defineConfig({
  // -------------------------------------------------------------------------
  // Build-time defines
  //
  // The upstream `api/config.ts` declares two ambient consts (VITE_API_BASE_URL
  // and TOKEN) that the host console replaces via `vite define`. We keep them
  // empty here so the plugin always speaks to the same origin and reads the
  // bearer from localStorage (which the host wrote at login). `MOBILE` is a
  // legacy flag the source code references in a couple of places.
  // -------------------------------------------------------------------------
  define: {
    VITE_API_BASE_URL: JSON.stringify(""),
    TOKEN: JSON.stringify(""),
    MOBILE: false,
    // This package only ships as a QwenPaw plugin bundle — never hide layout
    // based on URL alone (host may nest routes differently).
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
      less: {
        javascriptEnabled: true,
      },
    },
  },

  resolve: {
    // Use the *array* form so we can mix prefix aliases (`@/...`) with
    // exact-match regex aliases for the React entries. The object form
    // does prefix matching for every key, which silently rewrites
    // `react/jsx-runtime` to `<react.ts>/jsx-runtime` and breaks the
    // build with `ENOTDIR: not a directory, open '…/react.ts/jsx-runtime'`.
    alias: [
      // Console source uses the `@/` alias heavily — keep prefix matching
      // so `@/api/foo` resolves to `<absSrc>/api/foo`.
      { find: "@", replacement: path.resolve(r("./src")) },
      // The host-chat embed reuses small pieces from the lightweight plugin UI.
      { find: "@datapaw/ui", replacement: path.resolve(r("../ui/src")) },

      // Externalise React to the host so we never have two Reacts.
      // The shim files re-export every public React API from
      // `window.QwenPaw.host.React` / `.ReactDOM`.
      //
      // IMPORTANT: each regex must be anchored ($) so prefix matches like
      // `react/jsx-runtime` are NOT eaten by the bare-`react` alias.
      { find: /^react$/, replacement: r("./src/shims/react.ts") },
      { find: /^react-dom$/, replacement: r("./src/shims/react-dom.ts") },
      {
        find: /^react-dom\/client$/,
        replacement: r("./src/shims/react-dom-client.ts"),
      },
      {
        find: /^react\/jsx-runtime$/,
        replacement: r("./src/shims/react-jsx-runtime.ts"),
      },
      {
        find: /^react\/jsx-dev-runtime$/,
        replacement: r("./src/shims/react-jsx-runtime.ts"),
      },
    ],
  },

  build: {
    // Library mode → single `dist/index.js` next to plugin.json's
    // `entry.frontend` declaration.
    lib: {
      entry: r("./src/index.ts"),
      formats: ["es"],
      fileName: () => "index.js",
    },
    outDir: r("../dist"),
    emptyOutDir: true,
    cssCodeSplit: false,
    sourcemap: false,
    chunkSizeWarningLimit: 6000,
    rollupOptions: {
      // We bundle everything else (antd, @ant-design/icons, @agentscope-ai/*,
      // react-router-dom, i18next, dayjs, …) since the plugin loader's
      // dynamic `import()` of a blob URL cannot resolve bare specifiers.
      external: [],
      output: {
        // Library mode emits CSS as a sibling asset by default; we inline it
        // through `cssCodeSplit: false` (single `style.css`) and instruct the
        // backend to serve both files from `/api/frontend_plugin/datapaw/`.
        inlineDynamicImports: true,
      },
    },
  },

  optimizeDeps: {
    // Speeds up dev builds for the (rarely used) `npm run dev` watch mode.
    include: ["antd", "react-router-dom", "@ant-design/icons"],
  },
});
