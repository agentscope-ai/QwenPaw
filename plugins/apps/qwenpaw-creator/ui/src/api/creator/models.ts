import type {
  ModelConfigData,
  ModelConnectionTestRequest,
  ConnectionTestResponse,
} from "@/contracts/creator";
import { creatorRequest, jsonBody, newClientId } from "./client";

export function getModelConfig(): Promise<ModelConfigData> {
  return creatorRequest("/models/config");
}

export interface ResolvedModels {
  video: { provider: string; model: string };
}

/**
 * Runtime-resolved model identity that execution actually uses.
 * Unlike getModelConfig (persisted-only), this reflects host tool config,
 * environment overrides and defaults — i.e. get_video_model_name() at submit.
 */
export function getResolvedModels(): Promise<ResolvedModels> {
  return creatorRequest("/models/resolved");
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
