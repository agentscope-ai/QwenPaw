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

export interface CloneProjectRequest {
  target_id?: string;
  target_name?: string;
  include_pipeline_runs?: boolean;
}

export interface ProjectPipelineTemplateStep {
  id: string;
  name: string;
  kind: string;
  description: string;
  inputs?: Record<string, unknown>;
  prompt?: string;
  script?: string;
  outputs?: Record<string, unknown>;
  depends_on?: string[];
  input_bindings?: Record<string, string>;
  retry_policy?: Record<string, unknown>;
}

export interface PipelineValidationError {
  error_code: string;
  message: string;
  field_path: string;
  step_id: string;
  expected: string;
  actual: string;
  suggestion: string;
}

export interface AgentPipelineDraftInfo {
  md_path: string;
  md_relative_path: string;
  flow_memory_path: string;
  flow_memory_relative_path: string;
  md_mtime: number;
  revision: number;
  content_hash: string;
  validation_errors: PipelineValidationError[];
  compilation_status: string;
  steps: ProjectPipelineTemplateStep[];
}

export interface ProjectPipelineTemplateInfo {
  id: string;
  name: string;
  version: string;
  description: string;
  steps: ProjectPipelineTemplateStep[];
  revision?: number;
  content_hash?: string;
  md_mtime?: number;
  validation_errors?: PipelineValidationError[];
  compilation_status?: string;
}

export interface PlatformFlowTemplateInfo {
  id: string;
  name: string;
  version: string;
  description: string;
  steps: ProjectPipelineTemplateStep[];
  revision?: number;
  content_hash?: string;
  md_mtime?: number;
  validation_errors?: PipelineValidationError[];
  compilation_status?: string;
  tags: string[];
  source_project_id?: string | null;
  source_project_template_id?: string | null;
  source_project_template_version?: string | null;
}

export interface ProjectFlowInstanceInfo extends ProjectPipelineTemplateInfo {
  project_id: string;
  source_platform_template_id?: string | null;
  source_platform_template_version?: string | null;
}

export interface ImportPlatformTemplateRequest {
  platform_template_id: string;
  target_template_id?: string;
}

export interface PublishProjectTemplateRequest {
  platform_template_id?: string;
  bump?: "major" | "minor" | "patch";
  tags?: string[];
}

export interface PlatformTemplateVersionRecord {
  template_id: string;
  version: string;
  published_at: string;
  source_project_id?: string | null;
  source_project_template_id?: string | null;
  source_project_template_version?: string | null;
  bump: string;
}

export interface PipelineSaveStreamEvent {
  event: string;
  agent_id: string;
  pipeline_id: string;
  payload: Record<string, unknown>;
}

export interface ProjectPipelineRunSummary {
  id: string;
  template_id: string;
  status: string;
  created_at: string;
  updated_at: string;
  focus_chat_id?: string | null;
  focus_type?: string | null;
  focus_path?: string | null;
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

export interface ProjectPipelineCollaborationEvent {
  ts: string;
  event: string;
  step_id: string;
  role: string;
  actor: string;
  status: string;
  message: string;
  evidence: string[];
  metrics: Record<string, unknown>;
}

export interface ProjectPipelineArtifactRecord {
  artifact_id: string;
  path: string;
  name: string;
  kind: string;
  format: string;
  human_readable: boolean;
  run_id: string;
  producer_step_id?: string | null;
  producer_step_name?: string | null;
  consumer_step_ids: string[];
  consumer_step_names: string[];
  created_at: string;
}

export interface ProjectPipelineRunDetail extends ProjectPipelineRunSummary {
  project_id: string;
  parameters: Record<string, unknown>;
  steps: ProjectPipelineRunStep[];
  artifacts: string[];
  artifact_records: ProjectPipelineArtifactRecord[];
  flow_version: string;
  source_platform_template_id?: string | null;
  source_platform_template_version?: string | null;
  collaboration_events: ProjectPipelineCollaborationEvent[];
}

export interface CreateProjectPipelineRunRequest {
  template_id: string;
  parameters?: Record<string, unknown>;
}

export interface AgentsSquareSourceSpec {
  id: string;
  name: string;
  type: string;
  provider: string;
  url: string;
  branch: string;
  path: string;
  enabled: boolean;
  order: number;
  trust: string;
  license_hint: string;
  pinned: boolean;
}

export interface AgentsSquareSourcesPayload {
  version: number;
  cache: {
    ttl_sec: number;
  };
  install: {
    overwrite_default: boolean;
    preserve_workspace_files: boolean;
  };
  sources: AgentsSquareSourceSpec[];
}

export interface ValidateSquareSourceResponse {
  ok: boolean;
  normalized: AgentsSquareSourceSpec;
  warnings: string[];
}

export interface AgentSquareItem {
  source_id: string;
  agent_id: string;
  name: string;
  description: string;
  version: string;
  license: string;
  source_url: string;
  install_url: string;
  tags: string[];
  extra: Record<string, string>;
}

export interface AgentSquareSourceError {
  source_id: string;
  code: string;
  message: string;
  retryable: boolean;
}

export interface AgentSquareItemsResponse {
  items: AgentSquareItem[];
  source_errors: AgentSquareSourceError[];
  meta: {
    source_count?: number;
    item_count?: number;
    cache_hit?: boolean;
    [key: string]: unknown;
  };
}

export interface ImportAgentSquareRequest {
  source_id: string;
  agent_id: string;
  overwrite?: boolean;
  enable?: boolean;
  preferred_name?: string;
}

export interface ImportAgentSquareResponse {
  imported: boolean;
  id: string;
  name: string;
  workspace_dir: string;
  source: Record<string, string>;
}

export interface AgentSummary {
  id: string;
  name: string;
  description: string;
  workspace_dir: string;
  enabled: boolean;
  project_count?: number;
  projects?: AgentProjectSummary[];
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
  skill_names?: string[];
}

export interface AgentProfileRef {
  id: string;
  workspace_dir: string;
}
