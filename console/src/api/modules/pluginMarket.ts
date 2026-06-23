import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

export interface MarketPluginLocale {
  description: string;
  category: string;
}

export interface MarketPluginEntry {
  id: string;
  display_name: string;
  developer: string;
  owner: string;
  version: string;
  logo_url: string | null;
  downloads: number;
  view_count: number;
  details_url: string | null;
  locales: Record<string, MarketPluginLocale>;
}

interface MarketPluginListResponse {
  success: boolean;
  message: string;
  data: {
    total: number;
    plugins: MarketPluginEntry[];
  };
}

export interface FetchMarketPluginsParams {
  search?: string;
  category?: string;
  page_number: number;
  page_size: number;
}

export async function fetchMarketPlugins(
  params: FetchMarketPluginsParams,
): Promise<{ total: number; plugins: MarketPluginEntry[] }> {
  const url = new URL(
    getApiUrl("/plugins/market/search"),
    window.location.origin,
  );
  url.searchParams.set("page_number", String(params.page_number));
  url.searchParams.set("page_size", String(params.page_size));
  if (params.search) url.searchParams.set("search", params.search);
  if (params.category) url.searchParams.set("category", params.category);

  const response = await fetch(url.toString(), {
    headers: buildAuthHeaders(),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      (body as { detail?: string; message?: string }).detail ??
        (body as { message?: string }).message ??
        `Failed to fetch market plugins (${response.status})`,
    );
  }

  const json: MarketPluginListResponse = await response.json();
  if (!json.success) {
    throw new Error(json.message || "Failed to fetch market plugins");
  }

  return json.data;
}

export function buildMarketDownloadUrl(entry: MarketPluginEntry): string {
  const id = entry.id.startsWith("@") ? entry.id.slice(1) : entry.id;
  const [owner, name] = id.split("/");
  return `https://platform.agentscope.io/plugins/${owner}/${name}/archive/zip/master`;
}
