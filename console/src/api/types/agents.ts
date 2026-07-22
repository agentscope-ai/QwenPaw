// Multi-agent management types

import type { ModelSlotConfig } from "./provider";

export type AgentStartupStatus =
  | "disabled"
  | "pending"
  | "starting"
  | "running"
  | "failed";

export interface AgentSummary {
  id: string;
  name: string;
  description: string;
  workspace_dir: string;
  enabled: boolean;
  pinned?: boolean;
  startup_status?: AgentStartupStatus;
  backend: AgentBackend;
  active_model?: ModelSlotConfig | null;
}

export type AgentBackend = "qwenpaw" | "codex";

export interface AgentListResponse {
  agents: AgentSummary[];
}

export interface ReorderAgentsResponse {
  success: boolean;
  agent_ids: string[];
}

export interface AgentProfileConfig {
  id: string;
  name: string;
  description?: string;
  workspace_dir?: string;
  backend?: AgentBackend;
  backend_project_dir?: string | null;
  approval_level?: string;
  active_model?: ModelSlotConfig | null;
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
  id?: string;
  name: string;
  description?: string;
  workspace_dir?: string;
  language?: string;
  skill_names?: string[];
  active_model?: ModelSlotConfig | null;
  backend?: AgentBackend;
  backend_project_dir?: string;
}

export interface CopyAgentRequest {
  name?: string;
  copy_agent_json?: true;
  copy_md_files?: boolean;
  copy_skills?: boolean;
  copy_jobs?: boolean;
}

export interface AgentProfileRef {
  id: string;
  workspace_dir: string;
  enabled?: boolean;
  pinned?: boolean;
}
