import { request } from "../request";
import type {
  ProviderInfo,
  ProviderConfigRequest,
  ActiveModelsInfo,
  ModelSlotRequest,
  CreateCustomProviderRequest,
  AddModelRequest,
  TestConnectionResponse,
  TestProviderRequest,
  TestModelRequest,
  DiscoverModelsResponse,
  SeriesResponse,
  DiscoverExtendedResponse,
  FilterModelsRequest,
  FilterModelsResponse,
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

  /* ---- Test Connection ---- */

  testProviderConnection: (providerId: string, body?: TestProviderRequest) =>
    request<TestConnectionResponse>(
      `/models/${encodeURIComponent(providerId)}/test`,
      {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      },
    ),

  testModelConnection: (providerId: string, body: TestModelRequest) =>
    request<TestConnectionResponse>(
      `/models/${encodeURIComponent(providerId)}/models/test`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),

  discoverModels: (providerId: string, body?: TestProviderRequest) =>
    request<DiscoverModelsResponse>(
      `/models/${encodeURIComponent(providerId)}/discover`,
      {
        method: "POST",
        body: body ? JSON.stringify(body) : undefined,
      },
    ),

  /* ---- OpenRouter specific endpoints ---- */

  getOpenRouterSeries: () => request<SeriesResponse>("/models/openrouter/series"),

  discoverOpenRouterExtended: (body?: TestProviderRequest) =>
    request<DiscoverExtendedResponse>("/models/openrouter/discover-extended", {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    }),

  filterOpenRouterModels: (body: FilterModelsRequest) =>
    request<FilterModelsResponse>("/models/openrouter/models/filter", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
