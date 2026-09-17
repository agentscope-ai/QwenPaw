import { request } from "../request";
import type {
  ACPAgentConfig,
  ACPConfig,
  ACPNodeRuntimeStatus,
  ACPNodeRuntimeUpdate,
} from "../types";

export const acpApi = {
  getACPConfig: () => request<ACPConfig>("/config/acp"),

  getACPNodeRuntime: () =>
    request<ACPNodeRuntimeStatus>("/config/acp/node-runtime"),

  getACPAgentConfig: (agentName: string) =>
    request<ACPAgentConfig>(`/config/acp/${encodeURIComponent(agentName)}`),

  updateACPConfig: (body: ACPConfig) =>
    request<ACPConfig>("/config/acp", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  updateACPNodeRuntime: (body: ACPNodeRuntimeUpdate) =>
    request<ACPNodeRuntimeStatus>("/config/acp/node-runtime", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  updateACPAgentConfig: (agentName: string, body: ACPAgentConfig) =>
    request<ACPAgentConfig>(`/config/acp/${encodeURIComponent(agentName)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};
