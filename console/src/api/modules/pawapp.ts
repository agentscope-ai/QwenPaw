import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

export interface PawAppInfo {
  id: string;
  name: string;
  version: string;
  description: string;
  author: string;
  category: string;
  icon: string;
  status: string;
  home_page: string | null;
  entry_page?: string;
  launch_scope?: string;
  dir: string;
  settings: unknown[];
  permissions: Record<string, unknown>;
  backends: Record<string, unknown>;
}

export interface PawAppListResponse {
  apps: PawAppInfo[];
  total: number;
}

export interface PawAppIframeResponse {
  app_id: string;
  iframe_url: string | null;
  error?: string;
}

export const pawappApi = {
  /**
   * List all installed PawApps.
   */
  async list(): Promise<PawAppListResponse> {
    const res = await fetch(getApiUrl("/pawapps"), {
      headers: buildAuthHeaders(),
    });
    if (!res.ok) throw new Error(`Failed to list PawApps: ${res.statusText}`);
    return res.json();
  },

  /**
   * Get details of a specific PawApp.
   */
  async get(appId: string): Promise<PawAppInfo> {
    const res = await fetch(getApiUrl(`/pawapps/${appId}`), {
      headers: buildAuthHeaders(),
    });
    if (!res.ok)
      throw new Error(`Failed to get PawApp ${appId}: ${res.statusText}`);
    return res.json();
  },

  /**
   * Get the iframe URL for a PawApp.
   */
  async getIframeUrl(appId: string): Promise<PawAppIframeResponse> {
    const res = await fetch(getApiUrl(`/pawapps/${appId}/iframe`), {
      headers: buildAuthHeaders(),
    });
    if (!res.ok)
      throw new Error(
        `Failed to get iframe URL for ${appId}: ${res.statusText}`,
      );
    return res.json();
  },

  /**
   * Uninstall a PawApp by ID (deletes its directory under ~/.copaw/apps).
   */
  async uninstall(appId: string): Promise<void> {
    const res = await fetch(getApiUrl(`/pawapps/${appId}`), {
      method: "DELETE",
      headers: buildAuthHeaders(),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(
        (body as { detail?: string }).detail ??
          `Uninstall failed (${res.status})`,
      );
    }
  },

  /**
   * Get the static file URL for a PawApp asset.
   */
  getStaticUrl(appId: string, filePath: string): string {
    return getApiUrl(`/pawapps/${appId}/static/${filePath}`);
  },
};
