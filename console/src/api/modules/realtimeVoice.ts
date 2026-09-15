import { buildAuthHeaders } from "../authHeaders";
import { getApiUrl } from "../config";
import { request } from "../request";
import type {
  ModelSlotConfig,
  RealtimeVoiceMedia,
  RealtimeVoiceModelConfig,
} from "../types/provider";

export type { RealtimeVoiceMedia } from "../types/provider";

export interface RealtimeVoiceProviderCapabilities {
  id: string;
  label: string;
  models: RealtimeVoiceModelConfig[];
  regions: Array<{ id: string; label: string }>;
  vad_modes: string[];
  speech_models: Array<{ id: string; label: string }>;
  media: RealtimeVoiceMedia;
  endpoint_override: { scheme: "wss"; optional: boolean };
  supports_context_items: boolean;
  supports_manual_response: boolean;
  supports_output_cancel: boolean;
}

export interface EffectiveRealtimeVoiceModel {
  provider_id: string;
  model: string;
  region: string;
  realtime_model: string;
  endpoint: string | null;
  voice: string;
  language: string;
  vad_mode: string;
  vad_threshold: number;
  vad_silence_duration_ms: number;
  continuation_grace_ms: number;
  presentation_capacity: number;
  playback_timeout_seconds: number;
  max_history_turns: number;
  max_session_seconds: number;
}

export interface RealtimeVoiceCapabilities {
  protocol_version: number;
  agent_id: string;
  providers: RealtimeVoiceProviderCapabilities[];
  active_model: ModelSlotConfig | null;
  effective_model: EffectiveRealtimeVoiceModel | null;
  active_router_model: ModelSlotConfig | null;
  effective_router_model: ModelSlotConfig | null;
  credential_configured: boolean;
  configuration_error: { code: string; message: string } | null;
}

export interface RealtimeVoiceBootstrap {
  session_id: string;
  agent_id: string;
  chat_id: string;
  generation: number;
  protocol_version: number;
  media: RealtimeVoiceMedia;
  ws_url: string;
  token: string;
  expires_at: string;
  admission_mode: VoiceAdmissionMode;
}

export type VoiceAdmissionMode = "queue" | "steer";

export interface CreateRealtimeVoiceSession {
  chat_id?: string;
  previous_session_id?: string;
  replace_session_id?: string;
  admission_mode?: VoiceAdmissionMode;
}

export class RealtimeVoiceApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(
    message: string,
    code: string,
    status: number,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

async function createSession(
  body: CreateRealtimeVoiceSession,
): Promise<RealtimeVoiceBootstrap> {
  const response = await fetch(getApiUrl("/realtime-voice/sessions"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...buildAuthHeaders(),
    },
    body: JSON.stringify(body),
  });
  const payload = (await response.json().catch(() => ({}))) as Record<
    string,
    unknown
  >;
  if (!response.ok) {
    const detail =
      payload.detail && typeof payload.detail === "object"
        ? (payload.detail as Record<string, unknown>)
        : {};
    throw new RealtimeVoiceApiError(
      String(detail.message || "Unable to start Realtime Voice."),
      String(detail.code || "request_failed"),
      response.status,
      detail,
    );
  }
  return payload as unknown as RealtimeVoiceBootstrap;
}

export const realtimeVoiceApi = {
  getCapabilities: () =>
    request<RealtimeVoiceCapabilities>("/realtime-voice/capabilities"),
  createSession,
  endSession: (bootstrap: RealtimeVoiceBootstrap) =>
    request<{ released: boolean }>(
      `/realtime-voice/sessions/${encodeURIComponent(bootstrap.session_id)}`,
      { method: "DELETE", headers: { "X-Agent-Id": bootstrap.agent_id } },
    ),
};
