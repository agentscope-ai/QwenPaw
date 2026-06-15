import { buildAuthHeaders, getApiUrl } from "./api";
import { resolveTaskApiSessionId } from "./session-id";

export interface TaskArtifact {
  graph_id: string;
  node_id: string;
  name: string;
  path: string;
  mime_type: string;
  size_bytes: number;
  created_at?: string;
  preview_url?: string;
  download_url?: string;
}

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

export function resolveArtifactUrl(
  _apiUrl: string | undefined,
  filepath: string,
  sessionId: string,
  userId: string,
  kind: "preview" | "download",
): string {
  return buildArtifactUrl(filepath, sessionId, userId, kind);
}

export async function listTaskFiles(
  sessionId: string,
  userId = "default",
  filters?: { graph_id?: string; node_id?: string },
): Promise<TaskArtifact[]> {
  const resolved = resolveTaskApiSessionId(sessionId) || sessionId;
  const encoded = encodeURIComponent(resolved);
  const params = new URLSearchParams({ user_id: userId });
  if (filters?.graph_id) params.set("graph_id", filters.graph_id);
  if (filters?.node_id) params.set("node_id", filters.node_id);

  const res = await fetch(
    getApiUrl(`/tasks/${encoded}/files?${params.toString()}`),
    { headers: buildAuthHeaders() },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }
  const data = (await res.json()) as { files?: TaskArtifact[] };
  return data.files ?? [];
}

export function truncateArtifactPath(path: string, maxLen = 52): string {
  if (path.length <= maxLen) return path;
  const head = Math.max(12, Math.floor(maxLen * 0.38));
  const tail = Math.max(16, Math.floor(maxLen * 0.42));
  return `${path.slice(0, head)}...${path.slice(-tail)}`;
}

export async function downloadTaskArtifact(
  file: TaskArtifact,
  sessionId: string,
  userId: string,
): Promise<void> {
  const url = resolveArtifactUrl(
    file.download_url,
    file.path,
    sessionId,
    userId,
    "download",
  );
  const res = await fetch(url, { headers: buildAuthHeaders() });
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  const blob = await res.blob();
  const blobUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  anchor.download = file.name || file.path.split("/").pop() || "download";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(blobUrl);
}
