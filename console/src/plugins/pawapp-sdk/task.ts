/**
 * pawapp-sdk/task.ts — PawTask: long-running task with SSE event stream.
 *
 * Usage:
 *   const task = paw.api.task('/generate', { script });
 *   task.on('progress', (data) => setProgress(data.step));
 *   task.on('image_ready', (data) => addImage(data.url));
 *   const result = await task.result;
 */
import { hostFetch } from "../hostSdk/fetch";
import type { PawTaskEventHandler, PawTaskHandle } from "./types";
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";

/**
 * Create a PawTask — posts to backend to start task, then connects
 * to SSE stream for realtime events.
 */
export function createPawTask(
  appId: string,
  path: string,
  params?: unknown,
): PawTaskHandle {
  const listeners = new Map<string, Set<PawTaskEventHandler>>();
  let taskId = "";
  let abortController: AbortController | null = new AbortController();

  // Promise that resolves with the final result
  let resolveResult!: (value: unknown) => void;
  let rejectResult!: (reason: unknown) => void;
  const resultPromise = new Promise<unknown>((resolve, reject) => {
    resolveResult = resolve;
    rejectResult = reject;
  });

  function emit(event: string, data: unknown) {
    const handlers = listeners.get(event);
    if (handlers) {
      for (const handler of handlers) {
        try {
          handler(data);
        } catch (e) {
          console.error(`[PawTask] Error in ${event} handler:`, e);
        }
      }
    }
  }

  // Start the task asynchronously
  (async () => {
    try {
      // POST to create task
      const normalized = path.startsWith("/") ? path : `/${path}`;
      // Use unified route: /{appId}/... -> /api/{appId}/... via getApiUrl
      const createRes = await hostFetch(`/${appId}${normalized}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: params != null ? JSON.stringify(params) : undefined,
        signal: abortController?.signal,
      });

      if (!createRes.ok) {
        throw new Error(
          `Task creation failed: ${createRes.status} ${createRes.statusText}`,
        );
      }

      const createData = await createRes.json();
      taskId = createData.task_id ?? createData.taskId ?? "";

      if (!taskId) {
        throw new Error("No task_id returned from backend");
      }

      // Connect to SSE stream using fetch-based approach
      // (EventSource doesn't support custom auth headers)
      const streamUrl = getApiUrl(`/${appId}/task/${taskId}/stream`);
      const sseRes = await fetch(streamUrl, {
        headers: {
          ...buildAuthHeaders(),
          Accept: "text/event-stream",
        },
        signal: abortController?.signal,
      });

      if (!sseRes.ok || !sseRes.body) {
        throw new Error(`SSE connection failed: ${sseRes.status}`);
      }

      const reader = sseRes.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const eventData = JSON.parse(line.slice(6));
              const eventType = eventData.type ?? eventData.event ?? "message";

              if (eventType === "done") {
                emit("done", eventData.data ?? eventData);
                resolveResult(eventData.data ?? eventData.result ?? null);
                return;
              } else if (eventType === "error") {
                const err = new Error(eventData.message ?? "Task failed");
                emit("error", eventData);
                rejectResult(err);
                return;
              } else {
                emit(eventType, eventData.data ?? eventData);
              }
            } catch {
              // Non-JSON line, emit as raw
              emit("message", line.slice(6));
            }
          }
        }
      }

      // Stream ended without explicit done/error
      resolveResult(null);
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        rejectResult(new Error("Task cancelled"));
      } else {
        rejectResult(err);
      }
    }
  })();

  const handle: PawTaskHandle = {
    on(event, handler) {
      if (!listeners.has(event)) {
        listeners.set(event, new Set());
      }
      listeners.get(event)!.add(handler);
      return handle;
    },
    off(event, handler) {
      listeners.get(event)?.delete(handler);
      return handle;
    },
    cancel() {
      abortController?.abort();
      abortController = null;
    },
    get result() {
      return resultPromise;
    },
    get taskId() {
      return taskId;
    },
  };

  return handle;
}
