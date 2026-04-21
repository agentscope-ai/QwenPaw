import { request } from "../request";
import type {
  LocalActionResponse,
  LocalDownloadProgress,
  LocalDownloadSource,
  LocalModelInfo,
  LocalServerStatus,
  LocalServerUpdateStatus,
  StartLocalServerRequest,
} from "../types";

export const localModelApi = {
  getLocalServerStatus: () =>
    request<LocalServerStatus>("/local-models/server"),

  getLocalServerUpdateStatus: () =>
    request<LocalServerUpdateStatus>("/local-models/server/update"),

  startLlamacppDownload: () =>
    request<LocalActionResponse>("/local-models/server/download", {
      method: "POST",
    }),

  getLlamacppDownloadProgress: () =>
    request<LocalDownloadProgress>("/local-models/server/download"),

  cancelLlamacppDownload: () =>
    request<LocalActionResponse>("/local-models/server/download", {
      method: "DELETE",
    }),

  listRecommendedLocalModels: () =>
    request<LocalModelInfo[]>("/local-models/models"),

  startLocalModelDownload: (modelName: string, source: LocalDownloadSource) =>
    request<LocalActionResponse>("/local-models/models/download", {
      method: "POST",
      body: JSON.stringify({ model_name: modelName, source }),
    }),

  getLocalModelDownloadProgress: () =>
    request<LocalDownloadProgress>("/local-models/models/download"),

  cancelLocalModelDownload: () =>
    request<LocalActionResponse>("/local-models/models/download", {
      method: "DELETE",
    }),

  deleteLocalModel: (modelId: string) =>
    request<LocalActionResponse>(
      `/local-models/models/${encodeURIComponent(modelId)}`,
      {
        method: "DELETE",
      },
    ),

  startLocalServer: (body: StartLocalServerRequest) =>
    request<{ port: number; model_name: string }>("/local-models/server", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  stopLocalServer: () =>
    request<LocalActionResponse>("/local-models/server", {
      method: "DELETE",
    }),
};
