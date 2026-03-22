// Multi-agent management types

import type { OrchestrationConfig } from "./agent";
import type { ModelSlotConfig } from "./provider";

export interface AgentSummary {
  id: string;
  name: string;
  description: string;
  workspace_dir: string;
}

export interface AgentListResponse {
  agents: AgentSummary[];
}

export { OrchestrationConfig, ModelSlotConfig };

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
  orchestration?: OrchestrationConfig;
  active_model?: ModelSlotConfig;
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
