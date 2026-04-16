/**
 * `usePluginLoader` — dynamically discovers plugins that ship a frontend UI,
 * loads their JS/CSS assets at runtime, and produces:
 *
 * - A `customToolRenderConfig` map ready for `@agentscope-ai/chat`.
 * - A `pluginRoutes` array of page-level routes that plugins declare.
 *
 * ### How it works
 *
 * 1. `GET /api/plugins` → list of plugins with `ui` metadata, including
 *    `js_tool_renderers` mapping and `pages` declarations.
 * 2. For each plugin whose `has_ui === true`:
 *    a. Inject `<link rel="stylesheet">` for the plugin's CSS (if any).
 *    b. Fetch + Blob-URL-import the plugin's JS entry module.
 *    c. Call the module's default export `register(host)` which returns
 *       an object mapping component names to React components.
 *    d. Wire tool renderers and page routes using the exported components.
 * 3. Return `{ toolRenderConfig, pluginRoutes, loading, error }`.
 *
 * ### Plugin JS module contract
 *
 * ```js
 * export default function register(host) {
 *   const { React } = host;
 *   const h = React.createElement;
 *
 *   function MyCard(props) { return h("div", null, "Hello!"); }
 *   function DashboardPage() { return h("div", null, "Dashboard"); }
 *
 *   // Return components by name — the backend decides which tool/page
 *   // uses which component via plugin.json declarations.
 *   return { MyCard, DashboardPage };
 * }
 * ```
 */

import { useEffect, useRef, useState } from "react";
import type React from "react";
import { fetchPlugins, type PluginInfo } from "../api/modules/plugin";

declare const VITE_API_BASE_URL: string;

/**
 * Resolve a backend-relative URL (e.g. `/api/plugins/…/index.js`) to a full
 * URL that works in both dev mode (Vite dev server on a different port) and
 * production (same origin).
 */
function resolvePluginUrl(backendPath: string): string {
  const base =
    typeof VITE_API_BASE_URL !== "undefined" ? VITE_API_BASE_URL : "";
  if (!base) return backendPath;
  return `${base}${backendPath}`;
}

export type ToolRenderConfig = Record<string, React.FC<any>>;

/**
 * A resolved plugin page route with the actual React component attached.
 */
export interface PluginPageRoute {
  /** Full URL path, e.g. "/plugin/my-plugin/dashboard". */
  path: string;
  /** Display label for the sidebar menu. */
  label: string;
  /** Emoji or short text used as the sidebar icon. */
  icon: string;
  /** The resolved React component to render at this route. */
  component: React.ComponentType;
}

/**
 * The `host` object passed to each plugin's `register(host)` function.
 * Plugins use it to access shared dependencies (React, antd, etc.).
 *
 * The `register` function should **return** an object whose keys are
 * component names and values are React components.  The backend
 * `js_tool_renderers` mapping decides which tool uses which component.
 */
export interface PluginHost {
  /** React library (same instance as the host app). */
  React: typeof import("react");
  /** ReactDOM library. */
  ReactDOM: typeof import("react-dom");
  /** antd component library. */
  antd: typeof import("antd");
  /** @ant-design/icons. */
  antdIcons: typeof import("@ant-design/icons");
  /** API base URL (e.g. "http://localhost:8001" or ""). */
  apiBaseUrl: string;
  /** Build a full API URL from a relative path. */
  getApiUrl: (path: string) => string;
  /** Get the current auth token. */
  getApiToken: () => string;
}

export interface PluginLoaderResult {
  /** Map of tool name → React component, ready for customToolRenderConfig. */
  toolRenderConfig: ToolRenderConfig;
  /** Page-level routes registered by plugins. */
  pluginRoutes: PluginPageRoute[];
  /** True while plugins are being fetched / loaded. */
  loading: boolean;
  /** Non-null if any plugin failed to load (others may still succeed). */
  error: string | null;
}

/** Track injected CSS <link> elements so we can clean up. */
const injectedStylesheets = new Map<string, HTMLLinkElement>();

function injectCSS(pluginId: string, cssUrl: string): void {
  if (injectedStylesheets.has(pluginId)) return;

  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = cssUrl;
  link.dataset.pluginId = pluginId;
  document.head.appendChild(link);
  injectedStylesheets.set(pluginId, link);
}

/**
 * The return type of a plugin's `register(host)` function: an object
 * mapping component names to React components.
 */
type PluginComponentMap = Record<string, React.FC<any>>;

/**
 * Fetch a plugin's JS source, wrap it in a same-origin Blob URL, and
 * `import()` it.  This avoids CORS issues when the frontend dev server
 * and the backend run on different origins.
 */
