import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type {
  KnowledgeChunkConfig,
  KnowledgeConfigResponse,
  KnowledgeBaseSummary,
  KnowledgeChunk,
  KnowledgeDocumentSummary,
  KnowledgeReferenceItem,
  KnowledgeRetrievalConfig,
  KnowledgeUploadCapabilities,
  KnowledgeVectorConfig,
  PaginatedKnowledgeChunks,
} from "../types";

export const knowledgeApi = {
  listKnowledgeBases: () =>
    request<{ items: KnowledgeBaseSummary[] }>("/workspace/knowledge"),

  createKnowledgeBase: (payload: { name: string; id?: string }) =>
    request<{ item: KnowledgeBaseSummary }>("/workspace/knowledge", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getKnowledgeUploadCapabilities: () =>
    request<KnowledgeUploadCapabilities>("/workspace/knowledge/upload-capabilities"),

  getKnowledgeVectorConfig: () =>
    request<KnowledgeVectorConfig>("/workspace/knowledge/vector-config"),

  updateKnowledgeVectorConfig: (payload: KnowledgeVectorConfig) =>
    request<KnowledgeVectorConfig>("/workspace/knowledge/vector-config", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  getKnowledgeConfig: () =>
    request<KnowledgeConfigResponse>("/workspace/knowledge/config"),

  updateKnowledgeConfig: (items: KnowledgeReferenceItem[]) =>
    request<KnowledgeConfigResponse>("/workspace/knowledge/config", {
      method: "PUT",
      body: JSON.stringify({ items }),
    }),

  getKnowledgeBase: (knowledgeId: string) =>
    request<{
      item: KnowledgeBaseSummary;
      documents: KnowledgeDocumentSummary[];
    }>(`/workspace/knowledge/${encodeURIComponent(knowledgeId)}`),

  updateKnowledgeBase: (
    knowledgeId: string,
    payload: { name?: string; enabled?: boolean },
  ) =>
    request<{ item: KnowledgeBaseSummary }>(
      `/workspace/knowledge/${encodeURIComponent(knowledgeId)}`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
    ),

  deleteKnowledgeBase: (knowledgeId: string) =>
    request<{ deleted: boolean; name: string }>(
      `/workspace/knowledge/${encodeURIComponent(knowledgeId)}`,
      {
        method: "DELETE",
      },
    ),

  uploadKnowledgeDocument: async (
    knowledgeId: string,
    file: File,
    chunkConfig: KnowledgeChunkConfig,
    retrievalConfig: KnowledgeRetrievalConfig,
  ) => {
    const formData = new FormData();
    const safeRetrievalConfig = {
      indexing_technique: retrievalConfig.indexing_technique || "high_quality",
      search_method: retrievalConfig.search_method || "hybrid",
      top_k: retrievalConfig.top_k ?? 3,
      score_threshold_enabled: Boolean(retrievalConfig.score_threshold_enabled),
      score_threshold: retrievalConfig.score_threshold ?? 0.35,
      reranking_enable: Boolean(retrievalConfig.reranking_enable),
      weights: {
        vector_weight: retrievalConfig.weights?.vector_weight ?? 0.7,
        keyword_weight: retrievalConfig.weights?.keyword_weight ?? 0.3,
      },
    };
    const safeChunkConfig = {
      mode: chunkConfig.mode || "general",
      granularity: chunkConfig.granularity || "balanced",
      separator: chunkConfig.separator || "\\n\\n",
      normalize_whitespace: Boolean(chunkConfig.normalize_whitespace),
      llm_grouping: Boolean(chunkConfig.llm_grouping),
      chunk_size: chunkConfig.chunk_size ?? 1024,
      chunk_overlap: chunkConfig.chunk_overlap ?? 50,
      parent_separator: chunkConfig.parent_separator || "\\n\\n",
      parent_normalize_whitespace: Boolean(chunkConfig.parent_normalize_whitespace),
      parent_chunk_size: chunkConfig.parent_chunk_size ?? 1600,
      parent_chunk_overlap: chunkConfig.parent_chunk_overlap ?? 160,
      child_separator: chunkConfig.child_separator || "\\n",
      child_normalize_whitespace: Boolean(chunkConfig.child_normalize_whitespace),
      child_chunk_size: chunkConfig.child_chunk_size ?? 400,
      child_chunk_overlap: chunkConfig.child_chunk_overlap ?? 40,
    };
    formData.append("file", file);
    formData.append("indexing_technique", safeRetrievalConfig.indexing_technique);
    formData.append("search_method", safeRetrievalConfig.search_method);
    formData.append("top_k", String(safeRetrievalConfig.top_k));
    formData.append(
      "score_threshold_enabled",
      String(safeRetrievalConfig.score_threshold_enabled),
    );
    formData.append("score_threshold", String(safeRetrievalConfig.score_threshold));
    formData.append("reranking_enable", String(safeRetrievalConfig.reranking_enable));
    formData.append(
      "vector_weight",
      String(safeRetrievalConfig.weights.vector_weight),
    );
    formData.append(
      "keyword_weight",
      String(safeRetrievalConfig.weights.keyword_weight),
    );
    formData.append("mode", safeChunkConfig.mode);
    formData.append("granularity", safeChunkConfig.granularity);
    formData.append("separator", safeChunkConfig.separator);
    formData.append(
      "normalize_whitespace",
      String(safeChunkConfig.normalize_whitespace),
    );
    formData.append(
      "llm_grouping",
      String(safeChunkConfig.llm_grouping),
    );
    formData.append("chunk_size", String(safeChunkConfig.chunk_size));
    formData.append("chunk_overlap", String(safeChunkConfig.chunk_overlap));
    formData.append("parent_separator", safeChunkConfig.parent_separator);
    formData.append(
      "parent_normalize_whitespace",
      String(safeChunkConfig.parent_normalize_whitespace),
    );
    formData.append("parent_chunk_size", String(safeChunkConfig.parent_chunk_size));
    formData.append("parent_chunk_overlap", String(safeChunkConfig.parent_chunk_overlap));
    formData.append("child_separator", safeChunkConfig.child_separator);
    formData.append(
      "child_normalize_whitespace",
      String(safeChunkConfig.child_normalize_whitespace),
    );
    formData.append("child_chunk_size", String(safeChunkConfig.child_chunk_size));
    formData.append("child_chunk_overlap", String(safeChunkConfig.child_chunk_overlap));

    const response = await fetch(
      getApiUrl(`/workspace/knowledge/${encodeURIComponent(knowledgeId)}/documents/upload`),
      {
        method: "POST",
        headers: buildAuthHeaders(),
        body: formData,
      },
    );

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || "Upload failed");
    }

    return (await response.json()) as { document: KnowledgeDocumentSummary };
  },

  updateKnowledgeDocument: (
    knowledgeId: string,
    documentId: string,
    payload: { name?: string; enabled?: boolean },
  ) =>
    request<{ document: KnowledgeDocumentSummary }>(
      `/workspace/knowledge/${encodeURIComponent(knowledgeId)}/documents/${encodeURIComponent(documentId)}`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
    ),

  deleteKnowledgeDocument: (knowledgeId: string, documentId: string) =>
    request<{ deleted: boolean; name: string }>(
      `/workspace/knowledge/${encodeURIComponent(knowledgeId)}/documents/${encodeURIComponent(documentId)}`,
      {
        method: "DELETE",
      },
    ),

  listKnowledgeChunks: (
    knowledgeId: string,
    documentId: string,
    params?: { page?: number; page_size?: number; search?: string },
  ) => {
    const searchParams = new URLSearchParams();
    if (params?.page) searchParams.set("page", String(params.page));
    if (params?.page_size) searchParams.set("page_size", String(params.page_size));
    if (params?.search) searchParams.set("search", params.search);
    const query = searchParams.toString();
    return request<PaginatedKnowledgeChunks>(
      `/workspace/knowledge/${encodeURIComponent(knowledgeId)}/documents/${encodeURIComponent(documentId)}/chunks${query ? `?${query}` : ""}`,
    );
  },

  updateKnowledgeChunk: (
    knowledgeId: string,
    documentId: string,
    chunkId: string,
    payload: { name?: string; content?: string; enabled?: boolean },
  ) =>
    request<{ chunk: KnowledgeChunk }>(
      `/workspace/knowledge/${encodeURIComponent(knowledgeId)}/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(chunkId)}`,
      {
        method: "PUT",
        body: JSON.stringify(payload),
      },
    ),

  deleteKnowledgeChunk: (
    knowledgeId: string,
    documentId: string,
    chunkId: string,
  ) =>
    request<{ deleted: boolean; name: string }>(
      `/workspace/knowledge/${encodeURIComponent(knowledgeId)}/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(chunkId)}`,
      {
        method: "DELETE",
      },
    ),
};