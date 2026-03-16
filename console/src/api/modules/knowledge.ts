import { getApiUrl } from "../config";
import { request } from "../request";
import type {
  KnowledgeBulkIndexResult,
  KnowledgeConfig,
  KnowledgeHistoryBackfillRunResponse,
  KnowledgeHistoryBackfillStatus,
  KnowledgeIndexResult,
  KnowledgeClearResponse,
  KnowledgeSearchResponse,
  KnowledgeSourceContent,
  KnowledgeSourceSpec,
  KnowledgeSourcesResponse,
} from "../types";

export const knowledgeApi = {
  getKnowledgeConfig: () => request<KnowledgeConfig>("/knowledge/config"),

  updateKnowledgeConfig: (payload: KnowledgeConfig) =>
    request<KnowledgeConfig>("/knowledge/config", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  listKnowledgeSources: () =>
    request<KnowledgeSourcesResponse>("/knowledge/sources"),

  upsertKnowledgeSource: (payload: KnowledgeSourceSpec) =>
    request<KnowledgeSourceSpec>("/knowledge/sources", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  uploadKnowledgeFile: async (sourceId: string, file: File) => {
    const formData = new FormData();
    formData.append("source_id", sourceId);
    formData.append("file", file);

    const response = await fetch(getApiUrl("/knowledge/upload/file"), {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(
        `Upload failed: ${response.status} ${response.statusText}${
          text ? ` - ${text}` : ""
        }`,
      );
    }
    return (await response.json()) as { location: string; filename: string };
  },

  uploadKnowledgeDirectory: async (
    sourceId: string,
    files: Array<{ file: File; relativePath: string }>,
  ) => {
    const formData = new FormData();
    formData.append("source_id", sourceId);
    files.forEach(({ file, relativePath }) => {
      formData.append("files", file);
      formData.append("relative_paths", relativePath);
    });

    const response = await fetch(getApiUrl("/knowledge/upload/directory"), {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(
        `Upload failed: ${response.status} ${response.statusText}${
          text ? ` - ${text}` : ""
        }`,
      );
    }
    return (await response.json()) as { location: string; file_count: number };
  },

  deleteKnowledgeSource: (sourceId: string) =>
    request<{ deleted: boolean; source_id: string }>(
      `/knowledge/sources/${encodeURIComponent(sourceId)}`,
      {
        method: "DELETE",
      },
    ),

  clearKnowledge: (params?: { removeSources?: boolean }) =>
    request<KnowledgeClearResponse>(
      `/knowledge/clear?confirm=true&remove_sources=${
        params?.removeSources === false ? "false" : "true"
      }`,
      {
        method: "DELETE",
      },
    ),

  indexKnowledgeSource: (sourceId: string) =>
    request<KnowledgeIndexResult>(
      `/knowledge/sources/${encodeURIComponent(sourceId)}/index`,
      {
        method: "POST",
      },
    ),

  indexAllKnowledgeSources: () =>
    request<KnowledgeBulkIndexResult>("/knowledge/index", {
      method: "POST",
    }),

  getKnowledgeHistoryBackfillStatus: () =>
    request<KnowledgeHistoryBackfillStatus>("/knowledge/history-backfill/status"),

  runKnowledgeHistoryBackfillNow: () =>
    request<KnowledgeHistoryBackfillRunResponse>("/knowledge/history-backfill/run", {
      method: "POST",
    }),

  getKnowledgeSourceContent: (sourceId: string) =>
    request<KnowledgeSourceContent>(
      `/knowledge/sources/${encodeURIComponent(sourceId)}/content`,
    ),

  searchKnowledge: (params: {
    query: string;
    limit?: number;
    sourceIds?: string[];
    sourceTypes?: string[];
  }) => {
    const searchParams = new URLSearchParams({
      q: params.query,
      limit: String(params.limit ?? 10),
    });
    if (params.sourceIds?.length) {
      searchParams.set("source_ids", params.sourceIds.join(","));
    }
    if (params.sourceTypes?.length) {
      searchParams.set("source_types", params.sourceTypes.join(","));
    }
    return request<KnowledgeSearchResponse>(
      `/knowledge/search?${searchParams.toString()}`,
    );
  },
};