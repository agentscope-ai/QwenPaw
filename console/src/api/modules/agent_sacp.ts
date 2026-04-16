import { request } from "../request";
import type {
  AgentSACPConfig,
  CreateAgentSACPRequest,
  UpdateAgentSACPRequest,
  AgentSACPHealthCheckResult,
  AgentSACPStorage,
} from "../types/agent_sacp";

export type { AgentSACPConfig };

export const agentSACPApi = {
  /**
   * List all Agent SACP agents
   */
  getAgents: () => request<AgentSACPConfig[]>("/sacp-agents"),

  /**
   * Create a new Agent SACP agent
   */
  createAgent: (body: CreateAgentSACPRequest) =>
    request<AgentSACPConfig>("/sacp-agents", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /**
   * Get Agent SACP agents settings
   */
  getSettings: () => request<AgentSACPStorage>("/sacp-agents/settings"),

  /**
   * Update Agent SACP agents settings
   */
  updateSettings: (body: { global_internal_auth_key?: string }) =>
    request<AgentSACPStorage>("/sacp-agents/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  /**
   * Get a specific Agent SACP agent
   */
  getAgent: (agentId: string) =>
    request<AgentSACPConfig>(`/sacp-agents/entity/${agentId}`),

  /**
   * Update an existing Agent SACP agent
   */
  updateAgent: (agentId: string, body: UpdateAgentSACPRequest) =>
    request<AgentSACPConfig>(`/sacp-agents/entity/${agentId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  /**
   * Delete an Agent SACP agent
   */
  deleteAgent: (agentId: string) =>
    request<void>(`/sacp-agents/entity/${agentId}`, {
      method: "DELETE",
    }),

  /**
   * Trigger batch health check for all agents
   */
  healthCheckAllAgents: () =>
    request<AgentSACPHealthCheckResult[]>("/sacp-agents/health_check", {
      method: "POST",
    }),

  /**
   * Trigger health check for a specific Agent SACP agent
   */
  healthCheckAgent: (agentId: string) =>
    request<AgentSACPHealthCheckResult>(
      `/sacp-agents/health_check/${agentId}`,
      {
        method: "POST",
      },
    ),
};
