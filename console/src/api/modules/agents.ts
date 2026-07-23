import { request } from "../request";
import type {
  AgentListResponse,
  AgentProfileConfig,
  CreateAgentRequest,
  CopyAgentRequest,
  AgentProfileRef,
  ReorderAgentsResponse,
} from "../types/agents";

// Multi-agent management API
export const agentsApi = {
  // List all agents
  listAgents: () => request<AgentListResponse>("/agents"),

  // Get agent details
  getAgent: (agentId: string) =>
    request<AgentProfileConfig>(`/agents/${agentId}`),

  // Create new agent
  createAgent: (agent: CreateAgentRequest) =>
    request<AgentProfileRef>("/agents", {
      method: "POST",
      body: JSON.stringify(agent),
    }),

  // Copy selected agent configuration files into a new agent
  copyAgent: (agentId: string, body: CopyAgentRequest) =>
    request<AgentProfileRef>(`/agents/${agentId}/copy`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Update agent configuration
  updateAgent: (agentId: string, agent: AgentProfileConfig) =>
    request<AgentProfileConfig>(`/agents/${agentId}`, {
      method: "PUT",
      body: JSON.stringify(agent),
    }),

  rebuildMemoryIndex: (agentId: string) =>
    request<{ status: "completed" }>(`/agents/${agentId}/memory/reindex`, {
      method: "POST",
      timeout: 10 * 60 * 1000,
    }),

  // Delete agent
  deleteAgent: (agentId: string) =>
    request<{ success: boolean; agent_id: string }>(`/agents/${agentId}`, {
      method: "DELETE",
    }),

  // Persist ordered agent ids
  reorderAgents: (agentIds: string[]) =>
    request<ReorderAgentsResponse>("/agents/order", {
      method: "PUT",
      body: JSON.stringify({ agent_ids: agentIds }),
    }),

  // Toggle agent enabled state
  toggleAgentEnabled: (agentId: string, enabled: boolean) =>
    request<{ success: boolean; agent_id: string; enabled: boolean }>(
      `/agents/${agentId}/toggle`,
      {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      },
    ),

  setAgentPinned: (agentId: string, pinned: boolean) =>
    request<{ success: boolean; agent_id: string; pinned: boolean }>(
      `/agents/${agentId}/pin`,
      {
        method: "PATCH",
        body: JSON.stringify({ pinned }),
      },
    ),
};
