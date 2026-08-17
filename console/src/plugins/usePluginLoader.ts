/** Frontend plugin loading utilities. */

import { getApiToken, getApiUrl } from "../api/config";
import { removePluginRuntime } from "./pluginRuntimeCleanup";
import { routeRegistry } from "./registry/store";

interface FrontendPluginInfo {
  id: string;
  name: string;
  plugin_type?: string;
  frontend_entry?: string;
}

export interface PluginLoadSummary {
  loaded: number;
  failed: string[];
}

const loadingApps = new Map<string, Promise<void>>();

function authHeaders(): Record<string, string> {
  const token = getApiToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function resolveUrl(pluginId: string, apiPath: string): string {
  return getApiUrl(`frontend_plugin/${pluginId}/files/${apiPath}`);
}

async function fetchFrontendPlugins(): Promise<FrontendPluginInfo[]> {
  const response = await fetch(getApiUrl("/frontend_plugin"), {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Failed to list frontend plugins (${response.status})`);
  }
  return response.json();
}

async function executePluginScript(entryUrl: string): Promise<void> {
  const response = await fetch(entryUrl, { headers: authHeaders() });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${entryUrl}`);
  }

  const blobUrl = URL.createObjectURL(
    new Blob([await response.text()], { type: "application/javascript" }),
  );
  try {
    await import(/* @vite-ignore */ blobUrl);
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
}

/** Load every installed frontend plugin during Console startup. */
export async function loadAllPlugins(): Promise<PluginLoadSummary> {
  let plugins: FrontendPluginInfo[];
  try {
    plugins = await fetchFrontendPlugins();
  } catch (error) {
    console.warn("[PluginLoader] failed to fetch plugin list:", error);
    return { loaded: 0, failed: [] };
  }

  const loadable = plugins.filter((plugin) => plugin.frontend_entry);
  const results = await Promise.allSettled(
    loadable.map((plugin) =>
      executePluginScript(resolveUrl(plugin.id, plugin.frontend_entry!)),
    ),
  );
  const failed = results.flatMap((result, index) =>
    result.status === "rejected"
      ? [`${loadable[index].id}: ${result.reason}`]
      : [],
  );
  return { loaded: loadable.length - failed.length, failed };
}

/** Load one newly installed PawApp without reloading the page. */
export function loadPawApp(appId: string, entryPage?: string): Promise<void> {
  const registered = () =>
    routeRegistry
      .snapshot()
      .some(
        (route) =>
          route.source === appId &&
          route.path.startsWith("/apps/") &&
          (!entryPage || route.path === entryPage),
      );
  if (registered()) return Promise.resolve();

  const pending = loadingApps.get(appId);
  if (pending) return pending;

  const promise = (async () => {
    const plugins = await fetchFrontendPlugins();
    const plugin = plugins.find((item) => item.id === appId);
    if (!plugin?.frontend_entry || plugin.plugin_type !== "app") {
      throw new Error(`PawApp frontend plugin not found: ${appId}`);
    }

    try {
      await executePluginScript(resolveUrl(plugin.id, plugin.frontend_entry));
      if (!registered()) {
        throw new Error(`PawApp ${appId} did not register its app route`);
      }
    } catch (error) {
      removePluginRuntime(appId);
      throw error;
    }
  })().finally(() => {
    loadingApps.delete(appId);
  });

  loadingApps.set(appId, promise);
  return promise;
}

/** Reset pending loads between unit tests. */
export function resetPawAppLoaderForTests(): void {
  loadingApps.clear();
}
