import { request } from "../request";

export interface MarketProviderInfo {
  key: string;
  label: string;
  available: boolean;
  reason: string | null;
}

export interface MarketResult {
  source: string;
  slug: string;
  name: string;
  description: string | null;
  source_url: string;
  version: string | null;
  author: string | null;
  icon_url: string | null;
  stats: Record<string, string | number> | null;
}

export interface MarketSearchError {
  provider: string;
  message: string;
}

export interface ProviderPageInfo {
  has_more: boolean;
  total: number;
}

export interface MarketSearchResponse {
  results: MarketResult[];
  errors: MarketSearchError[];
  by_provider: Record<string, ProviderPageInfo>;
}

export interface MarketSearchPayload {
  query: string;
  provider_pages: Record<string, number>;
  limit?: number;
  lang?: string;
}

export const marketApi = {
  listMarketProviders: () => request<MarketProviderInfo[]>("/market/providers"),

  searchMarket: (payload: MarketSearchPayload) =>
    request<MarketSearchResponse>("/market/search", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
