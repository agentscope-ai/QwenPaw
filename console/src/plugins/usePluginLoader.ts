/** Frontend plugin loading utilities. */

import { getApiToken, getApiUrl } from "../api/config";
import { removePluginRuntime } from "./pluginRuntimeCleanup";
import { routeRegistry } from "./registry/store";
import { subscribeToPluginChanges } from "../utils/pluginChangeEvents";
import { harnessRegistry, refreshHarnessCatalog } from "./harnesses";
import { loadHostUiDependencies } from "./hostUiDependencies";
import {
  replacePluginSdkDeclarations,
  setPluginSdkDeclaration,
} from "./registry/pluginSdk";

interface FrontendPluginInfo {
  id: string;
  name: string;
  plugin_type?: string;
  frontend_entry?: string;
  enabled?: boolean;
  status?: string;
  harnesses?: string[];
  /** SDK version the plugin declared in its manifest. */
  sdk_version?: string;
  /** SDK capabilities the plugin declared in its manifest. */
  sdk_capabilities?: string[];
}

export interface PluginLoadSummary {
  loaded: number;
  failed: string[];
}

const loadingPlugins = new Map<string, Promise<void>>();
let stopChanges: (() => void) | undefined;
/** Monotonic id of the most recently started plugin-list request. */
let latestCatalogRequest = 0;
/**
 * Plugin ids whose entry script has been evaluated in this session.
 *
 * A superseded list must not re-run an id that a newer request already
 * installed, but it must still load the ids that newer request did not cover:
 * a hot reload of one plugin says nothing about the rest of the list.
 */
const executedPluginIds = new Set<string>();
/**
 * The newest catalog snapshot, by plugin ID. Only the newest list request may
 * replace it, so an out-of-order response cannot roll it back. A load compares
 * its own record against this entry rather than against the newest request ID:
 * a list fetched for one plugin must not make every other plugin look stale.
 */
const latestRecords = new Map<string, FrontendPluginInfo>();

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
  const stopPlugins = subscribeToPluginChanges(reconcile);
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

/** One catalog response, together with whether a newer request superseded it. */
export interface PluginCatalog {
  plugins: FrontendPluginInfo[];
  /**
   * A newer list request started while this one was in flight. Its records are
   * stale: a hot reload may already have installed the same plugin ID from the
   * newer list, so executing these would overwrite that declaration.
   */
  stale: boolean;
}

