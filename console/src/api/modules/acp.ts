import { request } from "../request";
import type { ACPAgentConfig, ACPConfig } from "../types";

export const acpApi = {
  getACPConfig: () => request<ACPConfig>("/config/acp"),

  getACPAgentConfig: (agentName: string) =>
    request<ACPAgentConfig>(`/config/acp/${encodeURIComponent(agentName)}`),

  updateACPConfig: (body: ACPConfig) =>
    request<ACPConfig>("/config/acp", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  updateACPAgentConfig: (agentName: string, body: ACPAgentConfig) =>
    request<ACPAgentConfig>(`/config/acp/${encodeURIComponent(agentName)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};
