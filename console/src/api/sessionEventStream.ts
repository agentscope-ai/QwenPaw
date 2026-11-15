import { getApiUrl } from "./config";
import { buildAuthHeaders } from "./authHeaders";
import {
  getAccessSessionGeneration,
  subscribeAccessSessionGeneration,
} from "./authSession";

export interface SessionStreamOptions {
  agentId?: string;
  onConnectionChange?: (connected: boolean) => void;
}

/** Shared lifecycle for session status streams; EOF is a disconnect too. */
function connectSessionEvents<T extends { type: string }>(
  path: string,
  onEvent: (event: T) => void,
  onError?: (error: unknown) => void,
  options: SessionStreamOptions = {},
): () => void {
  const generation = getAccessSessionGeneration();
  const agentId = options.agentId ?? buildAuthHeaders()["X-Agent-Id"];
  let stopped = false;
  let running = false;
  let failures = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let attempt: AbortController | undefined;
  let idleTimer: ReturnType<typeof setTimeout> | undefined;
  const available = () =>
    !stopped &&
    !document.hidden &&
    navigator.onLine !== false &&
    generation === getAccessSessionGeneration();

  async function connect() {
    if (running || !available()) return;
    running = true;
    const controller = new AbortController();
    attempt = controller;
    const openingTimer = setTimeout(() => controller.abort(), 15_000);
    const started = Date.now();
    let receivedEvent = false;
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    try {
      const response = await fetch(getApiUrl(path), {
        headers: {
          ...buildAuthHeaders(),
          ...(agentId ? { "X-Agent-Id": agentId } : {}),
        },
        signal: controller.signal,
      });
      clearTimeout(openingTimer);
      if (controller.signal.aborted || !available()) return;
      if (!response.ok || !response.body)
        throw new Error(`SSE connect failed: ${response.status}`);
      reader = response.body.getReader();
      options.onConnectionChange?.(true);
      const decoder = new TextDecoder();
      let buffer = "";
      let data: string[] = [];
      const flush = () => {
        if (data.length === 0) return;
        const text = data.join("\n");
        data = [];
        let event: unknown;
        try {
          event = JSON.parse(text);
        } catch {
          return;
        }
        if (
          !event ||
          typeof event !== "object" ||
          !("type" in event) ||
          typeof event.type !== "string"
        )
          return;
        if (!controller.signal.aborted && available()) {
          receivedEvent = true;
          onEvent(event as T);
        }
      };
      const line = (value: string) => {
        const text = value.replace(/\r$/, "");
        if (!text) flush();
        else if (text.startsWith("data:"))
          data.push(text.slice(5).replace(/^ /, ""));
      };
      while (!controller.signal.aborted && available()) {
        // Server heartbeats arrive every 30s; replace a silently stalled stream.
        idleTimer = setTimeout(() => controller.abort(), 65_000);
        const { done, value } = await reader.read();
        clearTimeout(idleTimer);
        if (done) {
          buffer += decoder.decode();
          if (buffer) line(buffer);
          flush();
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        lines.forEach(line);
      }
      if (available() && !controller.signal.aborted)
        throw new Error("SSE stream ended");
    } catch (error) {
      if (available()) onError?.(error);
    } finally {
      clearTimeout(openingTimer);
      clearTimeout(idleTimer);
      controller.abort();
      if (reader) {
        await reader.cancel().catch(() => {});
        reader.releaseLock();
      }
      attempt = undefined;
      running = false;
      if (!stopped) options.onConnectionChange?.(false);
      // An empty 200 response must not reset the backoff on every reconnect.
      if (receivedEvent || Date.now() - started >= 30_000) failures = 0;
      const delay = Math.min(30_000, 3000 * 2 ** failures);
      failures = Math.min(failures + 1, 4);
      if (available()) timer = setTimeout(() => void connect(), delay);
    }
  }

  const onAvailability = () => {
    clearTimeout(timer);
    if (navigator.onLine === false || document.hidden) attempt?.abort();
    else void connect();
  };
  const stop = () => {
    if (stopped) return;
    stopped = true;
    clearTimeout(timer);
    attempt?.abort();
    window.removeEventListener("online", onAvailability);
    window.removeEventListener("offline", onAvailability);
    document.removeEventListener("visibilitychange", onAvailability);
    unsubscribeAuth();
  };
  const unsubscribeAuth = subscribeAccessSessionGeneration(stop);
  window.addEventListener("online", onAvailability);
  window.addEventListener("offline", onAvailability);
  document.addEventListener("visibilitychange", onAvailability);
  void connect();
  return stop;
}

type StreamEvent = { type: string };
interface Listener {
  event: (value: StreamEvent) => void;
  error?: (error: unknown) => void;
  connection?: (connected: boolean) => void;
}
interface SharedStream {
  listeners: Set<Listener>;
  connected: boolean;
  stop: () => void;
}
const streams = new Map<string, SharedStream>();

/** One transport per authenticated Agent and topic, regardless of panel count. */
export function subscribeSessionEvents<T extends StreamEvent>(
  path: string,
  onEvent: (event: T) => void,
  onError?: (error: unknown) => void,
  options: SessionStreamOptions = {},
): () => void {
  const agentId = options.agentId ?? buildAuthHeaders()["X-Agent-Id"];
  const key = JSON.stringify([
    getApiUrl(path),
    getAccessSessionGeneration(),
    agentId,
  ]);
  let shared = streams.get(key);
  const listener: Listener = {
    event: (value) => onEvent(value as T),
    error: onError,
    connection: options.onConnectionChange,
  };
  if (!shared) {
    shared = {
      listeners: new Set([listener]),
      connected: false,
      stop: () => {},
    };
    streams.set(key, shared);
    const entry = shared;
    const notify = (call: (listener: Listener) => void) => {
      for (const listener of entry.listeners) {
        try {
          call(listener);
        } catch {
          console.error("Session stream subscriber failed");
        }
      }
    };
    entry.stop = connectSessionEvents<StreamEvent>(
      path,
      (event) => notify((listener) => listener.event(event)),
      (error) => notify((listener) => listener.error?.(error)),
      {
        agentId,
        onConnectionChange: (connected) => {
          entry.connected = connected;
          notify((listener) => listener.connection?.(connected));
        },
      },
    );
  } else {
    shared.listeners.add(listener);
    listener.connection?.(shared.connected);
  }
  const entry = shared;
  return () => {
    entry.listeners.delete(listener);
    if (!entry.listeners.size) {
      entry.stop();
      if (streams.get(key) === entry) streams.delete(key);
    }
  };
}
