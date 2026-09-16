import { request, type RequestOptions } from "../request";
import { voiceApi } from "./voice";
export { TranscriptionError } from "./voiceErrors";
export type { TranscriptionErrorCode } from "./voiceErrors";
import type {
  AgentRequest,
  AgentsRunningConfig,
  EmbeddingModelConfig,
} from "../types";
import {
  withAgentRequestContext,
  type AgentRequestContext,
} from "./agentRequestContext";
import type {
  MemoryScope,
  MemoryScopeSummary,
} from "../../features/files-workspace/filesWorkspaceScope";

export interface EmbeddingTestResponse {
  success: boolean;
  configured_dimensions: number;
  actual_dimensions: number | null;
  latency_ms: number;
  message: string;
}

export type RunningConfigRuntimeStatus = {
  state: "applied" | "pending_reload";
};

export type AgentRunningConfigAccess = {
  agent_id: string;
  access_role: "owner" | "collaborator" | "user" | "admin_governance";
  can_view: boolean;
  can_edit: boolean;
  can_edit_project_files: boolean;
  can_edit_workspace_files: boolean;
  is_governance: boolean;
  visibility: "private" | "shared" | "public_candidate" | "public";
  owner_user_id: string | null;
};

export type AgentRunningConfigSummary = {
  agent_id: string;
  name: string;
  language: string;
  timezone: string;
  active_model: { provider_id: string; model: string } | null;
  model_switchable: boolean;
  access_role: AgentRunningConfigAccess["access_role"];
  can_edit: boolean;
  read_only_reason: string | null;
};

export type RunningConfigRequestContext = AgentRequestContext;

function requestRunningConfig<T>(
  path: string,
  context?: RunningConfigRequestContext,
  options?: RequestOptions,
): Promise<T> {
  const merged = withAgentRequestContext(options, context);
  return merged ? request<T>(path, merged) : request<T>(path);
}

// Agent API
export const agentApi = {
  agentRoot: () => request<unknown>("/agent/"),

  healthCheck: () => request<unknown>("/agent/health"),

  getMemoryScopes: (agentId: string, context?: RunningConfigRequestContext) =>
    requestRunningConfig<{ agent_id: string; scopes: MemoryScopeSummary[] }>(
      `/agents/${agentId}/memory/scopes`,
      context,
    ),

  rebuildMemoryIndex: (
    agentId: string,
    scope: MemoryScope,
    context?: RunningConfigRequestContext,
  ) =>
    requestRunningConfig<{ status: "completed" }>(
      `/agents/${agentId}/memory/reindex?scope=${scope}`,
      context,
      { method: "POST", timeout: 10 * 60 * 1000 },
    ),

  agentApi: (body: AgentRequest) =>
    request<unknown>("/console/chat", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getProcessStatus: () => request<unknown>("/agent/admin/status"),

  shutdownSimple: () =>
    request<void>("/agent/shutdown", {
      method: "POST",
    }),

  shutdown: () =>
    request<void>("/agent/admin/shutdown", {
      method: "POST",
    }),

  getAgentRunningConfig: (context?: RunningConfigRequestContext) =>
    requestRunningConfig<AgentsRunningConfig>(
      "/workspace/running-config",
      context,
    ),

  getAgentRunningConfigAccess: (context?: RunningConfigRequestContext) =>
    requestRunningConfig<AgentRunningConfigAccess>(
      "/workspace/access",
      context,
    ),

  getAgentRunningConfigSummary: (context?: RunningConfigRequestContext) =>
    requestRunningConfig<AgentRunningConfigSummary>(
      "/workspace/running-config/summary",
      context,
    ),

  getAgentRunningConfigVersion: (context?: RunningConfigRequestContext) =>
    requestRunningConfig<{ version: number }>(
      "/workspace/running-config/version",
      context,
    ),

  getAgentRunningConfigRuntimeStatus: (context?: RunningConfigRequestContext) =>
    requestRunningConfig<RunningConfigRuntimeStatus>(
      "/workspace/running-config/runtime-status",
      context,
    ),

  retryAgentRunningConfigReload: (context?: RunningConfigRequestContext) =>
    requestRunningConfig<RunningConfigRuntimeStatus>(
      "/workspace/running-config/reload",
      context,
      { method: "POST" },
    ),

  updateAgentRunningConfig: (
    config: AgentsRunningConfig,
    configVersion?: number,
    context?: RunningConfigRequestContext,
  ) =>
    requestRunningConfig<AgentsRunningConfig>(
      "/workspace/running-config",
      context,
      {
        method: "PUT",
        body: JSON.stringify(config),
        ...(configVersion == null
          ? {}
          : { headers: { "If-Match": `"${configVersion}"` } }),
        timeout: 10 * 60 * 1000,
      },
    ),

  testEmbedding: (
    config: EmbeddingModelConfig,
    context?: RunningConfigRequestContext,
  ) =>
    requestRunningConfig<EmbeddingTestResponse>(
      "/workspace/embedding/test",
      context,
      {
        method: "POST",
        body: JSON.stringify(config),
        timeout: 30 * 1000,
      },
    ),

  getAgentLanguage: (context?: RunningConfigRequestContext) =>
    requestRunningConfig<{ language: string }>("/workspace/language", context),

  updateAgentLanguage: (
    language: string,
    context?: RunningConfigRequestContext,
  ) =>
    requestRunningConfig<{ language: string; copied_files: string[] }>(
      "/workspace/language",
      context,
      {
        method: "PUT",
        body: JSON.stringify({ language }),
      },
    ),

  getAudioMode: () => request<{ audio_mode: string }>("/workspace/audio-mode"),

  updateAudioMode: (audio_mode: string) =>
    request<{ audio_mode: string }>("/workspace/audio-mode", {
      method: "PUT",
      body: JSON.stringify({ audio_mode }),
    }),

  getTranscriptionProviders: () =>
    request<{
      providers: { id: string; name: string; available: boolean }[];
      configured_provider_id: string;
    }>("/workspace/transcription-providers"),

  updateTranscriptionProvider: (provider_id: string) =>
    request<{ provider_id: string }>("/workspace/transcription-provider", {
      method: "PUT",
      body: JSON.stringify({ provider_id }),
    }),

  getTranscriptionProviderType: () =>
    request<{ transcription_provider_type: string }>(
      "/workspace/transcription-provider-type",
    ),

  updateTranscriptionProviderType: (transcription_provider_type: string) =>
    request<{ transcription_provider_type: string }>(
      "/workspace/transcription-provider-type",
      {
        method: "PUT",
        body: JSON.stringify({ transcription_provider_type }),
      },
    ),

  getLocalWhisperStatus: () =>
    request<{
      available: boolean;
      ffmpeg_installed: boolean;
      whisper_installed: boolean;
    }>("/workspace/local-whisper-status"),

  transcribeAudio: (...args: Parameters<typeof voiceApi.transcribe>) =>
    voiceApi.transcribe(...args),
};
