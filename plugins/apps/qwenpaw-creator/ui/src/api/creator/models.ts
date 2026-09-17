import type {
  ModelConfigData,
  ModelConnectionTestRequest,
  ConnectionTestResponse,
} from "@/contracts/creator";
import { creatorRequest, hostToken, jsonBody, newClientId } from "./client";

export interface HostModelInfo {
  id: string;
  name: string;
}

export interface HostProviderInfo {
  id: string;
  name: string;
  base_url: string;
  freeze_url: boolean;
  models: HostModelInfo[];
  extra_models: HostModelInfo[];
  meta?: {
    base_url_options?: { label: string; value: string }[];
  };
}

let hostProvidersPromise: Promise<HostProviderInfo[]> | null = null;

export function getHostProviders(): Promise<HostProviderInfo[]> {
  if (hostProvidersPromise) return hostProvidersPromise;
  const headers: HeadersInit = { "Content-Type": "application/json" };
  const token = hostToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  hostProvidersPromise = fetch("/api/models", { headers })
    .then((r) => (r.ok ? r.json() : []))
    // The host may answer with an error envelope instead of a provider
    // array; anything non-array must degrade to "no presets" rather than
    // crash the modal on hostProviders.find.
    .then((data) => (Array.isArray(data) ? (data as HostProviderInfo[]) : []))
    .catch(() => [])
    .finally(() => {
      hostProvidersPromise = null;
    });
  return hostProvidersPromise;
}

export function getModelConfig(): Promise<ModelConfigData> {
  return creatorRequest("/models/config");
}

export interface ResolvedModels {
  video: {
    provider: string;
    model: string;
    /** Per-mode derived names — what a t2v/i2v element actually bills. */
    byMode?: Record<string, string>;
  };
  s2v?: { model: string };
}

/**
 * Runtime-resolved model identity that execution actually uses.
 * Unlike getModelConfig (persisted-only), this reflects host tool config,
 * environment overrides and defaults — i.e. get_video_model_name() at submit.
 */
export function getResolvedModels(): Promise<ResolvedModels> {
  return creatorRequest("/models/resolved");
}

export interface TtsModelCapability {
  model: string;
  label: string;
  family: "qwen-tts" | "cosyvoice";
  transport: "http" | "websocket";
  systemVoices: string[];
  supportsDesign: boolean;
}

export interface TtsCapabilities {
  default: string;
  models: TtsModelCapability[];
}

/**
 * Speech models this backend build supports. The configuration UI renders its
 * choices from here so it never offers a model the backend cannot drive, and
 * so it knows which models need a designed voice before they can speak.
 */
export function getTtsCapabilities(): Promise<TtsCapabilities> {
  return creatorRequest("/models/tts-capabilities");
}

export function saveModelConfig(
  config: ModelConfigData,
): Promise<{ ok: boolean }> {
  const id = newClientId("model-config");
  return creatorRequest("/models/config", {
    method: "POST",
    headers: { "Idempotency-Key": id },
    body: jsonBody(config),
  });
}

export function testModelConnection(
  request: ModelConnectionTestRequest,
): Promise<ConnectionTestResponse> {
  return creatorRequest("/models/test", {
    method: "POST",
    body: jsonBody(request),
  });
}

export function patchModelConfigSection(
  section: string,
  data: Record<string, unknown>,
): Promise<{ ok: boolean }> {
  const id = newClientId("model-config-patch");
  return creatorRequest(`/models/config/${section}`, {
    method: "PATCH",
    headers: { "Idempotency-Key": id },
    body: jsonBody(data),
  });
}

export function patchExecutionAuthorization(
  mode: "required" | "allow_all",
): Promise<{ ok: boolean }> {
  const id = newClientId("execution-auth");
  return creatorRequest("/models/config/execution-authorization", {
    method: "PATCH",
    headers: { "Idempotency-Key": id },
    body: jsonBody({ mode }),
  });
}

export function patchCreationCheckpoints(
  mode: "required" | "skip",
  executionMode: "delegated" | "co_creation" | "fine_tuning" = "co_creation",
): Promise<{ ok: boolean }> {
  const id = newClientId("creation-checkpoints");
  return creatorRequest("/models/config/creation-checkpoints", {
    method: "PATCH",
    headers: { "Idempotency-Key": id },
    body: jsonBody({ mode, execution_mode: executionMode }),
  });
}

export function patchMediaReview(
  mode: "required" | "auto_approve",
): Promise<{ ok: boolean }> {
  const id = newClientId("media-review");
  return creatorRequest("/models/config/media-review", {
    method: "PATCH",
    headers: { "Idempotency-Key": id },
    body: jsonBody({ mode }),
  });
}

export function patchPermissionMode(mode: {
  execution: "required" | "allow_all";
  checkpoints: "required" | "skip";
  mediaReview: "required" | "auto_approve";
}): Promise<{ ok: boolean }> {
  const id = newClientId("permission-mode");
  return creatorRequest("/models/config/permission-mode", {
    method: "PATCH",
    headers: { "Idempotency-Key": id },
    body: jsonBody({
      execution_authorization: mode.execution,
      creation_checkpoints: mode.checkpoints,
      media_review: mode.mediaReview,
    }),
  });
}

export function patchSelfReview(
  tiers: Partial<{
    sync_enabled: boolean;
    media_enabled: boolean;
    render_enabled: boolean;
  }>,
): Promise<{ ok: boolean }> {
  const id = newClientId("self-review");
  return creatorRequest("/models/config/self-review", {
    method: "PATCH",
    headers: { "Idempotency-Key": id },
    body: jsonBody(tiers),
  });
}

export function getRealApiKey(section: string): Promise<{ api_key: string }> {
  return creatorRequest(`/models/real-api-key/${section}`);
}

export function getHostProviderApiKey(
  providerId: string,
): Promise<{ api_key: string | null }> {
  return creatorRequest(`/models/host-provider/${providerId}/api-key`);
}
