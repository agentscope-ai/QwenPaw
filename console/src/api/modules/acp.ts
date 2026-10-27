import { request } from "../request";
import type {
  ACPAgentConfig,
  ACPConfig,
  ACPNodeRuntimeStatus,
  ACPNodeRuntimeUpdate,
} from "../types";

function agentHeaders(agentId?: string) {
  return agentId ? { "X-Agent-Id": agentId } : undefined;
}

export const acpApi = {
  getACPConfig: (agentId?: string) =>
    request<ACPConfig>("/config/acp", {
      headers: agentHeaders(agentId),
    }),

  getACPNodeRuntime: (agentId?: string) =>
    request<ACPNodeRuntimeStatus>("/config/acp/node-runtime", {
      headers: agentHeaders(agentId),
    }),

  getACPAgentConfig: (agentName: string, agentId?: string) =>
    request<ACPAgentConfig>(`/config/acp/${encodeURIComponent(agentName)}`, {
      headers: agentHeaders(agentId),
    }),

  updateACPConfig: (body: ACPConfig, agentId?: string) =>
    request<ACPConfig>("/config/acp", {
      method: "PUT",
      body: JSON.stringify(body),
      headers: agentHeaders(agentId),
    }),

  updateACPNodeRuntime: (body: ACPNodeRuntimeUpdate, agentId?: string) =>
    request<ACPNodeRuntimeStatus>("/config/acp/node-runtime", {
      method: "PUT",
      body: JSON.stringify(body),
      headers: agentHeaders(agentId),
    }),

  updateACPAgentConfig: (
    agentName: string,
    body: ACPAgentConfig,
    agentId?: string,
  ) =>
    request<ACPAgentConfig>(`/config/acp/${encodeURIComponent(agentName)}`, {
      method: "PUT",
      body: JSON.stringify(body),
      headers: agentHeaders(agentId),
    }),
};
