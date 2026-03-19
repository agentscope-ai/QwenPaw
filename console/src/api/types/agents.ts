// Multi-agent management types

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

export interface AgentsSquareSourceSpec {
  id: string;
  name: string;
  type: "git";
  provider: "agency_markdown_repo" | "index_json_repo";
  url: string;
  branch?: string;
  path?: string;
  enabled: boolean;
  order: number;
  trust?: "official" | "community" | "custom";
  license_hint?: string;
  pinned?: boolean;
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

export interface AgentSquareMeta {
  generated_at: number;
  cache_ttl_sec: number;
  source_count: number;
  item_count: number;
  cache_hit: boolean;
  duration_ms: number;
}

export interface AgentSquareItemsResponse {
  items: AgentSquareItem[];
  source_errors: AgentSquareSourceError[];
  meta: AgentSquareMeta;
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
  source: {
    source_id: string;
    source_url: string;
    license: string;
    original_agent_id: string;
  };
}
