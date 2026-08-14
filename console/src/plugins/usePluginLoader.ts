/**
 * Frontend plugin loading utilities.
 *
 * Global plugins load eagerly during Console startup. PawApp pages load only
 * when the user opens the app, keeping installed state independent from the
 * browser's in-memory route registry.
 */

import { getApiToken, getApiUrl } from "../api/config";
import { routeRegistry } from "./registry/store";
import {
  detachPluginRuntime,
  removePluginRuntime,
} from "./pluginRuntimeCleanup";

interface FrontendPluginInfo {
  id: string;
  name: string;
  version: string;
  plugin_type?: string;
  frontend_entry?: string;
}

export interface PluginLoadSummary {
  loaded: number;
  failed: string[];
}

const loadedApps = new Map<string, string>();
const loadingPromises = new Map<string, Promise<void>>();
const lifecycleGenerations = new Map<string, number>();
const loadControllers = new Map<string, AbortController>();

function generationOf(appId: string): number {
  return lifecycleGenerations.get(appId) ?? 0;
}

function assertCurrentGeneration(appId: string, generation: number): void {
  if (generation !== generationOf(appId)) {
    throw new Error(`PawApp load invalidated: ${appId}`);
  }
}

function authHeaders(): Record<string, string> {
  const token = getApiToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function resolveUrl(pluginId: string, apiPath: string): string {
  return getApiUrl(`frontend_plugin/${pluginId}/files/${apiPath}`);
}

async function fetchFrontendPlugins(
  signal?: AbortSignal,
): Promise<FrontendPluginInfo[]> {
  const response = await fetch(getApiUrl("/frontend_plugin"), {
    headers: authHeaders(),
    signal,
  });
  if (!response.ok) {
    throw new Error(`Failed to list frontend plugins (${response.status})`);
  }
  return response.json();
}

async function executePluginScript(
  entryUrl: string,
  signal?: AbortSignal,
  beforeImport?: () => void,
): Promise<void> {
  const response = await fetch(entryUrl, { headers: authHeaders(), signal });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${entryUrl}`);
  }

  const jsText = await response.text();
  const blobUrl = URL.createObjectURL(
    new Blob([jsText], { type: "application/javascript" }),
  );
  try {
    beforeImport?.();
    await import(/* @vite-ignore */ blobUrl);
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
}

/** Load non-App frontend plugins that provide global Console capabilities. */
export async function loadEagerFrontendPlugins(): Promise<PluginLoadSummary> {
  let plugins: FrontendPluginInfo[];
  try {
    plugins = await fetchFrontendPlugins();
  } catch (error) {
    console.warn("[PluginLoader] failed to fetch plugin list:", error);
    return { loaded: 0, failed: [] };
  }

  const eagerPlugins = plugins.filter(
    (plugin) => plugin.frontend_entry && plugin.plugin_type !== "app",
  );
  const results = await Promise.allSettled(
    eagerPlugins.map(async (plugin) => {
      await executePluginScript(resolveUrl(plugin.id, plugin.frontend_entry!));
      console.info(`[PluginLoader] loaded ${plugin.id}`);
    }),
  );
  const failed: string[] = [];
  results.forEach((result, index) => {
    if (result.status === "rejected") {
      const message = `${eagerPlugins[index].id}: ${result.reason}`;
      console.error(`[PluginLoader] failed ${message}`);
      failed.push(message);
    }
  });
  return { loaded: eagerPlugins.length - failed.length, failed };
}

/** Load and verify one PawApp page bundle on demand. */
export function loadPawApp(
  appId: string,
  entryPage = `/apps/${appId}`,
): Promise<void> {
  const pending = loadingPromises.get(appId);
  if (pending) return pending;

  const generation = generationOf(appId);
  const controller = new AbortController();
  loadControllers.set(appId, controller);

  const promise = (async () => {
    const plugins = await fetchFrontendPlugins(controller.signal);
    assertCurrentGeneration(appId, generation);
    const plugin = plugins.find((item) => item.id === appId);
    if (!plugin) {
      throw new Error(`PawApp frontend plugin not found: ${appId}`);
    }
    if (plugin.plugin_type !== "app") {
      throw new Error(`Plugin is not a PawApp: ${appId}`);
    }
    if (!plugin.frontend_entry) {
      throw new Error(`PawApp has no frontend entry: ${appId}`);
    }

    const loadedVersion = loadedApps.get(appId);
    const versionChanged = Boolean(
      loadedVersion && loadedVersion !== plugin.version,
    );
    const alreadyRegistered = routeRegistry
      .snapshot()
      .some((route) => route.path === entryPage && route.baseSource === appId);

    if (loadedVersion === plugin.version && alreadyRegistered) return;

    const previousRuntime = versionChanged ? detachPluginRuntime(appId) : null;

    try {
      if (!alreadyRegistered || versionChanged) {
        const entryUrl = resolveUrl(plugin.id, plugin.frontend_entry);
        await executePluginScript(
          versionChanged
            ? `${entryUrl}?version=${encodeURIComponent(plugin.version)}`
            : entryUrl,
          controller.signal,
          () => assertCurrentGeneration(appId, generation),
        );
        assertCurrentGeneration(appId, generation);
      }

      const registered = routeRegistry
        .snapshot()
        .some(
          (route) => route.path === entryPage && route.baseSource === appId,
        );
      if (!registered) {
        throw new Error(
          `PawApp ${appId} did not register entry page ${entryPage}`,
        );
      }
    } catch (error) {
      const invalidated = generation !== generationOf(appId);
      removePluginRuntime(appId);
      if (!invalidated) previousRuntime?.restore();
      throw error;
    }
    assertCurrentGeneration(appId, generation);
    loadedApps.set(appId, plugin.version);
  })().finally(() => {
    if (loadingPromises.get(appId) === promise) {
      loadingPromises.delete(appId);
    }
    if (loadControllers.get(appId) === controller) {
      loadControllers.delete(appId);
    }
  });

  loadingPromises.set(appId, promise);
  return promise;
}

/** Invalidate and abort one PawApp load after a confirmed uninstall. */
export function invalidatePawAppLoad(appId: string): void {
  lifecycleGenerations.set(appId, generationOf(appId) + 1);
  loadControllers.get(appId)?.abort();
  loadControllers.delete(appId);
  loadingPromises.delete(appId);
  loadedApps.delete(appId);
}

/** Reset module caches between unit tests. */
export function resetPawAppLoaderForTests(): void {
  loadedApps.clear();
  loadingPromises.clear();
  lifecycleGenerations.clear();
  for (const controller of loadControllers.values()) controller.abort();
  loadControllers.clear();
}
