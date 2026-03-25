import { request } from "../request";
import { getApiUrl, getApiToken } from "../config";
import type {
  AgentListResponse,
  AgentProfileConfig,
  CreateAgentRequest,
  AgentProfileRef,
} from "../types/agents";
import type { MdFileInfo, MdFileContent } from "../types/workspace";

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

  // Toggle agent enabled state
  toggleAgentEnabled: (agentId: string, enabled: boolean) =>
    request<{ success: boolean; agent_id: string; enabled: boolean }>(
      `/agents/${agentId}/toggle`,
      {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      },
    ),

  // Agent workspace files
  listAgentFiles: (agentId: string, all: boolean = false) =>
    request<MdFileInfo[]>(`/agents/${agentId}/files${all ? "?all=true" : ""}`),

  downloadSelectedFiles: async (agentId: string, files: string[]) => {
    const response = await fetch(
      getApiUrl(`/agents/${agentId}/files/download`),
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(getApiToken()
            ? { Authorization: `Bearer ${getApiToken()}` }
            : {}),
        },
        body: JSON.stringify({ files }),
      },
    );
    if (!response.ok) {
      throw new Error(
        `Download failed: ${response.status} ${response.statusText}`,
      );
    }
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `selected_files.zip`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
  },

  readAgentFile: (agentId: string, filename: string) =>
    request<MdFileContent>(
      `/agents/${agentId}/files/${filename
        .split("/")
        .map(encodeURIComponent)
        .join("/")}`,
    ),

  writeAgentFile: (agentId: string, filename: string, content: string) =>
    request<{ written: boolean; filename: string }>(
      `/agents/${agentId}/files/${filename
        .split("/")
        .map(encodeURIComponent)
        .join("/")}`,
      {
        method: "PUT",
        body: JSON.stringify({ content }),
      },
    ),

  // Agent memory files
  listAgentMemory: (agentId: string) =>
    request<MdFileInfo[]>(`/agents/${agentId}/memory`),
};
