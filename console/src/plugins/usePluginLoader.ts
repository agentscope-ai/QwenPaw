/** Frontend plugin loading utilities. */

import { getApiToken, getApiUrl } from "../api/config";
import { removePluginRuntime } from "./pluginRuntimeCleanup";
import { routeRegistry } from "./registry/store";
import { subscribeToPluginChanges } from "../utils/pluginChangeEvents";
import { harnessRegistry, refreshHarnessCatalog } from "./harnesses";

interface FrontendPluginInfo {
  id: string;
  name: string;
  plugin_type?: string;
  frontend_entry?: string;
  enabled?: boolean;
  status?: string;
  harnesses?: string[];
}

export interface PluginLoadSummary {
  loaded: number;
  failed: string[];
}

const loadingPlugins = new Map<string, Promise<void>>();
let revision = 0;
let stopChanges: (() => void) | undefined;

function watchChanges(): void {
  if (stopChanges) return;
  const reconcile = () => {
    harnessRegistry.invalidateCatalog();
    void refreshHarnessCatalog()
      .then(async () => {
        const pending = new Set<string>();
        for (const row of harnessRegistry.getSnapshot()) {
          if (!row.plugin_id) continue;
          if (row.status !== "available") removePluginRuntime(row.plugin_id);
          else if (!harnessRegistry.getSettings(row.id))
            pending.add(row.plugin_id);
        }
        await Promise.allSettled([...pending].map(reloadFrontendPlugin));
      })
      .catch((error) =>
        console.warn("[PluginLoader] catalog refresh failed:", error),
      );
  };
  const stopPlugins = subscribeToPluginChanges(() => {
    revision += 1;
    reconcile();
  });
  window.addEventListener("qwenpaw:auth-changed", reconcile);
  stopChanges = () => {
    stopPlugins();
    window.removeEventListener("qwenpaw:auth-changed", reconcile);
  };
}

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

function canExecute(plugin: FrontendPluginInfo): boolean {
  if (
    !plugin.frontend_entry ||
    plugin.enabled === false ||
    (plugin.status !== undefined && plugin.status !== "active")
  )
    return false;
  const catalog = harnessRegistry.getSnapshot();
  const declared =
    plugin.harnesses ??
    catalog.filter((row) => row.plugin_id === plugin.id).map((row) => row.id);
  return declared.every((id) =>
    catalog.some(
      (row) =>
        row.id === id &&
        row.plugin_id === plugin.id &&
        row.status === "available",
    ),
  );
}

