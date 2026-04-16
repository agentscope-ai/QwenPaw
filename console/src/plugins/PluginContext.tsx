import { createContext, useContext } from "react";
import { usePluginLoader, type PluginLoaderResult } from "./usePluginLoader";

const PluginContext = createContext<PluginLoaderResult>({
  toolRenderConfig: {},
  pluginRoutes: [],
  loading: true,
  error: null,
});

/**
 * Wraps the application to load all plugins once and share the result
 * (tool render config + page routes) with any descendant via `usePlugins()`.
 */
export function PluginProvider({ children }: { children: React.ReactNode }) {
  const value = usePluginLoader();

  return (
    <PluginContext.Provider value={value}>{children}</PluginContext.Provider>
  );
}

/**
 * Consume the global plugin context.
 *
 * - `toolRenderConfig` — pass to `@agentscope-ai/chat` for custom tool rendering.
 * - `pluginRoutes` — inject into the router and sidebar for page-level plugins.
 */
export function usePlugins(): PluginLoaderResult {
  return useContext(PluginContext);
}
