/**
 * usePluginLoader.ts — plugin loading utility
 *
 * Fetches authorized plugins and executes worker-v1 bundles in dedicated
 * workers. Only validated data registrations cross into the host UI.
 *
 * Exports `loadAllPlugins()` — the single function PluginContext calls.
 */

import { getApiUrl, getApiToken } from "../api/config";
import { createElement } from "react";
import { pluginSystem } from "./pluginSystem";
import { PluginWorkerClient } from "./isolated/workerClient";
import { PluginView } from "./isolated/PluginView";
import { chatExtensions } from "./registry/chatExtensions";
import { menuRegistry, routeRegistry, slotRegistry } from "./registry/store";

// ─────────────────────────────────────────────────────────────────────────────
// Plugin manifest type (mirrors backend PluginInfo)
// ─────────────────────────────────────────────────────────────────────────────

interface PluginInfo {
  id: string;
  name: string;
  frontend_entry?: string;
  frontend_runtime?: string;
  enabled?: boolean;
}

const workers = new Map<string, PluginWorkerClient>();
let generation = 0;
const PLUGIN_FETCH_TIMEOUT_MS = 8000;

async function fetchPluginResource<T>(
  url: string,
  read: (response: Response) => Promise<T>,
  signal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, PLUGIN_FETCH_TIMEOUT_MS);
  try {
    const token = getApiToken();
    const response = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal: controller.signal,
    });
    if (!response.ok)
      throw new Error(`Plugin resource HTTP ${response.status}`);
    const result = await read(response);
    if (controller.signal.aborted)
      throw new DOMException("Aborted", "AbortError");
    return result;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export function resetLoadedPlugins(): void {
  generation++;
  for (const [source, worker] of workers) {
    worker.stop();
    disposeSource(source);
  }
  workers.clear();
}

/** Drop removed installations and their in-flight actions on every open console. */
export function watchPluginAccess(signal: AbortSignal): () => void {
  let checking = false;
  const check = async () => {
    if (signal.aborted || document.hidden || !workers.size || checking) return;
    checking = true;
    try {
      const plugins = await fetchPluginResource<PluginInfo[]>(
        getApiUrl("/frontend_plugin"),
        (response) => response.json(),
        signal,
      );
      if (signal.aborted || !Array.isArray(plugins)) return;
      const allowed = new Set(
        plugins
          .filter((item) => item.enabled !== false && item.frontend_entry)
          .map((item) => item.id),
      );
      for (const worker of workers.values()) {
        if (!allowed.has(worker.pluginId))
          worker.stop(new Error("plugin_access_revoked"));
      }
    } catch {
      // The server checks authorization for every operation. Retry discovery
      // on the next focus/interval after a transient connectivity failure.
    } finally {
      checking = false;
    }
  };
  const interval = setInterval(check, 30_000);
  window.addEventListener("focus", check);
  window.addEventListener("qwenpaw:plugin-access-changed", check);
  return () => {
    clearInterval(interval);
    window.removeEventListener("focus", check);
    window.removeEventListener("qwenpaw:plugin-access-changed", check);
  };
}

function disposeSource(source: string) {
  menuRegistry.disposeSource(source);
  routeRegistry.disposeSource(source);
  slotRegistry.disposeSource(source);
  chatExtensions.disposeAll(source);
  pluginSystem.remove(source);
}

// ─────────────────────────────────────────────────────────────────────────────
// Internal helpers
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Resolve a backend-relative API path (e.g. `/plugins/…/files/index.js`)
 * to a full URL using the same base that all other API calls use.
 */
function resolveUrl(pluginId: string, apiPath: string): string {
  return getApiUrl(
    `frontend_plugin/${encodeURIComponent(pluginId)}/files/${apiPath}`,
  );
}

/**
 * Download code as text only. All execution happens in a terminable worker.
 */
