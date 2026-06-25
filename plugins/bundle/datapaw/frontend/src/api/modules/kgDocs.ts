import { buildAuthHeaders } from "../authHeaders";
import { clearAuthToken, getApiUrl } from "../config";
import { request } from "../request";
import type {
  KgDocsApiEnvelope,
  KgDocsDeleteData,
  KgDocsListData,
  KgDocument,
} from "../types/kgDocs";

function ensureSuccess<T>(envelope: KgDocsApiEnvelope<T>): T {
  if (envelope.code !== 0 || envelope.data == null) {
    throw new Error(envelope.message || "Request failed");
  }
  return envelope.data;
}

async function parseEnvelope<T>(
  response: Response,
): Promise<KgDocsApiEnvelope<T>> {
  const contentType = response.headers.get("content-type") || "";
  const text = await response.text();

  if (response.status === 401) {
    clearAuthToken();
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    throw new Error("Not authenticated");
  }

  if (!contentType.includes("application/json")) {
    throw new Error(
      text || `Request failed: ${response.status} ${response.statusText}`,
    );
  }

  try {
    const envelope = JSON.parse(text) as KgDocsApiEnvelope<T>;
    if (!response.ok) {
      throw new Error(envelope.message || text);
    }
    return envelope;
  } catch (error) {
    if (error instanceof Error && error.message) {
      throw error;
    }
    throw new Error(text || "Invalid response");
  }
}

export const kgDocsApi = {
  listKgDocs: async (params: { page: number; pageSize: number }) => {
    const query = new URLSearchParams({
      page: String(params.page),
      page_size: String(params.pageSize),
    });
    const envelope = await request<KgDocsApiEnvelope<KgDocsListData>>(
      `/v1/docs?${query.toString()}`,
    );
    return ensureSuccess(envelope);
  },

  uploadKgDoc: async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch(getApiUrl("/v1/docs/upload"), {
      method: "POST",
      headers: buildAuthHeaders(),
      body: formData,
    });
    const envelope = await parseEnvelope<KgDocument>(response);
    return ensureSuccess(envelope);
  },

  deleteKgDoc: async (docId: string) => {
    const envelope = await request<KgDocsApiEnvelope<KgDocsDeleteData>>(
      `/v1/docs/${encodeURIComponent(docId)}`,
      { method: "DELETE" },
    );
    return ensureSuccess(envelope);
  },
};
