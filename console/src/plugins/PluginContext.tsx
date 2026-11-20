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
import { pluginSystem } from "./pluginSystem";
import {
  loadAllPlugins,
  resetLoadedPlugins,
  watchPluginAccess,
} from "./usePluginLoader";
import type { PluginRouteDeclaration } from "./pluginSystem";
import {
  routeRegistry,
  subscribe as registrySubscribe,
} from "./registry/store";
import { useAuthStore } from "@/stores/authStore";
import {
  getAgentAccessScopeKey,
  subscribeChatSessionScope,
} from "../stores/chatSessionScope";

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
  const authMode = useAuthStore((state) => state.mode);
  const authPhase = useAuthStore((state) => state.phase);
  const authenticatedUserId = useAuthStore((state) => state.user?.id);
  const [toolRenderConfig, setToolRenderConfig] = useState<
    Record<string, React.FC<any>>
  >(pluginSystem.getToolRenderConfig());
  const [pluginRoutes, setPluginRoutes] = useState<PluginRouteDeclaration[]>(
    derivePluginRoutes(),
  );
  const loadScope = React.useSyncExternalStore(
    subscribeChatSessionScope,
    getAgentAccessScopeKey,
  );
  const mayLoad =
    authPhase !== "loading" &&
    (authMode === "legacy" ||
      authPhase === "disabled" ||
      (authPhase === "authenticated" && Boolean(authenticatedUserId)));
  const [completedScope, setCompletedScope] = useState<string | null>(null);
  // Gate the first render for a new identity, before effects run. Otherwise
  // business pages briefly mount, start requests, and immediately unmount.
  const loading = mayLoad && completedScope !== loadScope;
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

    return () => {
      unsubA();
      unsubB();
    };
  }, []);

  useEffect(() => {
    resetLoadedPlugins();
    setCompletedScope(null);
    if (!mayLoad) {
      return;
    }
    setError(null);
    const controller = new AbortController();
    loadAllPlugins(controller.signal, (failure) => {
      if (!controller.signal.aborted)
        setError((previous) =>
          previous ? `${previous}; ${failure}` : failure,
        );
    })
      .then(({ failed }) => {
        if (controller.signal.aborted) return;
        if (failed.length > 0)
          setError((previous) =>
            [previous, ...failed].filter(Boolean).join("; "),
          );
        setCompletedScope(loadScope);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setError(String(error));
        setCompletedScope(loadScope);
      });
    const stopWatching = watchPluginAccess(controller.signal);
    return () => {
      controller.abort();
      stopWatching();
    };
  }, [mayLoad, loadScope]);

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
