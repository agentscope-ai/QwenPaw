import { request } from "../request";
import type { TokenUsageSummary } from "../types/tokenUsage";

export interface GetTokenUsageParams {
  start_date: string;
  end_date: string;
  model?: string;
  provider?: string;
}

function buildQuery(params: GetTokenUsageParams): string {
  const search = new URLSearchParams({
    start_date: params.start_date,
    end_date: params.end_date,
  });
  if (params.model) search.set("model", params.model);
  if (params.provider) search.set("provider", params.provider);
  return `?${search.toString()}`;
}

export const tokenUsageApi = {
  getTokenUsage: (params: GetTokenUsageParams) =>
    request<TokenUsageSummary>(`/token-usage${buildQuery(params)}`),
};
