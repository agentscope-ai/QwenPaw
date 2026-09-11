import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";

export interface ToolCallInfo {
  tool_call_id: string;
  tool_name: string;
  session_id?: string;
  agent_id?: string;
  status: string;
  started_at?: number;
  elapsed: number;
  offload_remaining: number | null;
  kill_remaining: number | null;
  end_state?: string | null;
  force_cancelled?: boolean;
  extra?: Record<string, unknown>;
  /** Hook hard cap from start; extend-kill must stay below this. */
  max_internal_timeout_secs?: number | null;
  /** Present when the call was backgrounded (user or timeout). */
  offload_reason?: string | null;
}

export interface ToolCallListResponse {
  items: ToolCallInfo[];
  total: number;
}

export interface ExtendResult {
  status: string;
  tool_call_id: string;
  offload_remaining: number | null;
  kill_remaining: number | null;
}

export interface ToolCallOutput {
  tool_call_id: string;
  is_closed: boolean;
  final_state: string | null;
  content: Array<Record<string, unknown>>;
}

const BASE = "/tool-calls";

export function toolCallStreamUrl(sid: string, tcid: string): string {
  return getApiUrl(`${BASE}/${sid}/${tcid}/stream`);
}

/** Extract plain text from getOutput content blocks. */
export function extractOutputText(output: ToolCallOutput): string {
  if (!output.content?.length) return "";
  const parts: string[] = [];
  for (const block of output.content) {
    if (typeof block.text === "string") {
      parts.push(block.text);
    } else if (typeof block === "object" && block !== null) {
      try {
        parts.push(JSON.stringify(block));
      } catch {
        /* skip */
      }
    }
  }
  return parts.join("\n");
}

/**
 * Subscribe to ToolStream SSE via fetch (supports auth headers).
 * Calls onChunk for each data payload; onDone when type===done or stream ends.
 * Returns an abort function.
 */
export function subscribeToolCallStream(
  sid: string,
  tcid: string,
  handlers: {
    onChunk: (data: unknown) => void;
    onDone: () => void;
    onError: (err: unknown) => void;
  },
): () => void {
  const controller = new AbortController();
  const url = toolCallStreamUrl(sid, tcid);

  (async () => {
    try {
      const res = await fetch(url, {
        headers: buildAuthHeaders(),
        signal: controller.signal,
      });
      if (!res.ok) {
        handlers.onError(new Error(`stream HTTP ${res.status}`));
        return;
      }
      if (!res.body) {
        handlers.onError(new Error("stream has no body"));
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          try {
            const payload = JSON.parse(line.slice(6));
            if (payload.type === "done") {
              handlers.onDone();
              return;
            }
            handlers.onChunk(payload);
          } catch {
            /* ignore malformed */
          }
        }
      }
      handlers.onDone();
    } catch (err) {
      if ((err as { name?: string })?.name === "AbortError") return;
      handlers.onError(err);
    }
  })();

  return () => controller.abort();
}

export const toolCallsApi = {
  list: (sid: string) => request<ToolCallListResponse>(`${BASE}/${sid}`),

  getInfo: (sid: string, tcid: string) =>
    request<ToolCallInfo>(`${BASE}/${sid}/${tcid}`),

  getOutput: (sid: string, tcid: string) =>
    request<ToolCallOutput>(`${BASE}/${sid}/${tcid}/output`),

  offload: (sid: string, tcid: string) =>
    request(`${BASE}/${sid}/${tcid}/offload`, { method: "POST" }),

  cancel: (sid: string, tcid: string) =>
    request(`${BASE}/${sid}/${tcid}/cancel`, { method: "POST" }),

  preventOffload: (sid: string, tcid: string) =>
    request<ExtendResult>(`${BASE}/${sid}/${tcid}/extend-deadline`, {
      method: "POST",
      body: JSON.stringify({ target: "offload", no_deadline: true }),
    }),

  extendOffload: (sid: string, tcid: string, seconds = 30) =>
    request<ExtendResult>(`${BASE}/${sid}/${tcid}/extend-deadline`, {
      method: "POST",
      body: JSON.stringify({ target: "offload", seconds }),
    }),

  extendKill: (sid: string, tcid: string, seconds = 30) =>
    request<ExtendResult>(`${BASE}/${sid}/${tcid}/extend-deadline`, {
      method: "POST",
      body: JSON.stringify({ target: "kill", seconds }),
    }),

  getOffloadPolicy: () =>
    request<{ default_action: string }>("/settings/offload-policy"),

  setOffloadPolicy: (action: "keep_foreground" | "offload") =>
    request("/settings/offload-policy", {
      method: "PUT",
      body: JSON.stringify({ default_action: action }),
    }),
};
