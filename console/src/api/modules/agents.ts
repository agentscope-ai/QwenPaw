import { request } from "../request";
import type {
  AgentListResponse,
  AgentModelSettingsPatch,
  AgentProfileConfig,
  CreateAgentRequest,
  CopyAgentRequest,
  AgentProfileRef,
  MemoryGraphSnapshot,
  ReorderAgentsResponse,
} from "../types/agents";

export interface ReMeComponentMemoryUsage {
  bytes: number;
  human: string;
}

export interface MemoryCaptureTaskStatus {
  task_id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  queued_at: string | null;
  finished_at: string | null;
  message_count: number;
  result: string | null;
  error: string | null;
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
    };
    tasks: MemoryCaptureTaskStatus[];
    recent: {
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

  // Update agent configuration
  updateAgent: (agentId: string, agent: AgentProfileConfig) =>
    request<AgentProfileConfig>(`/agents/${agentId}`, {
      method: "PUT",
      body: JSON.stringify(agent),
    }),

  updateModelSettings: (agentId: string, settings: AgentModelSettingsPatch) =>
    request<AgentProfileConfig>(`/agents/${agentId}/model-settings`, {
      method: "PATCH",
      body: JSON.stringify(settings),
    }),

  updateBackendSettings: (
    agentId: string,
    settings: {
      model?: string | null;
      reasoning_effort?: string | null;
    },
  ) =>
    request<AgentProfileConfig>(`/agents/${agentId}/backend-settings`, {
      method: "PATCH",
      body: JSON.stringify(settings),
    }),

  rebuildMemoryIndex: (agentId: string) =>
    request<{ status: "completed" }>(`/agents/${agentId}/memory/reindex`, {
      method: "POST",
      timeout: 10 * 60 * 1000,
    }),

  getMemoryStatus: (agentId: string, signal?: AbortSignal) => {
    const path = `/agents/${agentId}/memory/status`;
    return signal
      ? request<ReMeMemoryStatusResponse>(path, { signal })
      : request<ReMeMemoryStatusResponse>(path);
  },

  getMemoryRuntimeStatus: (agentId: string, signal?: AbortSignal) => {
    const path = `/agents/${agentId}/memory/runtime-status`;
    return signal
      ? request<ReMeMemoryRuntimeStatus>(path, { signal })
      : request<ReMeMemoryRuntimeStatus>(path);
  },

  getMemoryGraph: (agentId: string) =>
    request<MemoryGraphSnapshot>(`/agents/${agentId}/memory/graph`),

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
