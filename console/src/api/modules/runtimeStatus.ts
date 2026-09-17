import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

export type RuntimeStatusKind = "running" | "failed" | "completed" | "idle";

export interface RuntimeStatus {
  type: "runtime_status";
  event_id: string;
  agent_id: string;
  session_id: string;
  root_session_id: string;
  chat_id?: string | null;
  stage: string;
  status: RuntimeStatusKind;
  message: string;
  detail: Record<string, unknown>;
  ts: number;
}

export const runtimeStatusApi = {
  getCurrent: (sessionId: string) =>
    request<RuntimeStatus | null>(
      `/runtime-status/current?session_id=${encodeURIComponent(sessionId)}`,
    ),
};

export function subscribeRuntimeStatusUpdates(
  onUpdate: (
    status: RuntimeStatus | null,
    sessionId: string | undefined,
    rootSessionId: string | undefined,
  ) => void,
  onError?: (err: unknown) => void,
): () => void {
  let aborted = false;
  const controller = new AbortController();

  async function connect() {
    while (!aborted) {
      try {
        const response = await fetch(getApiUrl("/runtime-status/stream"), {
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
            if (!line.startsWith("data: ")) continue;
            try {
              const data = JSON.parse(line.slice(6));
              if (data.type === "runtime_status") {
                const next =
                  data.status === "completed" || data.status === "idle"
                    ? null
                    : (data as RuntimeStatus);
                onUpdate(next, data.session_id, data.root_session_id);
              }
            } catch {
              // ignore malformed payloads
            }
          }
        }
      } catch (err) {
        if (aborted) return;
        onError?.(err);
        await new Promise((resolve) => setTimeout(resolve, 3000));
      }
    }
  }

  connect();

  return () => {
    aborted = true;
    controller.abort();
  };
}
