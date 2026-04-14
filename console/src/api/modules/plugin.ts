import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

/**
 * UI metadata returned by the backend for a plugin that ships a frontend.
 */
export interface PluginUIInfo {
  /** Absolute URL to the plugin's JS entry module. */
  entry: string;
  /** Absolute URL to the plugin's CSS file (empty string if none). */
  css: string;
  /**
   * Mapping from backend tool name → exported component name.
   *
   * Example: `{ "weather_search": "WeatherCard" }`
   */
  tool_renderers: Record<string, string>;
}

/**
 * A single plugin record returned by `GET /api/plugins`.
 */
export interface PluginInfo {
  id: string;
  name: string;
  version: string;
  description: string;
  enabled: boolean;
  has_ui: boolean;
  ui?: PluginUIInfo;
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
