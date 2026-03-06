import { request } from "../request";
import type { TokenUsageSummary } from "../types/tokenUsage";

type GetTokenUsageParams = {
  start_date?: string;
  end_date?: string;
  model?: string;
};

function buildQuery(params: GetTokenUsageParams): string {
  const search = new URLSearchParams();
  if (params.start_date) search.set("start_date", params.start_date);
  if (params.end_date) search.set("end_date", params.end_date);
  if (params.model) search.set("model", params.model);
  const q = search.toString();
  return q ? `?${q}` : "";
}

export const tokenUsageApi = {
  getTokenUsage: (params?: GetTokenUsageParams) =>
    request<TokenUsageSummary>(`/token-usage${buildQuery(params ?? {})}`),
};
