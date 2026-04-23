import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

export interface SubTaskResponse {
  name: string;
  description: string;
  expected_outcome: string;
  outcome: string | null;
  state: "todo" | "in_progress" | "done" | "abandoned";
  created_at: string | null;
  finished_at: string | null;
}

export interface PlanStateResponse {
  id: string;
  name: string;
  description: string;
  expected_outcome: string;
  state: "todo" | "in_progress" | "done" | "abandoned";
  subtasks: SubTaskResponse[];
  created_at: string | null;
  finished_at: string | null;
  outcome: string | null;
}

export interface PlanConfigResponse {
  enabled: boolean;
}

export const planApi = {
  getCurrentPlan: (sessionId?: string) =>
    request<PlanStateResponse | null>(
      sessionId
        ? `/plan/current?session_id=${encodeURIComponent(sessionId)}`
        : "/plan/current",
    ),

  getPlanConfig: () => request<PlanConfigResponse>("/plan/config"),

  updatePlanConfig: (body: PlanConfigResponse) =>
    request<PlanConfigResponse>("/plan/config", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};

/**
 * Subscribe to plan updates via SSE using fetch streaming.
 * Returns an unsubscribe function.
 */
export function subscribePlanUpdates(
  onUpdate: (
    plan: PlanStateResponse | null,
    sessionId: string | undefined,
  ) => void,
  onError?: (err: unknown) => void,
): () => void {
  let aborted = false;
  const controller = new AbortController();

  async function connect() {
    while (!aborted) {
      try {
        const url = getApiUrl("/plan/stream");
        const response = await fetch(url, {
          headers: buildAuthHeaders(),
          signal: controller.signal,
        });

        if (!response.ok || !response.body) {
          throw new Error(`SSE connect failed: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!aborted) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.slice(6));
                if (data.type === "plan_update") {
                  onUpdate(data.plan ?? null, data.session_id);
                }
              } catch {
                // ignore parse errors
              }
            }
          }
        }
      } catch (err) {
        if (aborted) return;
        onError?.(err);
        // Reconnect after 3s
        await new Promise((r) => setTimeout(r, 3000));
      }
    }
  }

  connect();

  return () => {
    aborted = true;
    controller.abort();
  };
}