async function loadPluginModule(
  entryUrl: string,
): Promise<(host: PluginHost) => PluginComponentMap> {
  const response = await fetch(entryUrl);
  if (!response.ok) {
    throw new Error(
      `HTTP ${response.status} ${response.statusText} for ${entryUrl}`,
    );
  }

  const jsText = await response.text();
  const blob = new Blob([jsText], { type: "application/javascript" });
  const blobUrl = URL.createObjectURL(blob);

  try {
    const module = await import(/* @vite-ignore */ blobUrl);
    const registerFn = module.default ?? module;

    if (typeof registerFn !== "function") {
      throw new TypeError(
        `Plugin module must default-export a register(host) function, ` +
          `got ${typeof registerFn}`,
      );
    }

    return registerFn;
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
}

/**
 * Build a `PluginHost` object that plugins receive in their `register(host)`
 * call.  Provides shared dependencies only — component registration is
 * handled by the loader based on the backend mappings.
 */
function createPluginHost(): PluginHost {
  const externals = window.__QWENPAW__;

  return {
    React: externals.React,
    ReactDOM: externals.ReactDOM,
    antd: externals.antd,
    antdIcons: externals.antdIcons,
    apiBaseUrl: externals.apiBaseUrl,
    getApiUrl: externals.getApiUrl,
    getApiToken: externals.getApiToken,
  };
}

export function usePluginLoader(): PluginLoaderResult {
  const [toolRenderConfig, setToolRenderConfig] = useState<ToolRenderConfig>(
    {},
  );
  const [pluginRoutes, setPluginRoutes] = useState<PluginPageRoute[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loadedRef = useRef(false);

  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;

    let cancelled = false;

    async function loadAllPlugins() {
      try {
        const plugins = await fetchPlugins();
        const uiPlugins = plugins.filter(
          (plugin: PluginInfo) => plugin.has_ui && plugin.ui,
        );

        if (uiPlugins.length === 0) {
          setLoading(false);
          return;
        }

        const toolConfig: ToolRenderConfig = {};
        const routes: PluginPageRoute[] = [];
        const errors: string[] = [];

        await Promise.allSettled(
          uiPlugins.map(async (plugin: PluginInfo) => {
            const ui = plugin.ui!;

            try {
              // 1. Inject CSS (if any)
              if (ui.css) {
                injectCSS(plugin.id, resolvePluginUrl(ui.css));
              }

              // 2. Load the plugin JS module
              const registerFn = await loadPluginModule(
                resolvePluginUrl(ui.entry),
              );

              // 3. Call register(host) — get exported components
              const host = createPluginHost();
              const exportedComponents = registerFn(host) || {};

              // 4. Wire tool renderers via backend js_tool_renderers mapping
              const jsToolRenderers = ui.js_tool_renderers || {};
              for (const [toolName, componentName] of Object.entries(
                jsToolRenderers,
              )) {
                const component = exportedComponents[componentName];
                if (typeof component === "function") {
                  toolConfig[toolName] = component;
                  console.info(
                    `[plugin:${plugin.id}] Mapped tool "${toolName}" -> component "${componentName}"`,
                  );
                } else {
                  console.warn(
                    `[plugin:${plugin.id}] js_tool_renderers declares "${toolName}" -> "${componentName}", ` +
                      `but register() did not return a component named "${componentName}"`,
                  );
                }
              }

              // 5. Wire page routes via backend pages declaration
              const pages = ui.pages || [];
              for (const page of pages) {
                const component = exportedComponents[page.component];
                if (typeof component === "function") {
                  routes.push({
                    path: `/plugin/${plugin.id}/${page.path}`,
                    label: page.label,
                    icon: page.icon || "🔌",
                    component,
                  });
                  console.info(
                    `[plugin:${plugin.id}] Registered page route "/plugin/${plugin.id}/${page.path}" -> "${page.component}"`,
                  );
                } else {
                  console.warn(
                    `[plugin:${plugin.id}] pages declares component "${page.component}" for path "${page.path}", ` +
                      `but register() did not return a component with that name`,
                  );
                }
              }
            } catch (err) {
              const message = `Plugin "${plugin.id}" failed to load: ${err}`;
              console.error(`[plugin] ${message}`);
              errors.push(message);
            }
          }),
        );

        if (!cancelled) {
          setToolRenderConfig(toolConfig);
          setPluginRoutes(routes);
          if (errors.length > 0) {
            setError(errors.join("; "));
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(`Failed to fetch plugin list: ${err}`);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadAllPlugins();

    return () => {
      cancelled = true;
    };
  }, []);

  return { toolRenderConfig, pluginRoutes, loading, error };
}
