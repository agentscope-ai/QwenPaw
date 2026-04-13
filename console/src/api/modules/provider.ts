import { request } from "../request";
import type {
  ProviderInfo,
  ProviderConfigRequest,
  ActiveModelsInfo,
  GetActiveModelsRequest,
  ModelSlotRequest,
  CreateCustomProviderRequest,
  AddModelRequest,
  ModelConfigRequest,
  LocalActionResponse,
  LocalModelConfig,
  LocalModelConfigRequest,
  TestConnectionResponse,
  TestProviderRequest,
  TestModelRequest,
  DiscoverModelsResponse,
  ProbeMultimodalResponse,
  SeriesResponse,
  DiscoverExtendedResponse,
  FilterModelsRequest,
  FilterModelsResponse,
} from "../types";

function buildActiveModelQuery(params?: GetActiveModelsRequest): string {
  if (!params?.scope && !params?.agent_id) {
    return "/models/active";
  }

  const searchParams = new URLSearchParams();
  if (params.scope) {
    searchParams.set("scope", params.scope);
  }
  if (params.agent_id) {
    searchParams.set("agent_id", params.agent_id);
  }

  return `/models/active?${searchParams.toString()}`;
}

export const providerApi = {
  listProviders: () => request<ProviderInfo[]>("/models"),

  configureProvider: (providerId: string, body: ProviderConfigRequest) =>
    request<ProviderInfo>(`/models/${encodeURIComponent(providerId)}/config`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  getActiveModels: (params?: GetActiveModelsRequest) =>
    request<ActiveModelsInfo>(buildActiveModelQuery(params)),

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

  configureModel: (
    providerId: string,
    modelId: string,
    body: ModelConfigRequest,
  ) =>
    request<ProviderInfo>(
      `/models/${encodeURIComponent(providerId)}/models/${encodeURIComponent(
        modelId,
      )}/config`,
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    ),

  configureLocalModelSettings: (body: LocalModelConfigRequest) =>
    request<LocalActionResponse>(`/local-models/config`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  getLocalModelConfig: () => request<LocalModelConfig>("/local-models/config"),

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

  discoverModels: (
    providerId: string,
    body?: TestProviderRequest,
    save: boolean = true,
  ) => {
    const url = new URL(
      `/models/${encodeURIComponent(providerId)}/discover`,
      window.location.origin,
    );
    url.searchParams.set("save", save.toString());
    return request<DiscoverModelsResponse>(url.pathname + url.search, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
  },

  probeMultimodal: (providerId: string, modelId: string) =>
    request<ProbeMultimodalResponse>(
      `/models/${encodeURIComponent(providerId)}/models/${encodeURIComponent(
        modelId,
      )}/probe-multimodal`,
      { method: "POST" },
    ),

  /* ---- OpenRouter specific endpoints ---- */

  getOpenRouterSeries: () =>
    request<SeriesResponse>("/models/openrouter/series"),

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
