import { request } from "../request";

export interface HarnessProvider {
  id: string;
  name: string;
  available: boolean;
  coming_soon: boolean;
  installed: boolean;
  authenticated: boolean;
  account: {
    type?: string;
    username?: string | null;
    email?: string | null;
    planType?: string;
  } | null;
  runtime_path: string | null;
  runtime_source: string | null;
  error: string | null;
  capabilities: HarnessCapabilities;
}

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

export interface HarnessLogin {
  type: string;
  loginId: string;
  authUrl?: string;
  verificationUrl?: string;
  userCode?: string;
  command?: string;
}

export const harnessApi = {
  list: () =>
    request<{ providers: HarnessProvider[] }>("/harnesses", {
      timeout: 60_000,
    }),
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
  status: (providerId: string, settings: Record<string, unknown> = {}) =>
    request<HarnessProvider>(
      `/harnesses/${encodeURIComponent(providerId)}/status`,
      {
        method: "POST",
        body: JSON.stringify({ settings }),
        timeout: 60_000,
      },
    ),
  login: (
    providerId: string,
    deviceCode = false,
    settings: Record<string, unknown> = {},
  ) =>
    request<HarnessLogin>(
      `/harnesses/${encodeURIComponent(providerId)}/login`,
      {
        method: "POST",
        body: JSON.stringify({
          device_code: deviceCode,
          settings,
        }),
        timeout: 60_000,
      },
    ),
  logout: (providerId: string, settings: Record<string, unknown> = {}) =>
    request<{ ok: boolean }>(
      `/harnesses/${encodeURIComponent(providerId)}/logout`,
      {
        method: "POST",
        body: JSON.stringify({ settings }),
      },
    ),
};
