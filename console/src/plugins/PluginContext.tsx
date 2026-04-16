/**
 * PluginContext.tsx
 *
 * Reactive plugin context for the host application.
 *
 * ─ Architecture ─────────────────────────────────────────────────────────────────
 *
 *  Plugin bundles execute → call register_routes / register_tool_render
 *        ↓
 *  PluginSystem singleton (hostExternals.ts) — stores data + notifies listeners
 *        ↓
 *  PluginProvider subscribes via pluginSystem.subscribe()
 *        ↓
 *  usePlugins() — consumed by Chat, Sidebar, MainLayout
 *
 * ─ Consumer API ─────────────────────────────────────────────────────────────────
 *
 *  const { toolRenderConfig, pluginRoutes, loading, error } = usePlugins();
 */

import React, { createContext, useContext, useEffect, useState } from "react";
import { pluginSystem } from "./hostExternals";
import { loadAllPlugins } from "./usePluginLoader";
import type { PluginRouteDeclaration } from "./hostExternals";

// ─────────────────────────────────────────────────────────────────────────────
// Context shape
// ─────────────────────────────────────────────────────────────────────────────

export interface PluginContextValue {
  /** Map of tool-name → React component. Pass to `@agentscope-ai/chat`. */
  toolRenderConfig: Record<string, React.FC<any>>;
  /** Page routes registered by plugins. Inject into the router + sidebar. */
  pluginRoutes: PluginRouteDeclaration[];
  /** True until the initial plugin-load attempt completes. */
  loading: boolean;
  /** Non-null if one or more plugins failed to load. */
  error: string | null;
}

const PluginContext = createContext<PluginContextValue>({
  toolRenderConfig: {},
  pluginRoutes: [],
  loading: true,
  error: null,
});

// ─────────────────────────────────────────────────────────────────────────────
// Provider
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Wrap your application root with `<PluginProvider>` once.
 * All descendants can then call `usePlugins()` to access plugin-registered
 * routes and tool renderers.
 */
export function PluginProvider({ children }: { children: React.ReactNode }) {
  const [toolRenderConfig, setToolRenderConfig] = useState<
    Record<string, React.FC<any>>
  >(pluginSystem.getToolRenderConfig());
  const [pluginRoutes, setPluginRoutes] = useState<PluginRouteDeclaration[]>(
    pluginSystem.getRoutes(),
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Re-sync state whenever any plugin registers new capabilities
    const unsub = pluginSystem.subscribe(() => {
      setToolRenderConfig(pluginSystem.getToolRenderConfig());
      setPluginRoutes(pluginSystem.getRoutes());
    });

    // Load all installed plugins (non-fatal: one bad plugin won’t block others)
    loadAllPlugins().then(({ failed }) => {
      if (failed.length > 0) setError(failed.join("; "));
      setLoading(false);
    });

    return unsub;
  }, []);

  return (
    <PluginContext.Provider
      value={{ toolRenderConfig, pluginRoutes, loading, error }}
    >
      {children}
    </PluginContext.Provider>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Consumer hook
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Consume the global plugin context.
 *
 * ```tsx
 * const { toolRenderConfig, pluginRoutes, loading } = usePlugins();
 * ```
 */
export function usePlugins(): PluginContextValue {
  return useContext(PluginContext);
}
