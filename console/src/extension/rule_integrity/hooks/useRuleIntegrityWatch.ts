/**
 * Subscribe to built-in rule integrity SSE status stream.
 */

import { useEffect, useRef } from "react";
import { buildAuthHeaders } from "@/api/authHeaders";
import { getApiUrl } from "@/api/config";
import type { ToolGuardRulesIntegrity } from "../api/client";

export type RuleIntegrityWatchEvent =
  | ToolGuardRulesIntegrity
  | { type: "connected" };

type RuleIntegrityWatchCallback = (event: RuleIntegrityWatchEvent) => void;

const _listeners = new Set<RuleIntegrityWatchCallback>();
let _controller: AbortController | null = null;
let _running = false;

function _emit(event: RuleIntegrityWatchEvent) {
  _listeners.forEach((cb) => {
    try {
      cb(event);
    } catch {
      // ignore listener errors
    }
  });
}

async function _runLoop(signal: AbortSignal) {
  const url = getApiUrl("/config/security/tool-guard/rules-integrity/watch");
  let retryDelay = 1_000;

  while (!signal.aborted) {
    try {
      const response = await fetch(url, {
        method: "GET",
        headers: buildAuthHeaders(),
        signal,
      });

      if (!response.ok || !response.body) {
        await new Promise((resolve) => setTimeout(resolve, retryDelay));
        retryDelay = Math.min(retryDelay * 2, 30_000);
        continue;
      }

      retryDelay = 1_000;
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
            const parsed = JSON.parse(raw) as RuleIntegrityWatchEvent;
            if (parsed.type === "connected") {
              _emit(parsed);
              continue;
            }
            if (parsed.type === "rule_integrity_status") {
              _emit(parsed);
            }
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (err) {
      if (signal.aborted) break;
      if (err instanceof DOMException && err.name === "AbortError") break;
      await new Promise((resolve) => setTimeout(resolve, retryDelay));
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

export function useRuleIntegrityWatch(
  onEvent: RuleIntegrityWatchCallback,
  enabled = true,
): void {
  const callbackRef = useRef(onEvent);
  callbackRef.current = onEvent;

  useEffect(() => {
    if (!enabled) return;

    const listener: RuleIntegrityWatchCallback = (event) =>
      callbackRef.current(event);

    _listeners.add(listener);
    _ensureConnected();

    return () => {
      _listeners.delete(listener);
      _maybeDisconnect();
    };
  }, [enabled]);
}
