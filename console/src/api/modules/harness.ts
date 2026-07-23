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
    email?: string | null;
    planType?: string;
  } | null;
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

export interface HarnessLogin {
  type: string;
  loginId: string;
  authUrl?: string;
  verificationUrl?: string;
  userCode?: string;
}

export const harnessApi = {
  list: () =>
    request<{ providers: HarnessProvider[] }>("/harnesses", {
      timeout: 60_000,
    }),
  listModels: (providerId: string) =>
    request<{ models: HarnessModel[] }>(
      `/harnesses/${encodeURIComponent(providerId)}/models`,
      { timeout: 60_000 },
    ),
  login: (providerId: string, deviceCode = false) =>
    request<HarnessLogin>(
      `/harnesses/${encodeURIComponent(providerId)}/login`,
      {
        method: "POST",
        body: JSON.stringify({ device_code: deviceCode }),
        timeout: 60_000,
      },
    ),
  logout: (providerId: string) =>
    request<{ ok: boolean }>(
      `/harnesses/${encodeURIComponent(providerId)}/logout`,
      {
        method: "POST",
      },
    ),
};
