/**
 * PluginContext.tsx
 *
 * Reactive plugin context for the host application.
 * Subscribes to the PluginSystem singleton and exposes plugin-registered
 * routes and tool renderers to any component via usePlugins().
 *
 *  const { toolRenderConfig, pluginRoutes, loading, error } = usePlugins();
 */

import React, { createContext, useContext, useEffect, useState } from "react";
import { pluginSystem } from "./hostExternals";
import { loadAllPlugins } from "./usePluginLoader";
import type { PluginRouteDeclaration } from "./hostExternals";
import {
  routeRegistry,
  subscribe as registrySubscribe,
} from "./registry/store";

/** Derive the legacy PluginRouteDeclaration[] shape from routeRegistry. */
function derivePluginRoutes(): PluginRouteDeclaration[] {
  // Include both legacy (registerRoutes shim) routes and any new route.add
  // registrations from a plugin source. Built-in `core.*` routes are excluded.
  return routeRegistry
    .snapshot()
    .filter((r) => r.source !== "core")
    .map((r) => ({
      path: r.path,
      component: r.Component,
      label: r.id,
      icon: "",
    }));
}

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
    derivePluginRoutes(),
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Re-sync state whenever any plugin registers new capabilities — both
    // the legacy pluginSystem (toolRenderers) and the new registry
    // (routes via shim + direct route.add) notify on change.
    const unsubA = pluginSystem.subscribe(() => {
      setToolRenderConfig(pluginSystem.getToolRenderConfig());
    });
    const unsubB = registrySubscribe(() => {
      setPluginRoutes(derivePluginRoutes());
    });

    // Load all installed plugins and PawApps (non-fatal: one bad module
    // won’t block others). PawApps are 'app'-type plugins: the loader
    // executes their ui bundle, which self-registers the /apps/{id} route
    // so the App Center can render them inline.
    loadAllPlugins().then(({ failed }) => {
      if (failed.length > 0) setError(failed.join("; "));
      setLoading(false);
    });

    return () => {
      unsubA();
      unsubB();
    };
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
