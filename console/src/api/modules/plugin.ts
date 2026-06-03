import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

/** Matches the backend ``PluginType`` enum values. */
export type PluginType =
  | "tool"
  | "provider"
  | "hook"
  | "command"
  | "frontend"
  | "general";

/**
 * A single plugin record returned by `GET /api/plugins`.
 */
export interface PluginInfo {
  id: string;
  name: string;
  version: string;
  description: string;
  author?: string;
  enabled: boolean;
  /** Whether the plugin is currently loaded in memory. */
  loaded: boolean;
  /** Primary capability type declared in plugin.json. */
  plugin_type: PluginType;
  /** Frontend JS entry-point path (if any). */
  frontend_entry?: string;
}

export interface InstallPluginResult {
  id: string;
  name: string;
  version: string;
  description: string;
  author?: string;
  loaded: boolean;
  message: string;
}

export interface PluginStatus {
  id: string;
  loaded: boolean;
  enabled: boolean;
  version?: string;
}

/** Entry from ``GET /api/plugins/catalog`` (official CDN manifest). */
export interface OfficialPluginCatalogEntry {
  id: string;
  plugin_id: string;
  name: string;
  description: string;
  /** Locale-keyed descriptions, e.g. { "zh-CN": "...", "en-US": "..." } */
  description_i18n?: Record<string, string>;
  version: string;
  author: string;
  kind: string;
  size: string;
  sha256: string;
  install_url: string;
  installed: boolean;
  installed_version?: string;
  upgrade_available: boolean;
}

export interface OfficialPluginCatalog {
  updated_at: string | null;
  plugins: OfficialPluginCatalogEntry[];
  error?: string | null;
}

/**
 * Fetch the list of loaded plugins from the backend.
 */
export async function fetchPlugins(): Promise<PluginInfo[]> {
  const response = await fetch(getApiUrl("/plugins"), {
    headers: buildAuthHeaders(),
  });

  if (!response.ok) {
    console.warn("[plugin] Failed to fetch plugin list:", response.status);
    return [];
  }

  return response.json();
}

/**
 * Install a plugin from a local path or HTTP(S) URL via hot-reload.
 */
export async function fetchPluginCatalog(): Promise<OfficialPluginCatalog> {
  const response = await fetch(getApiUrl("/plugins/catalog"), {
    headers: buildAuthHeaders(),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      body.detail ?? `Failed to load plugin catalog (${response.status})`,
    );
  }

  return response.json();
}

export async function installPlugin(
  source: string,
  options?: { force?: boolean },
): Promise<InstallPluginResult> {
  const response = await fetch(getApiUrl("/plugins/install"), {
    method: "POST",
    headers: {
      ...buildAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ source, force: options?.force ?? false }),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Install failed (${response.status})`);
  }

  return response.json();
}

/**
 * Install a plugin from a local ZIP file via hot-reload.
 */
export async function uploadPlugin(file: File): Promise<InstallPluginResult> {
  const form = new FormData();
  form.append("file", file);

  const response = await fetch(getApiUrl("/plugins/upload"), {
    method: "POST",
    headers: buildAuthHeaders(),
    body: form,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Upload failed (${response.status})`);
  }

  return response.json();
}

/**
 * Uninstall (hot-unload + delete) a plugin by ID.
 */
export async function uninstallPlugin(pluginId: string): Promise<void> {
  const response = await fetch(getApiUrl(`/plugins/${pluginId}`), {
    method: "DELETE",
    headers: buildAuthHeaders(),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Uninstall failed (${response.status})`);
  }
}

/**
 * Fetch the runtime status of a single plugin.
 */
export async function fetchPluginStatus(
  pluginId: string,
): Promise<PluginStatus> {
  const response = await fetch(getApiUrl(`/plugins/${pluginId}/status`), {
    headers: buildAuthHeaders(),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Status fetch failed (${response.status})`);
  }

  return response.json();
}
