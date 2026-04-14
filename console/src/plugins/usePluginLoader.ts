/**
 * `usePluginLoader` — dynamically discovers plugins that ship a frontend UI,
 * loads their JS/CSS assets at runtime, and produces a
 * `customToolRenderConfig` map ready for `@agentscope-ai/chat`.
 *
 * ### How it works
 *
 * 1. `GET /api/plugins` → list of plugins with `ui` metadata, including
 *    `tool_renderers` mapping (tool_name → component_name) registered by
 *    the backend `plugin.py` via `api.register_tool_renderer(...)`.
 * 2. For each plugin whose `has_ui === true`:
 *    a. Inject `<link rel="stylesheet">` for the plugin's CSS (if any).
 *    b. Fetch + Blob-URL-import the plugin's JS entry module.
 *    c. Call the module's default export `register(host)` which returns
 *       an object mapping component names to React components.
 *    d. Use the backend `tool_renderers` mapping to look up each
 *       component by name and register it in `toolRenderConfig`.
 * 3. Return `{ toolRenderConfig, loading, error }`.
 *
 * ### Plugin JS module contract
 *
 * ```js
 * export default function register(host) {
 *   const { React } = host;
 *   const h = React.createElement;
 *
 *   function MyCard(props) { return h("div", null, "Hello!"); }
 *
 *   // Return components by name — the backend decides which tool uses which.
 *   return { MyCard };
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
 * The `host` object passed to each plugin's `register(host)` function.
 * Plugins use it to access shared dependencies (React, antd, etc.).
 *
 * The `register` function should **return** an object whose keys are
 * component names and values are React components.  The backend
 * `tool_renderers` mapping decides which tool uses which component.
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

interface PluginLoaderResult {
  /** Map of tool name → React component, ready for customToolRenderConfig. */
  toolRenderConfig: ToolRenderConfig;
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
 * Fetch a plugin's JS source, wrap it in a same-origin Blob URL, and
 * `import()` it.  This avoids CORS issues when the frontend dev server
 * and the backend run on different origins.
 */
/**
 * The return type of a plugin's `register(host)` function: an object
 * mapping component names to React components.
 */
type PluginComponentMap = Record<string, React.FC<any>>;

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
 * handled by the loader based on the backend `tool_renderers` mapping.
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

        const config: ToolRenderConfig = {};
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

              // 4. Use backend tool_renderers mapping to wire components
              const toolRenderers = ui.tool_renderers || {};
              for (const [toolName, componentName] of Object.entries(
                toolRenderers,
              )) {
                const component = exportedComponents[componentName];
                if (typeof component === "function") {
                  config[toolName] = component;
                  console.info(
                    `[plugin:${plugin.id}] Mapped tool "${toolName}" -> component "${componentName}"`,
                  );
                } else {
                  console.warn(
                    `[plugin:${plugin.id}] tool_renderers declares "${toolName}" -> "${componentName}", ` +
                      `but register() did not return a component named "${componentName}"`,
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
          setToolRenderConfig(config);
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

  return { toolRenderConfig, loading, error };
}
