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

export interface MarketSearchResponse {
  results: MarketResult[];
  errors: MarketSearchError[];
  has_more: boolean;
  total: number;
}

export const marketApi = {
  listMarketProviders: () => request<MarketProviderInfo[]>("/market/providers"),

  searchMarket: (payload: {
    query: string;
    providers?: string[];
    limit?: number;
    page?: number;
    lang?: string;
  }) =>
    request<MarketSearchResponse>("/market/search", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
