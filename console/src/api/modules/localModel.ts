import { request } from "../request";
import type {
  LocalActionResponse,
  LocalDownloadProgress,
  LocalDownloadSource,
  LocalEngineId,
  LocalEngineInfo,
  LocalModelInfo,
  LocalServerStatus,
  LocalServerUpdateStatus,
  StartLocalServerRequest,
} from "../types";

function engineQuery(engine?: LocalEngineId): string {
  return engine ? `?engine=${encodeURIComponent(engine)}` : "";
}

export const localModelApi = {
  getLocalEngines: () => request<LocalEngineInfo[]>("/local-models/engines"),

  getLocalServerStatus: (engine?: LocalEngineId) =>
    request<LocalServerStatus>(`/local-models/server${engineQuery(engine)}`),

  getLocalServerUpdateStatus: (engine?: LocalEngineId) =>
    request<LocalServerUpdateStatus>(
      `/local-models/server/update${engineQuery(engine)}`,
    ),

  // Backwards-compatible aliases for the llama.cpp-only API.
  startLlamacppDownload: (engine?: LocalEngineId) =>
    request<LocalActionResponse>(
      `/local-models/server/download${engineQuery(engine)}`,
      {
        method: "POST",
      },
    ),

  getLlamacppDownloadProgress: (engine?: LocalEngineId) =>
    request<LocalDownloadProgress>(
      `/local-models/server/download${engineQuery(engine)}`,
    ),

  cancelLlamacppDownload: (engine?: LocalEngineId) =>
    request<LocalActionResponse>(
      `/local-models/server/download${engineQuery(engine)}`,
      {
        method: "DELETE",
      },
    ),

  startLocalEngineDownload: (engine?: LocalEngineId) =>
    request<LocalActionResponse>(
      `/local-models/server/download${engineQuery(engine)}`,
      {
        method: "POST",
      },
    ),

  getLocalEngineDownloadProgress: (engine?: LocalEngineId) =>
    request<LocalDownloadProgress>(
      `/local-models/server/download${engineQuery(engine)}`,
    ),

  cancelLocalEngineDownload: (engine?: LocalEngineId) =>
    request<LocalActionResponse>(
      `/local-models/server/download${engineQuery(engine)}`,
      {
        method: "DELETE",
      },
    ),

  listRecommendedLocalModels: (engine?: LocalEngineId) =>
    request<LocalModelInfo[]>(`/local-models/models${engineQuery(engine)}`),

  startLocalModelDownload: (
    modelName: string,
    source: LocalDownloadSource,
    engine?: LocalEngineId,
  ) =>
    request<LocalActionResponse>("/local-models/models/download", {
      method: "POST",
      body: JSON.stringify({
        model_name: modelName,
        source,
        engine,
      }),
    }),

  getLocalModelDownloadProgress: () =>
    request<LocalDownloadProgress>("/local-models/models/download"),

  cancelLocalModelDownload: () =>
    request<LocalActionResponse>("/local-models/models/download", {
      method: "DELETE",
    }),

  deleteLocalModel: (modelId: string, engine?: LocalEngineId) =>
    request<LocalActionResponse>(
      `/local-models/models/${encodeURIComponent(modelId)}${engineQuery(
        engine,
      )}`,
      {
        method: "DELETE",
      },
    ),

  startLocalServer: (body: StartLocalServerRequest) =>
    request<{
      port: number;
      model_info: LocalModelInfo;
      engine: LocalEngineId;
    }>("/local-models/server", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  stopLocalServer: (engine?: LocalEngineId) =>
    request<LocalActionResponse>(`/local-models/server${engineQuery(engine)}`, {
      method: "DELETE",
    }),
};
