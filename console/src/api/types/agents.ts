// Multi-agent management types

export interface AgentSummary {
  id: string;
  name: string;
  description: string;
  workspace_dir: string;
  enabled: boolean;
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
