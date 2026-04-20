import { request } from "../request";
import { getApiToken, getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type {
  Plan,
  PlanConfig,
  RevisePlanRequest,
  FinishPlanRequest,
} from "../types";

/** Binds plan mutations to the active console chat session JSON on the server. */
function chatScopeHeaders(): Record<string, string> {
  const h: Record<string, string> = {};
  if (typeof window === "undefined") {
    return h;
  }
  const w = window as Window & {
    currentSessionId?: string;
    currentUserId?: string;
    currentChannel?: string;
  };
  if (w.currentSessionId) {
    h["X-Session-Id"] = w.currentSessionId;
  }
  h["X-User-Id"] = w.currentUserId || "default";
  if (w.currentChannel) {
    h["X-Channel"] = w.currentChannel;
  }
  return h;
}

function withChatScope(init: RequestInit = {}): RequestInit {
  return {
    ...init,
    headers: {
      ...chatScopeHeaders(),
      ...(init.headers as Record<string, string>),
    },
  };
}

export const planApi = {
  getCurrentPlan: () =>
    request<Plan | null>("/plan/current", { headers: chatScopeHeaders() }),

  revisePlan: (body: RevisePlanRequest) =>
    request<Plan>(
      "/plan/revise",
      withChatScope({
        method: "POST",
        body: JSON.stringify(body),
      }),
    ),

  finishPlan: (body: FinishPlanRequest) =>
    request<{ success: boolean }>(
      "/plan/finish",
      withChatScope({
        method: "POST",
        body: JSON.stringify(body),
      }),
    ),

  getPlanConfig: () => request<PlanConfig>("/plan/config"),

  updatePlanConfig: (config: PlanConfig) =>
    request<PlanConfig>("/plan/config", {
      method: "PUT",
      body: JSON.stringify(config),
    }),

  confirmPlan: () =>
    request<{ confirmed: boolean; started_subtask_idx: number | null }>(
      "/plan/confirm",
      withChatScope({ method: "POST" }),
    ),
};

/**
 * Subscribe to real-time plan updates via SSE.
 * When an API token is present, obtains a short-lived signed ticket
 * via POST (Bearer header) so the long-lived token is not put in the URL.
 * After auth errors or ticket expiry, closes and opens a new EventSource
 * with a fresh ticket (native EventSource would reuse an expired query string).
 * Returns a Promise of an unsubscribe function that closes the EventSource.
 */
export async function subscribePlanUpdates(
  onUpdate: (plan: Plan | null) => void,
): Promise<() => void> {
  let disposed = false;
  let es: EventSource | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectAttempt = 0;
  const maxReconnectAttempts = 12;

  const buildFullUrl = async (): Promise<string> => {
    const url = getApiUrl("/plan/stream");
    const headers = buildAuthHeaders();
    const agentId = headers["X-Agent-Id"];
    const params = new URLSearchParams();
    if (getApiToken()) {
      const { ticket } = await request<{ ticket: string }>(
        "/plan/stream/ticket",
        withChatScope({ method: "POST" }),
      );
      params.set("ticket", ticket);
    }
    if (agentId) params.set("agent_id", agentId);
    if (typeof window !== "undefined") {
      const w = window as Window & {
        currentSessionId?: string;
        currentChannel?: string;
      };
      if (w.currentSessionId) {
        params.set("session_id", w.currentSessionId);
      }
      if (w.currentChannel) {
        params.set("channel", w.currentChannel);
      }
    }
    const sep = url.includes("?") ? "&" : "?";
    return params.toString() ? `${url}${sep}${params.toString()}` : url;
  };

  const wireHandlers = (target: EventSource) => {
    target.addEventListener("plan_update", (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        onUpdate(data);
      } catch {
        // ignore malformed events
      }
    });
    target.addEventListener("open", () => {
      reconnectAttempt = 0;
      // On each (re)connect, fetch a snapshot so we recover a plan that was
      // created/revised before this EventSource was fully open. Only forward
      // non-null results: an empty snapshot may have been observed BEFORE a
      // plan_update that arrived in parallel, and we must not overwrite the
      // newer state with stale ``null``.
      request<Plan | null>("/plan/current", { headers: chatScopeHeaders() })
        .then((plan) => {
          if (plan !== null) onUpdate(plan);
        })
        .catch(() => {
          /* ignore snapshot pull errors; SSE updates still flow */
        });
    });
    target.onerror = () => {
      if (disposed) return;
      target.close();
      if (es === target) es = null;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (reconnectAttempt >= maxReconnectAttempts) {
        console.warn("Plan SSE: max reconnect attempts reached");
        return;
      }
      reconnectAttempt += 1;
      const delay = Math.min(500 * reconnectAttempt, 8000);
      reconnectTimer = setTimeout(() => {
        void openConnection();
      }, delay);
    };
  };

  const openConnection = async () => {
    if (disposed) return;
    try {
      es?.close();
      const fullUrl = await buildFullUrl();
      es = new EventSource(fullUrl);
      wireHandlers(es);
    } catch (e) {
      console.warn("Plan SSE: failed to connect", e);
      if (!disposed && reconnectAttempt < maxReconnectAttempts) {
        reconnectAttempt += 1;
        reconnectTimer = setTimeout(() => void openConnection(), 2000);
      }
    }
  };

  await openConnection();

  return () => {
    disposed = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    es?.close();
    es = null;
  };
}
