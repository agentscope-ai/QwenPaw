// Multi-agent management types
export interface AgentProjectSummary {
  id: string;
  name: string;
  description: string;
  status: string;
  workspace_dir: string;
  data_dir: string;
  metadata_file: string;
  tags: string[];
  updated_time: string;
}

export interface AgentProjectFileInfo {
  filename: string;
  path: string;
  size: number;
  modified_time: string;
}

export interface AgentProjectFileContent {
  content: string;
}

export interface ProjectPipelineTemplateStep {
  id: string;
  name: string;
  kind: string;
  description: string;
}

export interface ProjectPipelineTemplateInfo {
  id: string;
  name: string;
  version: string;
  description: string;
  steps: ProjectPipelineTemplateStep[];
}

export interface ProjectPipelineRunSummary {
  id: string;
  template_id: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ProjectPipelineRunStep {
  id: string;
  name: string;
  kind: string;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  metrics: Record<string, unknown>;
  evidence: string[];
}

export interface ProjectPipelineRunDetail extends ProjectPipelineRunSummary {
  project_id: string;
  parameters: Record<string, unknown>;
  steps: ProjectPipelineRunStep[];
  artifacts: string[];
}

export interface CreateProjectPipelineRunRequest {
  template_id: string;
  parameters?: Record<string, unknown>;
}
export interface AgentSummary {
  id: string;
  name: string;
  description: string;
  workspace_dir: string;
}

export interface AgentListResponse {
  agents: AgentSummary[];
}

export interface AgentProfileConfig {
  id: string;
  name: string;
  description?: string;
  workspace_dir?: string;
  channels?: unknown;
  mcp?: unknown;
  heartbeat?: unknown;
  running?: unknown;
  llm_routing?: unknown;
  system_prompt_files?: string[];
  tools?: unknown;
  security?: unknown;
}

export interface CreateAgentRequest {
  name: string;
  description?: string;
  workspace_dir?: string;
  language?: string;
}

export interface AgentProfileRef {
  id: string;
  workspace_dir: string;
}
