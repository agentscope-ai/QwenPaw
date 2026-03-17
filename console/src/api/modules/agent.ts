import { request } from "../request";
import type {
  AgentRequest,
  AgentsRunningConfig,
  LocalEmbeddingConfig,
  EmbeddingPresetModels,
  EmbeddingTestResult,
  ModelDownloadStatus,
} from "../types";

// Agent API
export const agentApi = {
  agentRoot: () => request<unknown>("/agent/"),

  healthCheck: () => request<unknown>("/agent/health"),

  agentApi: (body: AgentRequest) =>
    request<unknown>("/agent/process", {
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

  getAgentRunningConfig: () =>
    request<AgentsRunningConfig>("/agent/running-config"),

  updateAgentRunningConfig: (config: AgentsRunningConfig) =>
    request<AgentsRunningConfig>("/agent/running-config", {
      method: "PUT",
      body: JSON.stringify(config),
    }),

  getAgentLanguage: () => request<{ language: string }>("/agent/language"),

  updateAgentLanguage: (language: string) =>
    request<{ language: string; copied_files: string[] }>("/agent/language", {
      method: "PUT",
      body: JSON.stringify({ language }),
    }),

  // Audio / Transcription APIs
  getAudioMode: () => request<{ audio_mode: string }>("/agent/audio-mode"),

  updateAudioMode: (audio_mode: string) =>
    request<{ audio_mode: string }>("/agent/audio-mode", {
      method: "PUT",
      body: JSON.stringify({ audio_mode }),
    }),

  getTranscriptionProviders: () =>
    request<{
      providers: { id: string; name: string; available: boolean }[];
      configured_provider_id: string;
    }>("/agent/transcription-providers"),

  updateTranscriptionProvider: (provider_id: string) =>
    request<{ provider_id: string }>("/agent/transcription-provider", {
      method: "PUT",
      body: JSON.stringify({ provider_id }),
    }),

  getTranscriptionProviderType: () =>
    request<{ transcription_provider_type: string }>(
      "/agent/transcription-provider-type",
    ),

  updateTranscriptionProviderType: (transcription_provider_type: string) =>
    request<{ transcription_provider_type: string }>(
      "/agent/transcription-provider-type",
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
    }>("/agent/local-whisper-status"),

  // Local Embedding APIs
  getLocalEmbeddingConfig: () =>
    request<LocalEmbeddingConfig>("/config/agents/local-embedding"),

  updateLocalEmbeddingConfig: (config: LocalEmbeddingConfig) =>
    request<LocalEmbeddingConfig>("/config/agents/local-embedding", {
      method: "PUT",
      body: JSON.stringify(config),
    }),

  testLocalEmbeddingConfig: (config: LocalEmbeddingConfig) =>
    request<EmbeddingTestResult>("/config/agents/local-embedding/test", {
      method: "POST",
      body: JSON.stringify(config),
    }),

  downloadLocalEmbeddingModel: (config: LocalEmbeddingConfig) =>
    request<ModelDownloadStatus>("/config/agents/local-embedding/download", {
      method: "POST",
      body: JSON.stringify(config),
    }),

  getPresetEmbeddingModels: () =>
    request<EmbeddingPresetModels>("/config/agents/local-embedding/preset-models"),
};
