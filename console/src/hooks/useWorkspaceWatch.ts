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
import type { WorkspaceRoot } from "../features/files-workspace/types";

export interface FileChangeEvent {
  change: "added" | "modified" | "deleted";
  path: string;
}

type FileChangeCallback = (events: FileChangeEvent[]) => void;

// ---------------------------------------------------------------------------
// Singleton SSE manager
// ---------------------------------------------------------------------------

const _listeners = new Map<string, Set<FileChangeCallback>>();
const _controllers = new Map<string, AbortController>();
const _running = new Set<string>();

function _emit(key: string, events: FileChangeEvent[]) {
  _listeners.get(key)?.forEach((cb) => {
    try {
      cb(events);
    } catch {
      // ignore listener errors
    }
  });
}

async function _runLoop(
  key: string,
  chatId: string | undefined,
  projectDirOverride: string | undefined,
  root: WorkspaceRoot,
  signal: AbortSignal,
) {
  const url = workspaceApi.getWatchUrl(root);
  let retryDelay = 1_000;

  while (!signal.aborted) {
    try {
      const response = await fetch(url, {
        method: "GET",
        headers: {
          ...buildAuthHeaders(),
          ...(chatId ? { "X-Chat-Id": chatId } : {}),
          ...(!chatId && projectDirOverride
            ? { "X-Session-Project-Dir": projectDirOverride }
            : {}),
        },
        signal,
      });

      if (!response.ok || !response.body) {
        await _sleep(retryDelay, signal);
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
              _emit(key, msg.events);
            }
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (err) {
      if (signal.aborted) break;
      if (err instanceof DOMException && err.name === "AbortError") break;
      await _sleep(retryDelay, signal);
      retryDelay = Math.min(retryDelay * 2, 30_000);
    }
  }

  _running.delete(key);
}

function _ensureConnected(
  key: string,
  chatId: string | undefined,
  projectDirOverride: string | undefined,
  root: WorkspaceRoot,
) {
  if (_running.has(key)) return;
  _running.add(key);
  const controller = new AbortController();
  _controllers.set(key, controller);
  void _runLoop(key, chatId, projectDirOverride, root, controller.signal);
}

function _maybeDisconnect(key: string) {
  if ((_listeners.get(key)?.size ?? 0) === 0) {
    _listeners.delete(key);
    _controllers.get(key)?.abort();
    _controllers.delete(key);
    _running.delete(key);
  }
}

function _sleep(ms: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.resolve();
  return new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timeout);
      signal.removeEventListener("abort", finish);
      resolve();
    };
    const timeout = setTimeout(finish, ms);
    signal.addEventListener("abort", finish, { once: true });
  });
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useWorkspaceWatch(
  onFileChange: FileChangeCallback,
  enabled = true,
  chatId?: string,
  root: WorkspaceRoot = "project",
  projectDirOverride?: string,
): void {
  // Stable ref so callers don't need to memoize the callback.
  const callbackRef = useRef<FileChangeCallback>(onFileChange);
  callbackRef.current = onFileChange;

  useEffect(() => {
    if (!enabled) return;

    // Proxy listener that always calls the latest callback via ref.
    const listener: FileChangeCallback = (events) =>
      callbackRef.current(events);

    const key = `${chatId ?? ""}:${projectDirOverride ?? ""}:${root}`;
    const listeners = _listeners.get(key) ?? new Set<FileChangeCallback>();
    listeners.add(listener);
    _listeners.set(key, listeners);
    _ensureConnected(key, chatId, projectDirOverride, root);

    return () => {
      listeners.delete(listener);
      _maybeDisconnect(key);
    };
  }, [chatId, enabled, projectDirOverride, root]);
}
