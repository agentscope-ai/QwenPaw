import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

/**
 * A single plugin record returned by `GET /api/plugins`.
 */
export interface PluginInfo {
  id: string;
  name: string;
  version: string;
  description: string;
  enabled: boolean;
  /** Whether this plugin has a frontend entry point. */
  has_frontend: boolean;
  /** URL to the plugin's frontend JS entry module (if has_frontend). */
  frontend_entry?: string;
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
