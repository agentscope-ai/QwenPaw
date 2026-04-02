import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type {
  Plan,
  PlanSummary,
  PlanConfig,
  CreatePlanRequest,
  RevisePlanRequest,
  FinishPlanRequest,
} from "../types";

export const planApi = {
  getCurrentPlan: () => request<Plan | null>("/plan/current"),

  createPlan: (body: CreatePlanRequest) =>
    request<Plan>("/plan/create", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  revisePlan: (body: RevisePlanRequest) =>
    request<Plan>("/plan/revise", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  finishPlan: (body: FinishPlanRequest) =>
    request<{ success: boolean }>("/plan/finish", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getPlanHistory: () => request<PlanSummary[]>("/plan/history"),

  recoverPlan: (planId: string) =>
    request<Plan>(`/plan/recover/${planId}`, {
      method: "POST",
    }),

  deletePlan: (planId: string) =>
    request<{ success: boolean }>(`/plan/history/${planId}`, {
      method: "DELETE",
    }),

  getPlanConfig: () => request<PlanConfig>("/plan/config"),

  updatePlanConfig: (config: PlanConfig) =>
    request<PlanConfig>("/plan/config", {
      method: "PUT",
      body: JSON.stringify(config),
    }),

  confirmPlan: () =>
    request<{ confirmed: boolean; started_subtask_idx: number | null }>(
      "/plan/confirm",
      { method: "POST" },
    ),
};

/**
 * Subscribe to real-time plan updates via SSE.
 * Returns an unsubscribe function that closes the EventSource.
 */
export function subscribePlanUpdates(
  onUpdate: (plan: Plan | null) => void,
): () => void {
  const url = getApiUrl("/plan/stream");
  const headers = buildAuthHeaders();

  // EventSource does not support custom headers natively.
  // Append token as query param if auth is needed.
  const token = headers["Authorization"]?.replace("Bearer ", "");
  const agentId = headers["X-Agent-Id"];
  const params = new URLSearchParams();
  if (token) params.set("token", token);
  if (agentId) params.set("agent_id", agentId);
  const sep = url.includes("?") ? "&" : "?";
  const fullUrl = params.toString() ? `${url}${sep}${params.toString()}` : url;

  const es = new EventSource(fullUrl);

  es.addEventListener("plan_update", (event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data);
      onUpdate(data);
    } catch {
      // ignore malformed events
    }
  });

  es.onerror = () => {
    // EventSource auto-reconnects; we just log
    console.warn("Plan SSE connection error — will auto-reconnect");
  };

  return () => es.close();
}