async function executePluginScript(
  plugin: PluginInfo,
  epoch: number,
  signal?: AbortSignal,
  onFailure?: (message: string) => void,
): Promise<void> {
  if (plugin.frontend_runtime !== "worker-v1")
    throw new Error("旧前端插件需要升级到 worker-v1，已停止自动执行");
  if (!/^[\w.-]{1,100}$/.test(plugin.id)) throw new Error("invalid_plugin_id");
  const jsText = await fetchPluginResource(
    resolveUrl(plugin.id, plugin.frontend_entry!),
    (response) => response.text(),
    signal,
  );
  if (signal?.aborted || generation !== epoch)
    throw new DOMException("Aborted", "AbortError");
  if (jsText.length > 2_000_000) throw new Error("plugin_bundle_too_large");
  const source = `worker:${epoch}:${plugin.id}`;
  const client = new PluginWorkerClient(plugin.id, jsText, signal);
  workers.set(source, client);
  let committed = false;
  client.onStopped = (error) => {
    disposeSource(source);
    if (workers.get(source) === client) workers.delete(source);
    if (
      committed &&
      !signal?.aborted &&
      generation === epoch &&
      !["plugin_identity_changed", "plugin_access_revoked"].includes(
        error.message,
      )
    )
      onFailure?.(`${plugin.name || plugin.id}：插件已停止响应，已隔离停止`);
  };
  try {
    const registrations = await client.ready;
    if (signal?.aborted || generation !== epoch)
      throw new DOMException("Aborted", "AbortError");
    for (const item of registrations) {
      const component = (props: Record<string, unknown>) =>
        createElement(PluginView, { client, target: item.id, input: props });
      if (item.kind === "route") {
        const id = `${source}:${item.id}`;
        routeRegistry.add(source, { id, path: item.path!, component });
        if (plugin.id === "cloudpaw" && item.path === "/plugin/cloudpaw/a2a") {
          // Keep existing bookmarks inside the same authorized plugin lifecycle.
          routeRegistry.add(source, {
            id: `${id}:legacy-a2a`,
            path: "/a2a",
            component,
          });
        }
        if (!item.path!.startsWith("/apps/"))
          menuRegistry.add(source, {
            id,
            location: "primary.settings",
            label: item.label!,
            route: id,
          });
        pluginSystem.addRoutes(source, [
          { path: item.path!, component, label: item.label! },
        ]);
      } else {
        pluginSystem.addToolRenderers(source, { [item.tool!]: component });
      }
    }
    committed = true;
  } catch (error) {
    client.stop();
    disposeSource(source);
    throw error;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Public API
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Fetch the plugin list from `GET /api/plugins`, then load every plugin that
 * has a `frontend_entry` in parallel.  Failures are isolated per plugin so
 * one bad plugin never blocks the others.
 *
 * Returns a summary `{ loaded, failed }` for the caller to surface as an error.
 */
export async function loadAllPlugins(
  signal?: AbortSignal,
  onFailure?: (message: string) => void,
): Promise<{
  loaded: number;
  failed: string[];
}> {
  const failed: string[] = [];
  const epoch = generation;

  let plugins: PluginInfo[];
  try {
    plugins = await fetchPluginResource<PluginInfo[]>(
      getApiUrl("/frontend_plugin"),
      (response) => response.json(),
      signal,
    );
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    if (!Array.isArray(plugins)) throw new Error("Invalid plugin list");
  } catch (err) {
    console.warn("[PluginLoader] failed to fetch plugin list:", err);
    return { loaded: 0, failed: [String(err)] };
  }

  const frontendPlugins = [
    ...new Map(
      plugins
        .filter((p) => p.frontend_entry && p.enabled !== false)
        .map((p) => [p.id, p]),
    ).values(),
  ];
  if (frontendPlugins.length === 0) return { loaded: 0, failed: [] };

  const results = await Promise.allSettled(
    frontendPlugins.map(async (p) => {
      await executePluginScript(p, epoch, signal, onFailure);
      console.info(`[PluginLoader] ✓ ${p.id}`);
    }),
  );

  results.forEach((r, i) => {
    if (r.status === "rejected") {
      const reason = String(r.reason);
      const explanation = reason.includes("timed_out")
        ? "插件启动超时，已隔离停止"
        : reason.includes("plugin_execution_failed")
        ? "插件执行失败，已隔离停止"
        : reason;
      const msg = `${
        frontendPlugins[i].name || frontendPlugins[i].id
      }: ${explanation}`;
      console.error(`[PluginLoader] ✗ ${msg}`);
      failed.push(msg);
    }
  });

  console.info(
    `[PluginLoader] ${frontendPlugins.length - failed.length}/${
      frontendPlugins.length
    } plugin(s) loaded`,
  );
  return { loaded: frontendPlugins.length - failed.length, failed };
}
