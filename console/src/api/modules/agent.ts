import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type { AgentRequest, AgentsRunningConfig } from "../types";

export type TranscriptionErrorCode =
  | "TRANSCRIPTION_DISABLED"
  | "FILE_TOO_LARGE"
  | "UNSUPPORTED_FILE_TYPE";

export class TranscriptionError extends Error {
  status: number;
  code?: TranscriptionErrorCode;
  constructor(status: number, msg: string, code?: TranscriptionErrorCode) {
    super(`Transcription failed: ${status} ${msg}`);
    this.name = "TranscriptionError";
    this.status = status;
    this.code = code;
  }
}

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
    request<AgentsRunningConfig>("/workspace/running-config"),

  updateAgentRunningConfig: (config: AgentsRunningConfig) =>
    request<AgentsRunningConfig>("/workspace/running-config", {
      method: "PUT",
      body: JSON.stringify(config),
    }),

  getAgentLanguage: () => request<{ language: string }>("/workspace/language"),

  updateAgentLanguage: (language: string) =>
    request<{ language: string; copied_files: string[] }>(
      "/workspace/language",
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

  transcribeAudio: async (file: File | Blob): Promise<{ text: string }> => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(getApiUrl("/workspace/transcribe"), {
      method: "POST",
      headers: buildAuthHeaders(),
      body: formData,
    });
    if (!response.ok) {
      let msg = response.statusText;
      let code: TranscriptionErrorCode | undefined;
      try {
        const body = await response.json();
        if (typeof body?.detail === "object" && body.detail !== null) {
          code = body.detail.code;
          msg = body.detail.message || msg;
        } else if (typeof body?.detail === "string") {
          msg = body.detail;
        }
      } catch {
        // response body not JSON, use status text
      }
      throw new TranscriptionError(response.status, msg, code);
    }
    return response.json();
  },
};
