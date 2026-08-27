import { request } from "../request";
import type { AgentStatsSummary } from "../types/agentStats";

export interface GetAgentStatsParams {
  start_date: string;
  end_date: string;
}

export interface LlmToolDaily {
  date: string;
  agent_llm_calls: number;
  tool_calls: number;
}

function dateQuery(params: GetAgentStatsParams): string {
  const search = new URLSearchParams({
    start_date: params.start_date,
    end_date: params.end_date,
  });
  return `?${search.toString()}`;
}

export const agentStatsApi = {
  getAgentStats: (params: GetAgentStatsParams) =>
    request<AgentStatsSummary>(`/agent-stats${dateQuery(params)}`),
  getGlobalLlmToolTrend: (
    params: GetAgentStatsParams,
    options?: { signal?: AbortSignal },
  ) =>
    request<LlmToolDaily[]>(`/agent-stats/llm-tool-trend${dateQuery(params)}`, {
      timeout: 60_000,
      signal: options?.signal,
    }),
};
