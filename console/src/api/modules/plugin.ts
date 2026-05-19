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
export async function installPlugin(
  source: string,
): Promise<InstallPluginResult> {
  const response = await fetch(getApiUrl("/plugins/install"), {
    method: "POST",
    headers: {
      ...buildAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ source }),
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
