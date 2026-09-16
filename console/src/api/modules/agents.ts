import { request } from "../request";
import {
  withAgentRequestContext,
  type AgentRequestContext,
} from "./agentRequestContext";
import type {
  AgentListResponse,
  AgentProfileConfig,
  CreateAgentRequest,
  CopyAgentRequest,
  AgentProfileRef,
  MemoryGraphSnapshot,
  ReorderAgentsResponse,
  AgentMember,
  ShareableUser,
  AdminAgentSummary,
} from "../types/agents";
import type { MemoryScope } from "../../features/files-workspace/filesWorkspaceScope";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import { downloadFileFromUrl } from "../../utils/downloadFileFromUrl";

export interface PortableAgentImportResponse {
  agent_id: string;
  name: string;
  status: "draft";
  requires_reauthorization: true;
  dependencies: Record<string, string[]>;
}

export interface ReMeComponentMemoryUsage {
  bytes: number;
  human: string;
}

export interface ReMeMemoryStatusResponse {
  components: Record<string, Record<string, ReMeComponentMemoryUsage>>;
  components_total: string;
  process_rss: string;
  runtime: {
    worker: {
      status: "idle" | "busy" | "stopping" | "error";
      queue_pending: number;
      tasks_running: number;
    };
    auto_memory: {
      enabled: boolean;
      interval: number;
      active_sessions: number;
      sessions_with_pending: number;
      pending_turns: number;
    };
    recent: {
      last_completed_at: string | null;
      last_failed_at: string | null;
      last_error: string | null;
    };
    reindexing: boolean;
  };
}

export type ReMeMemoryRuntimeStatus = ReMeMemoryStatusResponse["runtime"];

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

  exportPortableAgent: (agentId: string, name: string) =>
    downloadFileFromUrl(
      getApiUrl(`/agents/${encodeURIComponent(agentId)}/portable-package`),
      `${name || agentId}.qwenpaw-agent.zip`,
      {
        headers: buildAuthHeaders(),
        errorMessage: "Agent portable export failed",
        preferResponseFilename: true,
      },
    ),

  importPortableAgent: async (file: File) => {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch(getApiUrl("/agents/portable-package/import"), {
      method: "POST",
      headers: buildAuthHeaders(),
      body,
    });
    if (!response.ok) {
      throw new Error(`Agent portable import failed: ${response.status}`);
    }
    return (await response.json()) as PortableAgentImportResponse;
  },

  // Update agent configuration
  updateAgent: (agentId: string, agent: AgentProfileConfig) =>
    request<AgentProfileConfig>(`/agents/${agentId}`, {
      method: "PUT",
      body: JSON.stringify(agent),
    }),

  updateBackendSettings: (
    agentId: string,
    settings: { model?: string; reasoning_effort?: string },
  ) =>
    request<AgentProfileConfig>(`/agents/${agentId}/backend-settings`, {
      method: "PATCH",
      body: JSON.stringify(settings),
    }),

  rebuildMemoryIndex: (agentId: string, context?: AgentRequestContext) =>
    request<{ status: "completed" }>(
      `/agents/${agentId}/memory/reindex`,
      withAgentRequestContext(
        {
          method: "POST",
          timeout: 10 * 60 * 1000,
        },
        context,
      ),
    ),

  getMemoryStatus: (
    agentId: string,
    signal?: AbortSignal,
    context?: AgentRequestContext,
  ) => {
    const path = `/agents/${agentId}/memory/status`;
    const options = withAgentRequestContext(
      signal ? { signal } : undefined,
      context,
    );
    return options
      ? request<ReMeMemoryStatusResponse>(path, options)
      : request<ReMeMemoryStatusResponse>(path);
  },

  getMemoryRuntimeStatus: (
    agentId: string,
    signal?: AbortSignal,
    context?: AgentRequestContext,
  ) => {
    const path = `/agents/${agentId}/memory/runtime-status`;
    const options = withAgentRequestContext(
      signal ? { signal } : undefined,
      context,
    );
    return options
      ? request<ReMeMemoryRuntimeStatus>(path, options)
      : request<ReMeMemoryRuntimeStatus>(path);
  },

  getMemoryGraph: (
    agentId: string,
    scope: MemoryScope = "public",
    context?: AgentRequestContext,
  ) => {
    const path =
      scope === "public"
        ? `/agents/${agentId}/memory/graph`
        : `/agents/${agentId}/memory/graph?scope=${scope}`;
    const options = withAgentRequestContext(undefined, context);
    return options
      ? request<MemoryGraphSnapshot>(path, options)
      : request<MemoryGraphSnapshot>(path);
  },

  // Delete agent
  deleteAgent: (agentId: string) =>
    request<{
      success: boolean;
      agent_id: string;
      soft_deleted?: boolean;
      references?: Record<string, number>;
    }>(`/agents/${agentId}`, {
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

  listMembers: (agentId: string) =>
    request<AgentMember[]>(`/agents/${agentId}/members`),

  listShareableUsers: () => request<ShareableUser[]>("/agent-sharing/users"),

  grantMember: (agentId: string, userId: string, role: AgentMember["role"]) =>
    request<{ success: boolean }>(`/agents/${agentId}/members/${userId}`, {
      method: "PUT",
      body: JSON.stringify({ role }),
    }),

  revokeMember: (agentId: string, userId: string) =>
    request<{ success: boolean }>(`/agents/${agentId}/members/${userId}`, {
      method: "DELETE",
    }),

  transferOwner: (agentId: string, userId: string) =>
    request<{ success: boolean }>(`/agents/${agentId}/transfer-owner`, {
      method: "POST",
      body: JSON.stringify({ new_owner_user_id: userId }),
    }),

  listAdminAgents: () =>
    request<{ agents: AdminAgentSummary[] }>("/admin/agents"),

  setPublication: (agentId: string, published: boolean) =>
    request<{ success: boolean; visibility: AdminAgentSummary["visibility"] }>(
      `/admin/agents/${agentId}/publication`,
      {
        method: "PATCH",
        body: JSON.stringify({ published }),
      },
    ),

  getAdminAgent: (agentId: string) =>
    request<AgentProfileConfig>(`/admin/agents/${agentId}/config`),

  updateAdminAgent: (agentId: string, agent: AgentProfileConfig) =>
    request<AgentProfileConfig>(`/admin/agents/${agentId}/config`, {
      method: "PUT",
      body: JSON.stringify(agent),
    }),
};
