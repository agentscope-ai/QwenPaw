// Multi-agent management types

import type { ModelSlotConfig } from "./provider";
import type { KnowledgeBaseSummary, KnowledgeReferenceItem } from "./knowledge";

export interface AgentSummary {
  id: string;
  name: string;
  description: string;
  workspace_dir: string;
  enabled: boolean;
  active_model?: ModelSlotConfig | null;
}

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
}

export interface AgentProfileRef {
  id: string;
  workspace_dir: string;
}

export interface AgentKnowledgeBaseListResponse {
  items: KnowledgeBaseSummary[];
}

export interface AgentKnowledgeConfigResponse {
  items: KnowledgeReferenceItem[];
  soul_path: string;
}

export interface AgentKnowledgePreviewResponse {
  knowledge_bases: KnowledgeBaseSummary[];
  knowledge_config: AgentKnowledgeConfigResponse;
}
