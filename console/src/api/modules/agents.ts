import { getApiUrl } from "../config";
import { request } from "../request";
import type {
  AgentListResponse,
  AgentProfileConfig,
  CreateAgentRequest,
  AgentProfileRef,
} from "../types/agents";
import type { MdFileInfo, MdFileContent } from "../types/workspace";

export function buildAgentAvatarUrl(
  agentId: string,
  avatar?: string | boolean | null,
  cacheBuster?: string | number,
): string | undefined {
  if (!avatar) return undefined;

  const url = getApiUrl(`/agents/${encodeURIComponent(agentId)}/avatar`);
  if (cacheBuster === undefined || cacheBuster === null) {
    return url;
  }
  return `${url}?v=${encodeURIComponent(String(cacheBuster))}`;
}

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

  // Update agent configuration
  updateAgent: (agentId: string, agent: AgentProfileConfig) =>
    request<AgentProfileConfig>(`/agents/${agentId}`, {
      method: "PUT",
      body: JSON.stringify(agent),
    }),

  // Delete agent
  deleteAgent: (agentId: string) =>
    request<{ success: boolean; agent_id: string }>(`/agents/${agentId}`, {
      method: "DELETE",
    }),

  uploadAvatar: (agentId: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);

    return request<{ success: boolean; avatar: string; avatar_url?: string }>(
      `/agents/${agentId}/avatar`,
      {
        method: "POST",
        body: formData,
      },
    );
  },

  deleteAvatar: (agentId: string) =>
    request<{ success: boolean }>(`/agents/${agentId}/avatar`, {
      method: "DELETE",
    }),

  // Agent workspace files
  listAgentFiles: (agentId: string) =>
    request<MdFileInfo[]>(`/agents/${agentId}/files`),

  readAgentFile: (agentId: string, filename: string) =>
    request<MdFileContent>(
      `/agents/${agentId}/files/${encodeURIComponent(filename)}`,
    ),

  writeAgentFile: (agentId: string, filename: string, content: string) =>
    request<{ written: boolean; filename: string }>(
      `/agents/${agentId}/files/${encodeURIComponent(filename)}`,
      {
        method: "PUT",
        body: JSON.stringify({ content }),
      },
    ),

  // Agent memory files
  listAgentMemory: (agentId: string) =>
    request<MdFileInfo[]>(`/agents/${agentId}/memory`),
};
