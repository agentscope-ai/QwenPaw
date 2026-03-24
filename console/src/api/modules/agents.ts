import { request } from "../request";
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
