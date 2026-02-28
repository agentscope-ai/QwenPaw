import { request } from "../request";
import type {
  ProviderInfo,
  ProviderConfigRequest,
  ActiveModelsInfo,
  ModelSlotRequest,
  VlmFallbacksRequest,
  VisionAudioSettingsRequest,
  VisionImageSettingsRequest,
  VisionVideoSettingsRequest,
  CreateCustomProviderRequest,
  AddModelRequest,
} from "../types";

export const providerApi = {
  listProviders: () => request<ProviderInfo[]>("/models"),

  configureProvider: (providerId: string, body: ProviderConfigRequest) =>
    request<ProviderInfo>(`/models/${encodeURIComponent(providerId)}/config`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  getActiveModels: () => request<ActiveModelsInfo>("/models/active"),

  setActiveLlm: (body: ModelSlotRequest) =>
    request<ActiveModelsInfo>("/models/active", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  setActiveVlm: (body: ModelSlotRequest) =>
    request<ActiveModelsInfo>("/models/active/vlm", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  setActiveVlmFallbacks: (body: VlmFallbacksRequest) =>
    request<ActiveModelsInfo>("/models/active/vlm/fallbacks", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  setVisionImageSettings: (body: VisionImageSettingsRequest) =>
    request("/models/vision/image", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  setVisionAudioSettings: (body: VisionAudioSettingsRequest) =>
    request("/models/vision/audio", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  setVisionVideoSettings: (body: VisionVideoSettingsRequest) =>
    request("/models/vision/video", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  /* ---- Custom provider CRUD ---- */

  createCustomProvider: (body: CreateCustomProviderRequest) =>
    request<ProviderInfo>("/models/custom-providers", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  deleteCustomProvider: (providerId: string) =>
    request<ProviderInfo[]>(
      `/models/custom-providers/${encodeURIComponent(providerId)}`,
      { method: "DELETE" },
    ),

  /* ---- Model CRUD (works for both built-in and custom providers) ---- */

  addModel: (providerId: string, body: AddModelRequest) =>
    request<ProviderInfo>(`/models/${encodeURIComponent(providerId)}/models`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  removeModel: (providerId: string, modelId: string) =>
    request<ProviderInfo>(
      `/models/${encodeURIComponent(providerId)}/models/${encodeURIComponent(
        modelId,
      )}`,
      { method: "DELETE" },
    ),
};