async function executePluginScript(plugin: FrontendPluginInfo): Promise<void> {
  const started = revision;
  const harness =
    Boolean(plugin.harnesses?.length) ||
    harnessRegistry.getSnapshot().some((row) => row.plugin_id === plugin.id);
  const entryUrl = resolveUrl(plugin.id, plugin.frontend_entry!);
  const response = await fetch(entryUrl, { headers: authHeaders() });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${entryUrl}`);
  }

  const source = await response.text();
  if (started !== revision) {
    if (!harness) {
      const current = (await fetchFrontendPlugins()).find(
        (item) => item.id === plugin.id,
      );
      if (current && canExecute(current)) return executePluginScript(current);
    }
    throw new Error(`Plugin became unavailable before execution: ${plugin.id}`);
  }
  if (!canExecute(plugin))
    throw new Error(`Plugin became unavailable before execution: ${plugin.id}`);
  const blobUrl = URL.createObjectURL(
    new Blob([source], { type: "application/javascript" }),
  );
  try {
    await import(/* @vite-ignore */ blobUrl);
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
}

/** Load every installed frontend plugin during Console startup. */
export async function loadAllPlugins(): Promise<PluginLoadSummary> {
  watchChanges();
  let plugins: FrontendPluginInfo[];
  try {
    plugins = await fetchFrontendPlugins();
  } catch (error) {
    console.warn("[PluginLoader] failed to fetch plugin list:", error);
    return { loaded: 0, failed: [] };
  }

  // SDK Harness entries require the authoritative active owner snapshot.
  await refreshHarnessCatalog().catch(() => {});
  const loadable = plugins.filter(canExecute);
  const results = await Promise.allSettled(
    loadable.map((plugin) => executePluginScript(plugin)),
  );
  const failed = results.flatMap((result, index) =>
    result.status === "rejected"
      ? [`${loadable[index].id}: ${result.reason}`]
      : [],
  );
  return { loaded: loadable.length - failed.length, failed };
}

interface LoadPluginOptions {
  force?: boolean;
  expectedType?: "app";
  entryPage?: string;
}

function loadFrontendPlugin(
  pluginId: string,
  options: LoadPluginOptions = {},
): Promise<void> {
  watchChanges();
  const pending = loadingPlugins.get(pluginId);
  if (pending) return pending;
  const registered = () =>
    routeRegistry
      .snapshot()
      .some(
        (route) =>
          route.source === pluginId &&
          route.path.startsWith("/apps/") &&
          (!options.entryPage || route.path === options.entryPage),
      );

  if (!options.force && options.expectedType === "app" && registered()) {
    return Promise.resolve();
  }

  const promise = (async () => {
    const plugins = await fetchFrontendPlugins();
    const plugin = plugins.find((item) => item.id === pluginId);
    if (!plugin?.frontend_entry) {
      removePluginRuntime(pluginId);
      if (options.expectedType === "app") {
        throw new Error(`PawApp frontend plugin not found: ${pluginId}`);
      }
      return;
    }
    if (options.expectedType && plugin.plugin_type !== options.expectedType) {
      throw new Error(`PawApp frontend plugin not found: ${pluginId}`);
    }
    if (options.force) removePluginRuntime(pluginId);
    try {
      await refreshHarnessCatalog().catch(() => {});
      if (!canExecute(plugin)) {
        removePluginRuntime(pluginId);
        if (options.expectedType === "app")
          throw new Error(`PawApp frontend plugin is unavailable: ${pluginId}`);
        return;
      }
      await executePluginScript(plugin);
      if (options.expectedType === "app" && !registered()) {
        throw new Error(`PawApp ${pluginId} did not register its app route`);
      }
    } catch (error) {
      removePluginRuntime(pluginId);
      throw error;
    }
  })().finally(() => {
    loadingPlugins.delete(pluginId);
  });

  loadingPlugins.set(pluginId, promise);
  return promise;
}

/** Load one newly installed PawApp without reloading the page. */
export function loadPawApp(
  appId: string,
  entryPage?: string,
  options: { force?: boolean } = {},
): Promise<void> {
  if (options.force) return reloadPawApp(appId, entryPage);
  const pending = loadingPlugins.get(appId);
  if (pending) return pending;
  return loadFrontendPlugin(appId, {
    expectedType: "app",
    entryPage,
    force: options.force,
  });
}

/** Force reload an installed PawApp after an update. */
export function reloadPawApp(appId: string, entryPage?: string): Promise<void> {
  const pending = loadingPlugins.get(appId);
  if (pending) {
    return pending.then(() =>
      loadFrontendPlugin(appId, {
        expectedType: "app",
        entryPage,
        force: true,
      }),
    );
  }
  return loadFrontendPlugin(appId, {
    expectedType: "app",
    entryPage,
    force: true,
  });
}

/** Reload a frontend plugin after installation or update. */
export function reloadFrontendPlugin(pluginId: string): Promise<boolean> {
  const pending = loadingPlugins.get(pluginId);
  if (pending) {
    return pending
      .catch(() => {})
      .then(() =>
        loadFrontendPlugin(pluginId, { force: true }).then(() => true),
      );
  }
  return loadFrontendPlugin(pluginId, { force: true }).then(() => true);
}

/** Reset pending loads between unit tests. */
export function resetPawAppLoaderForTests(): void {
  loadingPlugins.clear();
  stopChanges?.();
  stopChanges = undefined;
  revision = 0;
}
