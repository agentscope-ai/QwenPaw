/**
 * usePluginLoader.ts — plugin loading utility
 *
 * Fetches the plugin list, downloads each frontend bundle, and executes it
 * via a same-origin Blob URL so plugins can self-register into the
 * `pluginSystem` singleton (hostExternals.ts).
 *
 * Exports `loadAllPlugins()` — the single function PluginContext calls.
 */

import { getApiUrl, getApiToken } from "../api/config";

// ─────────────────────────────────────────────────────────────────────────────
// Plugin manifest type (mirrors backend PluginInfo)
// ─────────────────────────────────────────────────────────────────────────────

interface PluginInfo {
  id: string;
  name: string;
  frontend_entry?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Internal helpers
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Resolve a backend-relative API path (e.g. `/plugins/…/files/index.js`)
 * to a full URL using the same base that all other API calls use.
 */
function resolveUrl(pluginId: string, apiPath: string): string {
  return getApiUrl(`plugins/${pluginId}/files/${apiPath}`);
}

/**
 * Fetch a plugin's JS source, wrap it in a same-origin Blob URL, and
 * execute it via dynamic import.  Blob URL is revoked immediately after.
 */
async function executePluginScript(entryUrl: string): Promise<void> {
  const token = getApiToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(entryUrl, { headers });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} for ${entryUrl}`);
  }

  const jsText = await response.text();
  const blobUrl = URL.createObjectURL(
    new Blob([jsText], { type: "application/javascript" }),
  );
  try {
    await import(/* @vite-ignore */ blobUrl);
  } finally {
    URL.revokeObjectURL(blobUrl);
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
export async function loadAllPlugins(): Promise<{
  loaded: number;
  failed: string[];
}> {
  const failed: string[] = [];

  let plugins: PluginInfo[];
  try {
    const token = getApiToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(getApiUrl("/plugins"), { headers });
    if (!res.ok) {
      console.warn(`[PluginLoader] /api/plugins returned ${res.status}`);
      return { loaded: 0, failed: [] };
    }
    plugins = await res.json();
  } catch (err) {
    console.warn("[PluginLoader] failed to fetch plugin list:", err);
    return { loaded: 0, failed: [] };
  }

  const frontendPlugins = plugins.filter((p) => p.frontend_entry);

  const results = await Promise.allSettled(
    frontendPlugins.map(async (p) => {
      await executePluginScript(resolveUrl(p.id, p.frontend_entry!));
      console.info(`[PluginLoader] ✓ ${p.id}`);
    }),
  );

  results.forEach((r, i) => {
    if (r.status === "rejected") {
      const msg = `${frontendPlugins[i].id}: ${r.reason}`;
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