/** @internal exported so the out-of-order catalog test can drive two lists. */
export async function fetchFrontendPlugins(): Promise<PluginCatalog> {
  const requestId = latestCatalogRequest + 1;
  latestCatalogRequest = requestId;
  const response = await fetch(getApiUrl("/frontend_plugin"), {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Failed to list frontend plugins (${response.status})`);
  }
  const plugins: FrontendPluginInfo[] = await response.json();
  // Theme-role checks need each plugin's declared SDK surface, so keep the
  // registry in step with the list we just fetched. Only the newest request
  // may rewrite the registry: list responses can arrive out of order, and an
  // older one used to clear the declaration a newer list had just installed,
  // leaving the freshly loaded plugin reporting "declares no SDK".
  const stale = requestId !== latestCatalogRequest;
  if (!stale) {
    replacePluginSdkDeclarations(
      plugins.map((plugin) => ({
        id: plugin.id,
        sdkVersion: plugin.sdk_version,
        sdkCapabilities: plugin.sdk_capabilities,
      })),
    );
    latestRecords.clear();
    for (const plugin of plugins) {
      latestRecords.set(plugin.id, plugin);
    }
  }
  return { plugins, stale };
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

/**
 * Whether the newest catalog still describes this plugin exactly as the record
 * being loaded does. A list request issued for another plugin refreshes the
 * snapshot without changing this entry, and must not read as an update.
 */
function matchesLatestDefinition(
  record: FrontendPluginInfo,
  latest: FrontendPluginInfo,
): boolean {
  const sameList = (a: string[] | undefined, b: string[] | undefined) =>
    JSON.stringify([...(a ?? [])].sort()) ===
    JSON.stringify([...(b ?? [])].sort());
  return (
    record.frontend_entry === latest.frontend_entry &&
    record.sdk_version === latest.sdk_version &&
    record.plugin_type === latest.plugin_type &&
    record.enabled === latest.enabled &&
    record.status === latest.status &&
    sameList(record.sdk_capabilities, latest.sdk_capabilities) &&
    sameList(record.harnesses, latest.harnesses)
  );
}

/**
 * A newer catalog or a plugin-change event superseded a load while its entry
 * script was in flight. The stale script is never imported; whoever owns the
 * newest load installs that one instead. Kept distinct from real failures so a
 * plugin that is already running is not torn down for a superseded attempt.
 */
class PluginLoadSuperseded extends Error {}

/**
 * Evaluate one catalog record's entry script.
 *
 * @returns whether the script was evaluated. `false` means the record went
 * stale while its script was in flight and the caller must not import it.
 */
async function executePluginScript(
  plugin: FrontendPluginInfo,
): Promise<boolean> {
  const entryUrl = resolveUrl(plugin.id, plugin.frontend_entry!);
  const response = await fetch(entryUrl, { headers: authHeaders() });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${entryUrl}`);
  }

  const source = await response.text();
  // Every startup, PawApp install, and reload evaluates through here.
  // Keep availability checks after this await: preparation can be slow.
  await loadHostUiDependencies();
  // Refuse a record the catalog has moved past, before the import rather than
  // after it: importing it now would evaluate an old entry after the new one,
  // and a list that only refreshed the registry would leave that old entry
  // running with nothing left to replace it. Compare against this plugin's
  // newest definition, not the newest request id — a list fetched for one
  // plugin says nothing about whether this one changed.
  const latest = latestRecords.get(plugin.id);
  if (!latest || !matchesLatestDefinition(plugin, latest)) {
    return false;
  }
  if (!canExecute(plugin))
    throw new Error(`Plugin became unavailable before execution: ${plugin.id}`);
  // The record is still the newest one here, so its declaration belongs to the
  // script about to be evaluated.
  if (plugin.sdk_version) {
    setPluginSdkDeclaration(plugin.id, {
      version: plugin.sdk_version,
      capabilities: plugin.sdk_capabilities ?? [],
    });
  }
  const blobUrl = URL.createObjectURL(
    new Blob([source], { type: "application/javascript" }),
  );
  try {
    await import(/* @vite-ignore */ blobUrl);
    executedPluginIds.add(plugin.id);
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
  return true;
}

/** Load every installed frontend plugin during Console startup. */
export async function loadAllPlugins(): Promise<PluginLoadSummary> {
  watchChanges();
  let plugins: FrontendPluginInfo[];
  let superseded = false;
  try {
    const catalog = await fetchFrontendPlugins();
    // A newer list request superseded this one — a hot reload may have already
    // installed some of these ids from that list. Re-running them would hand
    // `executePluginScript` an older SDK declaration for the same id and
    // overwrite the one the reload just registered. Skip exactly those ids and
    // keep loading the rest: the reload only spoke for the plugin it handled.
    superseded = catalog.stale;
    plugins = catalog.plugins;
  } catch (error) {
    console.warn("[PluginLoader] failed to fetch plugin list:", error);
    return { loaded: 0, failed: [] };
  }

  // SDK Harness entries require the authoritative active owner snapshot.
  await refreshHarnessCatalog().catch(() => {});
  const loadable = plugins
    .filter(canExecute)
    .filter((plugin) => !(superseded && executedPluginIds.has(plugin.id)));
  const results = await Promise.allSettled(
    loadable.map(async (plugin) => {
      // A reload of this id may still be running. Its record is newer than the
      // one here, and its id is not in `executedPluginIds` until it finishes,
      // so the filter above cannot see it. Join that reload instead of running
      // the plugin a second time from this older record.
      const inFlight = loadingPlugins.get(plugin.id);
      if (inFlight) {
        await inFlight;
        return;
      }
      if (await executePluginScript(plugin)) return;
      // The record went stale while its script was in flight, so that script
      // was not evaluated. Install the newest one instead: a reload that has
      // already finished is visible in `executedPluginIds`, one that is still
      // running is joined by `ensureFrontendPlugin`.
      if (!executedPluginIds.has(plugin.id)) {
        await ensureFrontendPlugin(plugin.id);
      }
    }),
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
    let catalog = await fetchFrontendPlugins();
    // A stale answer means another list request started after this one; ask
    // again so the plugin is evaluated from the newest records rather than
    // from a declaration an update has already replaced.
    if (catalog.stale) catalog = await fetchFrontendPlugins();
    if (catalog.stale) {
      throw new Error(
        `Plugin catalog was superseded before loading: ${pluginId}`,
      );
    }
    const plugin = catalog.plugins.find((item) => item.id === pluginId);
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
      const executed = await executePluginScript(plugin);
      if (!executed) {
        throw new PluginLoadSuperseded(
          `Plugin load was superseded before its script ran: ${pluginId}`,
        );
      }
      if (options.expectedType === "app" && !registered()) {
        throw new Error(`PawApp ${pluginId} did not register its app route`);
      }
    } catch (error) {
      // A superseded attempt never replaced the running plugin, so its runtime
      // must stay in place; only real failures tear it down.
      if (!(error instanceof PluginLoadSuperseded)) {
        removePluginRuntime(pluginId);
      }
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

/** Ensure a frontend is present, joining any installation reload in flight. */
export function ensureFrontendPlugin(pluginId: string): Promise<void> {
  return loadFrontendPlugin(pluginId);
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
  executedPluginIds.clear();
  latestRecords.clear();
  stopChanges?.();
  stopChanges = undefined;
  latestCatalogRequest = 0;
}
