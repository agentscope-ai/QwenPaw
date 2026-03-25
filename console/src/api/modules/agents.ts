import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type {
  AgentListResponse,
  AgentProfileConfig,
  CreateAgentRequest,
  AgentProfileRef,
  AgentsSquareSourcesPayload,
  AgentsSquareSourceSpec,
  ValidateSquareSourceResponse,
  AgentSquareItemsResponse,
  ImportAgentSquareRequest,
  ImportAgentSquareResponse,
  AgentProjectFileInfo,
  AgentProjectFileContent,
  AgentPipelineDraftInfo,
  PipelineSaveStreamEvent,
  ProjectPipelineTemplateInfo,
  ProjectPipelineRunSummary,
  ProjectPipelineRunDetail,
  CreateProjectPipelineRunRequest,
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

  // Agent project files
  listProjectFiles: (agentId: string, projectId: string) =>
    request<AgentProjectFileInfo[]>(
      `/agents/${agentId}/projects/${encodeURIComponent(projectId)}/files`,
    ),

  readProjectFile: (agentId: string, projectId: string, filePath: string) =>
    request<AgentProjectFileContent>(
      `/agents/${agentId}/projects/${encodeURIComponent(projectId)}/files/${filePath
        .split("/")
        .map((part) => encodeURIComponent(part))
        .join("/")}`,
    ),

  listAgentPipelineTemplates: (agentId: string) =>
    request<ProjectPipelineTemplateInfo[]>(
      `/agents/${agentId}/pipelines/templates`,
    ),

  saveAgentPipelineTemplate: (
    agentId: string,
    templateId: string,
    body: ProjectPipelineTemplateInfo,
    options?: { expectedRevision?: number },
  ) =>
    request<ProjectPipelineTemplateInfo>(
      `/agents/${agentId}/pipelines/templates/${encodeURIComponent(templateId)}${
        options?.expectedRevision !== undefined
          ? `?expectedRevision=${encodeURIComponent(String(options.expectedRevision))}`
          : ""
      }`,
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    ),

  saveAgentPipelineTemplateStream: async (
    agentId: string,
    templateId: string,
    body: ProjectPipelineTemplateInfo,
    onEvent: (event: PipelineSaveStreamEvent) => void,
    options?: { expectedRevision?: number; signal?: AbortSignal },
  ) => {
    const query =
      options?.expectedRevision !== undefined
        ? `?expectedRevision=${encodeURIComponent(String(options.expectedRevision))}`
        : "";
    const response = await fetch(
      getApiUrl(`/agents/${agentId}/pipelines/templates/${encodeURIComponent(templateId)}/save/stream${query}`),
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...buildAuthHeaders(),
        },
        body: JSON.stringify(body),
        signal: options?.signal,
      },
    );

    if (!response.ok || !response.body) {
      const text = await response.text();
      throw new Error(text || `SSE save failed: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let eventBreak = buffer.indexOf("\n\n");
      while (eventBreak >= 0) {
        const rawEvent = buffer.slice(0, eventBreak);
        buffer = buffer.slice(eventBreak + 2);

        const line = rawEvent
          .split("\n")
          .find((item) => item.startsWith("data:"));
        if (line) {
          const payload = line.slice(5).trim();
          if (payload) {
            onEvent(JSON.parse(payload) as PipelineSaveStreamEvent);
          }
        }

        eventBreak = buffer.indexOf("\n\n");
      }
    }
  },

  getPipelineDraft: (agentId: string, templateId: string) =>
    request<AgentPipelineDraftInfo>(
      `/agents/${agentId}/pipelines/templates/${encodeURIComponent(templateId)}/draft`,
    ),

  ensurePipelineDraft: (
    agentId: string,
    templateId: string,
    body: ProjectPipelineTemplateInfo,
  ) =>
    request<AgentPipelineDraftInfo>(
      `/agents/${agentId}/pipelines/templates/${encodeURIComponent(templateId)}/draft/ensure`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),

  listProjectPipelineTemplates: (agentId: string, projectId: string) =>
    request<ProjectPipelineTemplateInfo[]>(
      `/agents/${agentId}/projects/${encodeURIComponent(projectId)}/pipelines/templates`,
    ),

  listProjectPipelineRuns: (agentId: string, projectId: string) =>
    request<ProjectPipelineRunSummary[]>(
      `/agents/${agentId}/projects/${encodeURIComponent(projectId)}/pipelines/runs`,
    ),

  getProjectPipelineRun: (agentId: string, projectId: string, runId: string) =>
    request<ProjectPipelineRunDetail>(
      `/agents/${agentId}/projects/${encodeURIComponent(projectId)}/pipelines/runs/${encodeURIComponent(runId)}`,
    ),

  createProjectPipelineRun: (
    agentId: string,
    projectId: string,
    body: CreateProjectPipelineRunRequest,
  ) =>
    request<ProjectPipelineRunDetail>(
      `/agents/${agentId}/projects/${encodeURIComponent(projectId)}/pipelines/runs`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),

  // Agents Square
  getSquareSources: () =>
    request<AgentsSquareSourcesPayload>("/agents/square/sources"),

  getSquareDefaultSources: () =>
    request<AgentsSquareSourcesPayload>("/agents/square/sources/defaults"),

  resetSquareSources: () =>
    request<AgentsSquareSourcesPayload>("/agents/square/sources/reset", {
      method: "POST",
    }),

  updateSquareSources: (payload: AgentsSquareSourcesPayload) =>
    request<AgentsSquareSourcesPayload>("/agents/square/sources", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  validateSquareSource: (payload: AgentsSquareSourceSpec) =>
    request<ValidateSquareSourceResponse>("/agents/square/sources/validate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getSquareItems: (refresh = false) =>
    request<AgentSquareItemsResponse>(
      `/agents/square/items?refresh=${refresh ? "true" : "false"}`,
    ),

  importSquareAgent: (payload: ImportAgentSquareRequest) =>
    request<ImportAgentSquareResponse>("/agents/square/import", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
