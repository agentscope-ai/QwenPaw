/**
 * Subscribe to workspace file-change SSE stream.
 *
 * Uses a module-level singleton so that multiple React components can call
 * `useWorkspaceWatch` without opening redundant SSE connections – only one
 * persistent connection is maintained and events are fanned out to all
 * registered listeners.
 *
 * Usage:
 *   useWorkspaceWatch((events) => { ... })
 */

import { useEffect, useRef } from "react";
import { workspaceApi } from "../api/modules/workspace";
import { buildAuthHeaders } from "../api/authHeaders";

export interface FileChangeEvent {
  change: "added" | "modified" | "deleted";
  path: string;
}

type FileChangeCallback = (events: FileChangeEvent[]) => void;

// ---------------------------------------------------------------------------
// Singleton SSE manager
// ---------------------------------------------------------------------------

const _listeners = new Set<FileChangeCallback>();
let _controller: AbortController | null = null;
let _running = false;

function _emit(events: FileChangeEvent[]) {
  _listeners.forEach((cb) => {
    try {
      cb(events);
    } catch {
      // ignore listener errors
    }
  });
}

async function _runLoop(signal: AbortSignal) {
  const url = workspaceApi.getWatchUrl();
  let retryDelay = 1_000;

  while (!signal.aborted) {
    try {
      const response = await fetch(url, {
        method: "GET",
        headers: buildAuthHeaders(),
        signal,
      });

      if (!response.ok || !response.body) {
        await _sleep(retryDelay);
        retryDelay = Math.min(retryDelay * 2, 30_000);
        continue;
      }

      retryDelay = 1_000; // reset on healthy connection
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (!signal.aborted) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;
          try {
            const msg = JSON.parse(raw) as {
              type: string;
              events?: FileChangeEvent[];
            };
            if (msg.type === "file_change" && msg.events) {
              _emit(msg.events);
            }
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (err) {
      if (signal.aborted) break;
      if (err instanceof DOMException && err.name === "AbortError") break;
      await _sleep(retryDelay);
      retryDelay = Math.min(retryDelay * 2, 30_000);
    }
  }

  _running = false;
}

function _ensureConnected() {
  if (_running) return;
  _running = true;
  _controller = new AbortController();
  void _runLoop(_controller.signal);
}

function _maybeDisconnect() {
  if (_listeners.size === 0 && _controller) {
    _controller.abort();
    _controller = null;
    _running = false;
  }
}

function _sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useWorkspaceWatch(
  onFileChange: FileChangeCallback,
  enabled = true,
): void {
  // Stable ref so callers don't need to memoize the callback.
  const callbackRef = useRef<FileChangeCallback>(onFileChange);
  callbackRef.current = onFileChange;

  useEffect(() => {
    if (!enabled) return;

    // Proxy listener that always calls the latest callback via ref.
    const listener: FileChangeCallback = (events) =>
      callbackRef.current(events);

    _listeners.add(listener);
    _ensureConnected();

    return () => {
      _listeners.delete(listener);
      _maybeDisconnect();
    };
  }, [enabled]);
}
