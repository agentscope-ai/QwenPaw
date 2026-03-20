import { getApiToken, getApiUrl } from "../config";
import { request } from "../request";
import type {
  AgentListResponse,
  AgentSummary,
  AgentProfileConfig,
  CreateAgentRequest,
  AgentProfileRef,
} from "../types/agents";
import type { MdFileInfo, MdFileContent } from "../types/workspace";

function appendAuthToken(url?: string | null): string | undefined {
  if (!url) return undefined;

  const token = getApiToken();
  if (!token) return url;

  const resolvedUrl = new URL(url, window.location.href);
  resolvedUrl.searchParams.set("token", token);
  return resolvedUrl.toString();
}

export function normalizeAvatarUrl(url?: string | null): string | undefined {
  return appendAuthToken(url);
}

function normalizeAgentSummary(agent: AgentSummary): AgentSummary {
  return {
    ...agent,
    avatar_url: normalizeAvatarUrl(agent.avatar_url),
  };
}

export function buildAgentAvatarUrl(
  agentId: string,
  avatar?: string | boolean | null,
  cacheBuster?: string | number,
): string | undefined {
  if (!avatar) return undefined;

  const url = getApiUrl(`/agents/${encodeURIComponent(agentId)}/avatar`);
  const resolvedUrl =
    cacheBuster === undefined || cacheBuster === null
      ? url
      : `${url}?v=${encodeURIComponent(String(cacheBuster))}`;

  return normalizeAvatarUrl(resolvedUrl);
}

// Multi-agent management API
export const agentsApi = {
  // List all agents
  listAgents: async () => {
    const response = await request<AgentListResponse>("/agents");
    return {
      ...response,
      agents: response.agents.map(normalizeAgentSummary),
    };
  },

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
