import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import { resolveTaskApiSessionId } from "../../pages/Chat/lib/taskApiSession";

function buildArtifactUrl(
  filepath: string,
  sessionId: string,
  userId: string,
  kind: "preview" | "download",
): string {
  const resolvedSessionId =
    resolveTaskApiSessionId(sessionId, filepath) || sessionId;
  const encodedSession = encodeURIComponent(resolvedSessionId);
  const encodedPath = encodeURIComponent(filepath);
  const base = kind === "preview" ? "preview" : "download";
  return getApiUrl(
    `/tasks/${encodedSession}/files/${base}?path=${encodedPath}&user_id=${encodeURIComponent(userId)}`,
  );
}

function resolveArtifactUrl(
  _apiUrl: string | undefined,
  filepath: string,
  sessionId: string,
  userId: string,
  kind: "preview" | "download",
): string {
  // Always rebuild with the resolved backend session id. preview_url / download_url
  // from the API may embed the chat UUID when /files was called with the wrong id.
  return buildArtifactUrl(filepath, sessionId, userId, kind);
}

export const filesApi = {
  resolveArtifactUrl,

  /** 获取文件预览 URL */
  getPreviewUrl: (filepath: string, sessionId: string, userId: string): string =>
    buildArtifactUrl(filepath, sessionId, userId, "preview"),

  /** 获取文件下载 URL */
  getDownloadUrl: (filepath: string, sessionId: string, userId: string): string =>
    buildArtifactUrl(filepath, sessionId, userId, "download"),

  /**
   * 异步加载文本类文件内容（用于 MD/CSV/HTML 前端渲染）
   */
  fetchTextContent: async (
    filepath: string,
    sessionId: string,
    userId: string,
    _previewUrl?: string,
  ): Promise<string> => {
    const url = buildArtifactUrl(filepath, sessionId, userId, "preview");
    const res = await fetch(url, {
      headers: buildAuthHeaders(),
    });
    if (!res.ok) throw new Error(`Failed to load file: ${res.status}`);
    return res.text();
  },
};
