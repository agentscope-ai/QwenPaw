/**
 * `usePluginLoader` — dynamically discovers and loads plugins.
 *
 * ### How it works
 *
 * 1. `GET /api/plugins` → list of plugins with `frontend_entry` URLs.
 * 2. For each plugin with a frontend entry:
 *    a. Fetch + Blob-URL-import the plugin's JS module.
 *    b. The plugin JS calls `window.__registerPlugin(manifest, capabilities)`
 *       to register its routes, tool renderers, etc.
 * 3. After all plugins are loaded, collect registrations from
 *    `window.__pluginRegistrations__` and produce:
 *    - `toolRenderConfig` for `@agentscope-ai/chat`
 *    - `pluginRoutes` for the router and sidebar
 *
 * ### Plugin JS module contract
 *
 * ```js
 * (window as any).__registerPlugin?.(
 *   { name: "my-plugin", version: "1.0.0" },
 *   {
 *     routes: [{ path: "/dashboard", component: Dashboard, label: "Dashboard", icon: "📊" }],
 *     toolRenderers: { "view_image": ViewImageCard },
 *   },
 * );
 * ```
 */

import { useEffect, useRef, useState } from "react";
import type React from "react";
import { fetchPlugins, type PluginInfo } from "../api/modules/plugin";
import type { PluginRegistration } from "./hostExternals";

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

/**
 * Fetch a plugin's JS source, wrap it in a same-origin Blob URL, and
 * execute it.  The plugin JS is expected to call
 * `window.__registerPlugin(manifest, capabilities)` during execution.
 */
async function loadPluginScript(entryUrl: string): Promise<void> {
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
    await import(/* @vite-ignore */ blobUrl);
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
}

/**
 * Process accumulated plugin registrations from
 * `window.__pluginRegistrations__` into tool render configs and page routes.
 */
function processRegistrations(registrations: PluginRegistration[]): {
  toolConfig: ToolRenderConfig;
  routes: PluginPageRoute[];
} {
  const toolConfig: ToolRenderConfig = {};
  const routes: PluginPageRoute[] = [];

  for (const { manifest, capabilities } of registrations) {
    const pluginName = manifest.name;

    // Process tool renderers
    if (capabilities.toolRenderers) {
      for (const [toolName, component] of Object.entries(
        capabilities.toolRenderers,
      )) {
        if (typeof component === "function") {
          toolConfig[toolName] = component;
          console.info(`[plugin:${pluginName}] Mapped tool "${toolName}"`);
        }
      }
    }

    // Process routes
    if (capabilities.routes) {
      for (const route of capabilities.routes) {
        if (typeof route.component === "function") {
          routes.push({
            path: route.path.startsWith("/")
              ? route.path
              : `/plugin/${pluginName}/${route.path}`,
            label: route.label,
            icon: route.icon || "🔌",
            component: route.component,
          });
          console.info(
            `[plugin:${pluginName}] Registered route "${route.path}"`,
          );
        }
      }
    }
  }

  return { toolConfig, routes };
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
        // Clear any previous registrations
        window.__pluginRegistrations__ = [];

        const plugins = await fetchPlugins();
        const frontendPlugins = plugins.filter(
          (plugin: PluginInfo) => plugin.has_frontend && plugin.frontend_entry,
        );

        if (frontendPlugins.length === 0) {
          setLoading(false);
          return;
        }

        const errors: string[] = [];

        // Load all plugin scripts — each calls __registerPlugin internally
        await Promise.allSettled(
          frontendPlugins.map(async (plugin: PluginInfo) => {
            try {
              await loadPluginScript(resolvePluginUrl(plugin.frontend_entry!));
            } catch (err) {
              const message = `Plugin "${plugin.id}" failed to load: ${err}`;
              console.error(`[plugin] ${message}`);
              errors.push(message);
            }
          }),
        );

        if (!cancelled) {
          // Collect all registrations made by plugins
          const registrations = window.__pluginRegistrations__ || [];
          const { toolConfig, routes } = processRegistrations(registrations);

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
