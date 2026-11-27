import { request } from "../request";

export interface HarnessCommand {
  name: string;
  description: string;
  accepts_arguments: boolean;
}

export interface HarnessApprovalPreset {
  id: string;
  name: string;
  description: string;
  settings: Record<string, unknown>;
}

export interface HarnessCapabilities {
  authentication: boolean;
  model_selection: boolean;
  reasoning_effort: boolean;
  reasoning_stream: boolean;
  tool_stream: boolean;
  session_resume: boolean;
  fork_mode?: "none" | "latest" | "turn";
  workspace_ui: boolean;
  native_skills_ui: boolean;
  native_tools_ui: boolean;
  native_mcp_ui: boolean;
  loop_modes: boolean;
  attachments: boolean;
  context_usage: boolean;
  skills_commands: boolean;
  qwenpaw_skills_projection: boolean;
  qwenpaw_mcp_projection: boolean;
  provider_skills_discovery: boolean;
  provider_mcp_discovery: boolean;
  mcp_tool_allowlist: boolean;
  commands: HarnessCommand[];
  approval_presets: HarnessApprovalPreset[];
}

export interface HarnessModel {
  id: string;
  name: string;
  description: string;
  is_default: boolean;
  reasoning_efforts: string[];
  default_reasoning_effort: string | null;
}

export interface HarnessDiscoveredMCPServer {
  name: string;
  provider_id: string;
  transport: string;
  enabled: boolean;
  auth_status: string;
  read_only: boolean;
  scope: "provider";
}

export interface HarnessDiscoveredSkill {
  name: string;
  description: string;
  provider_id: string;
  source: string;
  enabled: boolean;
  read_only: boolean;
  scope: "provider";
}

export const harnessApi = {
  listModels: (providerId: string) =>
    request<{ models: HarnessModel[]; message?: string }>(
      `/harnesses/${encodeURIComponent(providerId)}/models`,
      { timeout: 60_000 },
    ),
  listMCP: (providerId: string) =>
    request<{ servers: HarnessDiscoveredMCPServer[]; message?: string }>(
      `/harnesses/${encodeURIComponent(providerId)}/mcp`,
      { timeout: 60_000 },
    ),
  listSkills: (providerId: string) =>
    request<{ skills: HarnessDiscoveredSkill[]; message?: string }>(
      `/harnesses/${encodeURIComponent(providerId)}/skills`,
      { timeout: 60_000 },
    ),
};
