import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

/**
 * A page route declared by a plugin in its `plugin.json`.
 */
export interface PluginPageInfo {
  /** URL path segment (e.g. "my-dashboard"). Will be mounted at `/plugin/<id>/<path>`. */
  path: string;
  /** Display label shown in the sidebar. */
  label: string;
  /** Emoji or short text used as the sidebar icon. */
  icon?: string;
  /** Name of the React component exported by the plugin's `register(host)`. */
  component: string;
}

/**
 * UI metadata returned by the backend for a plugin that ships a frontend.
 */
export interface PluginUIInfo {
  /** Absolute URL to the plugin's JS entry module. */
  entry: string;
  /** Absolute URL to the plugin's CSS file (empty string if none). */
  css: string;
  /**
   * Mapping from backend tool name → exported JS component name.
   *
   * Example: `{ "weather_search": "WeatherCard" }`
   */
  js_tool_renderers: Record<string, string>;
  /**
   * Page routes declared by the plugin. Each page becomes a routable view
   * with a sidebar menu entry.
   */
  pages?: PluginPageInfo[];
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
