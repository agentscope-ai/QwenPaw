import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

function resolveArtifactUrl(
  apiUrl: string | undefined,
  filepath: string,
  sessionId: string,
  userId: string,
  kind: "preview" | "download",
): string {
  if (apiUrl) {
    if (apiUrl.startsWith("http")) return apiUrl;
    if (apiUrl.startsWith("/api/")) {
      return getApiUrl(apiUrl.slice(4));
    }
    return getApiUrl(apiUrl);
  }
  const encodedPath = encodeURIComponent(filepath);
  const base = kind === "preview" ? "preview" : "download";
  return getApiUrl(`/tasks/${sessionId}/files/${base}?path=${encodedPath}&user_id=${userId}`);
}

export const filesApi = {
  resolveArtifactUrl,

  /**
   * 获取文件预览 URL
   */
  getPreviewUrl: (filepath: string, sessionId: string, userId: string): string => {
    const encodedPath = encodeURIComponent(filepath);
    return getApiUrl(`/tasks/${sessionId}/files/preview?path=${encodedPath}&user_id=${userId}`);
  },

  /**
   * 获取文件下载 URL
   */
  getDownloadUrl: (filepath: string, sessionId: string, userId: string): string => {
    const encodedPath = encodeURIComponent(filepath);
    return getApiUrl(`/tasks/${sessionId}/files/download?path=${encodedPath}&user_id=${userId}`);
  },

  /**
   * 异步加载文本类文件内容（用于 MD/CSV/HTML 前端渲染）
   */
  fetchTextContent: async (
    filepath: string,
    sessionId: string,
    userId: string,
    previewUrl?: string,
  ): Promise<string> => {
    const url = resolveArtifactUrl(previewUrl, filepath, sessionId, userId, "preview");
    const res = await fetch(url, {
      headers: buildAuthHeaders(),
    });
    if (!res.ok) throw new Error(`Failed to load file: ${res.status}`);
    return res.text();
  },
};
