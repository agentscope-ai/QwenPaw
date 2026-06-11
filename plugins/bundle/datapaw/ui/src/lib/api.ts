import type { PlanSnapshot } from "../task-graph/types";
import { DATAPAW_AGENT_ID } from "./constants";
import { getSelectedAgentId } from "./agent";

function host() {
  return (window as { QwenPaw?: { host?: { getApiUrl?: (p: string) => string; getApiToken?: () => string } } })
    .QwenPaw?.host;
}

export function getApiUrl(path: string): string {
  const h = host();
  if (h?.getApiUrl) return h.getApiUrl(path);
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `/api${normalized}`;
}

export function getApiToken(): string {
  const h = host();
  const fromHost = h?.getApiToken?.();
  if (fromHost) return fromHost;
  return localStorage.getItem("qwenpaw_auth_token") || "";
}

export function buildAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = getApiToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const agent = getSelectedAgentId() || DATAPAW_AGENT_ID;
  headers["X-Agent-Id"] = agent;
  return headers;
}

export interface TasksSummaryResponse {
  current_plan: PlanSnapshot | null;
  historical_plans?: Array<{
    id: string;
    name?: string;
    state?: string;
    finished_at?: string | null;
  }>;
}

export async function fetchTasksSummary(
  sessionId: string,
  userId = "default",
): Promise<TasksSummaryResponse | null> {
  const encoded = encodeURIComponent(sessionId);
  const url = getApiUrl(
    `/tasks/${encoded}?user_id=${encodeURIComponent(userId)}`,
  );
  console.info("[datapaw:tasks-api] GET summary", { sessionId, userId, url });
  const res = await fetch(url, { headers: buildAuthHeaders() });
  if (!res.ok) {
    console.warn("[datapaw:tasks-api] GET summary failed", {
      status: res.status,
      sessionId,
    });
    return null;
  }
  const data = await res.json();
  console.info("[datapaw:tasks-api] GET summary ok", {
    sessionId,
    hasPlan: Boolean(data?.current_plan),
    planId: data?.current_plan?.id,
    planName: data?.current_plan?.name,
  });
  return data;
}

export async function fetchHistoricalTaskPlan(
  sessionId: string,
  planId: string,
  userId = "default",
): Promise<PlanSnapshot | null> {
  const encodedSession = encodeURIComponent(sessionId);
  const encodedPlan = encodeURIComponent(planId);
  const url = getApiUrl(
    `/tasks/${encodedSession}/history/${encodedPlan}?user_id=${encodeURIComponent(userId)}`,
  );
  console.info("[datapaw:tasks-api] GET historical plan", {
    sessionId,
    planId,
    url,
  });
  const res = await fetch(url, { headers: buildAuthHeaders() });
  if (!res.ok) {
    console.warn("[datapaw:tasks-api] GET historical plan failed", {
      status: res.status,
      sessionId,
      planId,
    });
    return null;
  }
  const data = await res.json();
  const plan = data?.plan ?? null;
  console.info("[datapaw:tasks-api] GET historical plan ok", {
    sessionId,
    planId,
    hasPlan: Boolean(plan),
    planName: plan?.name,
  });
  return plan;
}

export interface TaskMutationResponse {
  detail: string;
}

export async function putPlanSop(
  sessionId: string,
  yaml: string,
  userId = "default",
): Promise<TaskMutationResponse> {
  const encoded = encodeURIComponent(sessionId);
  const url = getApiUrl(
    `/tasks/${encoded}/sop?user_id=${encodeURIComponent(userId)}`,
  );
  const res = await fetch(url, {
    method: "PUT",
    headers: {
      ...buildAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ yaml }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function subscribeDagEvents(
  sessionId: string,
  userId: string,
  onSnapshot: (plan: PlanSnapshot | null) => void,
  signal: AbortSignal,
): Promise<void> {
  const encoded = encodeURIComponent(sessionId);
  const url = getApiUrl(
    `/tasks/${encoded}/dag/events?user_id=${encodeURIComponent(userId)}`,
  );
  const res = await fetch(url, {
    headers: { ...buildAuthHeaders(), Accept: "text/event-stream" },
    signal,
  });
  if (!res.ok || !res.body) return;

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: false });
  let buffer = "";
  let eventName = "";
  let dataLines: string[] = [];

  const flush = () => {
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
      const parsed = JSON.parse(payload) as { current_plan?: PlanSnapshot | null };
      onSnapshot(parsed.current_plan ?? null);
    } catch {
      /* ignore */
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
        flush();
        continue;
      }
      if (line.startsWith("event:")) eventName = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
  }
  flush();
}
