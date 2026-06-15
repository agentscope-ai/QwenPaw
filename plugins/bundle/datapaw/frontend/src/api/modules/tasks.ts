import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import { request } from "../request";
import type { PlanSnapshot } from "../../pages/Chat/components/TaskGraphPanel/types";
import { resolveTaskApiSessionId } from "../../pages/Chat/lib/taskApiSession";

export interface HistoricalPlanSummary {
  id: string;
  name: string;
  state: string;
  finished_at?: string | null;
}

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

export interface TasksSummaryResponse {
  current_plan: PlanSnapshot | null;
  historical_plans: HistoricalPlanSummary[];
  artifacts_summary: { total?: number };
}

export interface DagRuntimeSnapshot {
  current_plan: PlanSnapshot | null;
  storage?: { plans?: Record<string, PlanSnapshot> };
  artifacts?: TaskArtifact[];
  _pending_edits?: unknown[];
}

export interface TaskMutationResponse {
  ok: boolean;
  detail: string;
  extra?: Record<string, unknown>;
}

function tasksPath(sessionId: string, suffix = ""): string {
  const resolved = resolveTaskApiSessionId(sessionId) || sessionId;
  const encoded = encodeURIComponent(resolved);
  return `/tasks/${encoded}${suffix}`;
}

function parseContentDispositionFilename(header: string | null): string {
  if (!header) return "download.yaml";
  const match = header.match(/filename="([^"]+)"/i) ?? header.match(/filename=([^;\s]+)/i);
  return match?.[1]?.trim() || "download.yaml";
}

async function fetchYamlDownload(
  path: string,
  userId: string,
  query?: Record<string, string>,
): Promise<{ blob: Blob; filename: string }> {
  const params = new URLSearchParams({ user_id: userId, ...query });
  const url = getApiUrl(`${path}?${params.toString()}`);
  const res = await fetch(url, { headers: buildAuthHeaders() });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      text ? `Request failed: ${res.status} - ${text}` : `Request failed: ${res.status}`,
    );
  }
  const blob = await res.blob();
  return {
    blob,
    filename: parseContentDispositionFilename(res.headers.get("content-disposition")),
  };
}

function triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

export const tasksApi = {
  getSummary: (sessionId: string, userId: string) =>
    request<TasksSummaryResponse>(`${tasksPath(sessionId)}?user_id=${encodeURIComponent(userId)}`),

  getHistoryPlan: (sessionId: string, planId: string, userId: string) =>
    request<{ plan: PlanSnapshot }>(
      `${tasksPath(sessionId)}/history/${encodeURIComponent(planId)}?user_id=${encodeURIComponent(userId)}`,
    ),

  putSop: (sessionId: string, userId: string, yaml: string) =>
    request<TaskMutationResponse>(`${tasksPath(sessionId)}/sop?user_id=${encodeURIComponent(userId)}`, {
      method: "PUT",
      body: JSON.stringify({ yaml }),
    }),

  putDag: (sessionId: string, userId: string, yaml: string) =>
    request<TaskMutationResponse>(`${tasksPath(sessionId)}/dag?user_id=${encodeURIComponent(userId)}`, {
      method: "PUT",
      body: JSON.stringify({ yaml }),
    }),

  listFiles: (
    sessionId: string,
    userId: string,
    filters?: { graph_id?: string; node_id?: string },
  ) => {
    const params = new URLSearchParams({ user_id: userId });
    if (filters?.graph_id) params.set("graph_id", filters.graph_id);
    if (filters?.node_id) params.set("node_id", filters.node_id);
    return request<{ files: TaskArtifact[] }>(
      `${tasksPath(sessionId)}/files?${params.toString()}`,
    );
  },

  downloadActiveSop: (sessionId: string, userId: string) =>
    fetchYamlDownload(tasksPath(sessionId, "/sop"), userId),

  downloadActiveDag: (sessionId: string, userId: string, includeTrace = true) =>
    fetchYamlDownload(tasksPath(sessionId, "/dag"), userId, {
      include_trace: String(includeTrace),
    }),

  downloadHistorySop: (sessionId: string, planId: string, userId: string) =>
    fetchYamlDownload(
      `${tasksPath(sessionId)}/history/${encodeURIComponent(planId)}/sop`,
      userId,
    ),

  fetchActiveDagYamlText: async (
    sessionId: string,
    userId: string,
    includeTrace = false,
  ): Promise<string> => {
    const { blob } = await fetchYamlDownload(tasksPath(sessionId, "/dag"), userId, {
      include_trace: String(includeTrace),
    });
    return blob.text();
  },

  downloadBlob: triggerBlobDownload,

  /**
   * Subscribe to DAG snapshot SSE. Each `task_status` event delivers a full snapshot.
   */
  subscribeDagEvents: async (
    sessionId: string,
    userId: string,
    onSnapshot: (snapshot: DagRuntimeSnapshot) => void,
    signal: AbortSignal,
  ): Promise<void> => {
    const url = getApiUrl(
      `${tasksPath(sessionId)}/dag/events?user_id=${encodeURIComponent(userId)}`,
    );
    const res = await fetch(url, {
      headers: {
        ...buildAuthHeaders(),
        Accept: "text/event-stream",
      },
      signal,
    });

    if (!res.ok || !res.body) {
      throw new Error(`DAG SSE failed: ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8", { fatal: false });
    let buffer = "";
    let eventName = "";
    let dataLines: string[] = [];

    const flushEvent = () => {
      if (eventName !== "task_status" || dataLines.length === 0) {
        eventName = "";
        dataLines = [];
        return;
      }
      const payload = dataLines.join("\n");
      eventName = "";
      dataLines = [];
      if (!payload) return;
      try {
        onSnapshot(JSON.parse(payload) as DagRuntimeSnapshot);
      } catch {
        // ignore malformed frames
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n");
      buffer = parts.pop() ?? "";

      for (const rawLine of parts) {
        const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
        if (line === "") {
          flushEvent();
          continue;
        }
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
    }

    if (buffer) {
      const line = buffer.endsWith("\r") ? buffer.slice(0, -1) : buffer;
      if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    flushEvent();
  },
};
