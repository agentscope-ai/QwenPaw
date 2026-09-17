import { TranscriptionError } from "./voiceErrors";
export { TranscriptionError } from "./voiceErrors";
import { request, type RequestOptions } from "../request";
import { captureVoiceScope, type VoiceScope } from "../voiceScope";

export interface VoiceSettings {
  audio_mode: string;
  transcription_provider_type: string;
  transcription_provider_id: string;
  transcription_model: string;
  transcription_local_model: string;
}
export interface VoiceConfiguration {
  settings: VoiceSettings;
  providers: { id: string; name: string; available: boolean }[];
  local_status: {
    available: boolean;
    ffmpeg_installed: boolean;
    whisper_installed: boolean;
    ready?: boolean;
    reason?: string | null;
  };
  local_models: string[];
}
export interface TranscriptionStatus {
  enabled: boolean;
  available: boolean;
  reason: string | null;
}
export async function voiceRequest<T>(
  path: string,
  scope: VoiceScope,
  options: RequestOptions = {},
): Promise<T> {
  scope.assert();
  const headers = new Headers(options.headers);
  headers.set("X-Agent-Id", scope.agentId);
  try {
    const result = await request<T>(path, {
      ...options,
      headers,
      signal: options.signal
        ? AbortSignal.any([scope.signal, options.signal])
        : scope.signal,
    });
    scope.assert();
    return result;
  } catch (error) {
    scope.assert();
    if (
      options.signal?.aborted ||
      (error instanceof DOMException && error.name === "AbortError")
    )
      throw new DOMException("Cancelled", "AbortError");
    const raw = error instanceof Error ? error.message : "";
    const code =
      raw.match(/"code"\s*:\s*"([A-Z_]+)"/)?.[1] ??
      (raw.includes("Request timeout") ? "TRANSCRIPTION_TIMEOUT" : undefined);
    throw new TranscriptionError(0, "", code);
  }
}
function assertAllowed(allowed: boolean) {
  if (!allowed) throw new TranscriptionError(403, "", "FORBIDDEN");
}
export function audioFilename(file: Blob): string {
  if (file instanceof File) return file.name;
  const extensions: Record<string, string> = {
    "audio/webm": "webm",
    "audio/mp4": "mp4",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/flac": "flac",
  };
  const extension = extensions[file.type.split(";")[0]];
  if (!extension)
    throw new TranscriptionError(400, "", "UNSUPPORTED_FILE_TYPE");
  return `recording.${extension}`;
}
async function upload(
  path: string,
  file: Blob,
  scope: VoiceScope,
  signal?: AbortSignal,
  conversationId?: string,
) {
  const form = new FormData();
  form.append("file", file, audioFilename(file));
  if (conversationId) form.append("conversation_id", conversationId);
  const result = await voiceRequest<{ text: string }>(path, scope, {
    method: "POST",
    body: form,
    signal,
    timeout: 120000,
  });
  if (!result.text?.trim())
    throw new TranscriptionError(422, "", "EMPTY_TRANSCRIPTION");
  return result;
}
export const voiceApi = {
  getSettings(scope: VoiceScope, signal?: AbortSignal) {
    assertAllowed(scope.canManage);
    return voiceRequest<VoiceConfiguration>(
      "/workspace/voice-transcription",
      scope,
      { signal },
    );
  },
  saveSettings(
    settings: VoiceSettings,
    scope: VoiceScope,
    signal?: AbortSignal,
  ) {
    assertAllowed(scope.canManage);
    return voiceRequest<VoiceConfiguration>(
      "/workspace/voice-transcription",
      scope,
      {
        method: "PUT",
        body: JSON.stringify(settings),
        signal,
      },
    );
  },
  status(scope: VoiceScope, signal?: AbortSignal) {
    assertAllowed(scope.canUse);
    return voiceRequest<TranscriptionStatus>(
      "/workspace/transcription-status",
      scope,
      { signal },
    );
  },
  transcribe(
    file: Blob,
    scope = captureVoiceScope(),
    signal?: AbortSignal,
    conversationId?: string,
  ) {
    assertAllowed(scope.canUse);
    return upload("/workspace/transcribe", file, scope, signal, conversationId);
  },
  test(file: Blob, scope: VoiceScope, signal?: AbortSignal) {
    assertAllowed(scope.canManage);
    return upload("/workspace/transcription-test", file, scope, signal);
  },
};
export function transcriptionErrorKey(error: unknown) {
  const code = error instanceof TranscriptionError ? error.code : undefined;
  const keys: Record<string, string> = {
    TRANSCRIPTION_DISABLED: "transcriptionDisabled",
    FILE_TOO_LARGE: "uploadTooLarge",
    UNSUPPORTED_FILE_TYPE: "unsupportedAudio",
    EMPTY_AUDIO: "emptyAudio",
    EMPTY_TRANSCRIPTION: "emptyText",
    EMPTY_TRANSCRIPT: "emptyText",
    TRANSCRIPTION_NOT_READY: "notReady",
    TRANSCRIPTION_BUSY: "busy",
    UPSTREAM_TIMEOUT: "transcriptionTimeout",
    TRANSCRIPTION_TIMEOUT: "transcriptionTimeout",
  };
  return `chat.speech.${keys[code ?? ""] ?? "transcriptionFailed"}`;
}
