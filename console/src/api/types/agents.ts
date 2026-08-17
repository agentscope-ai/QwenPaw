// Multi-agent management types

import type { ModelSlotConfig } from "./provider";
import type { HarnessCapabilities } from "../modules/harness";

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
  backend_capabilities?: Partial<HarnessCapabilities>;
  backend_model?: string | null;
  backend_reasoning_effort?: string | null;
  active_model?: ModelSlotConfig | null;
  /** PawApp id when this profile is an app-owned execution engine. */
  managed_by_app?: string | null;
  /** False for app-owned profiles that must not appear in normal Chat. */
  available_in_chat?: boolean;
}

export type AgentBackend = string;

export interface AgentListResponse {
  agents: AgentSummary[];
}

export interface ReorderAgentsResponse {
  success: boolean;
  agent_ids: string[];
}

export interface MemoryGraphNode {
  id: string;
  path: string;
  name: string;
  description: string;
  indexed: boolean;
  virtual?: boolean;
  section?: "daily" | "digest" | null;
  relative_path?: string | null;
}

export interface MemoryGraphEdge {
  source: string;
  target: string;
  target_anchor: string | null;
}

export interface MemoryGraphSnapshot {
  version: 1;
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
}

export interface AgentProfileConfig {
  id: string;
  name: string;
  description?: string;
  workspace_dir?: string;
  backend?: AgentBackend;
  backend_settings?: {
    binary?: string;
    model?: string;
    reasoning_effort?: string;
    [key: string]: unknown;
  };
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
  backend_settings?: {
    binary?: string;
    model?: string;
    reasoning_effort?: string;
    [key: string]: unknown;
  };
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
