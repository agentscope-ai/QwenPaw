import type { ThinkingPreference } from "../thinking/types";

const key = (agentId: string, sessionId: string) =>
  `qwenpaw-thinking:${agentId}:${sessionId}`;
export function readPendingThinking(
  agentId: string,
  sessionId: string,
  modelKey = "",
): ThinkingPreference | null {
  const raw = sessionStorage.getItem(key(agentId, sessionId));
  if (!raw) return null;
  try {
    return JSON.parse(raw)[modelKey] ?? null;
  } catch {
    return null;
  }
}
export function setPendingThinking(
  agentId: string,
  sessionId: string,
  value: ThinkingPreference | null,
  modelKey = "",
) {
  const storageKey = key(agentId, sessionId);
  sessionStorage.setItem(`${storageKey}:active`, modelKey);
  const settings = JSON.parse(sessionStorage.getItem(storageKey) || "{}");
  if (!value || value.level === "inherit") delete settings[modelKey];
  else settings[modelKey] = value;
  sessionStorage.setItem(storageKey, JSON.stringify(settings));
}
export function clearPendingThinking(agentId: string, sessionId: string) {
  sessionStorage.removeItem(key(agentId, sessionId));
  sessionStorage.removeItem(`${key(agentId, sessionId)}:active`);
}
export function migratePendingThinking(
  agentId: string,
  from: string,
  to: string,
) {
  if (from === to) return;
  const active = sessionStorage.getItem(`${key(agentId, from)}:active`);
  if (active) {
    sessionStorage.setItem(`${key(agentId, to)}:active`, active);
    sessionStorage.removeItem(`${key(agentId, from)}:active`);
  }
  const raw = sessionStorage.getItem(key(agentId, from));
  if (raw) {
    sessionStorage.setItem(key(agentId, to), raw);
    sessionStorage.removeItem(key(agentId, from));
  }
}

export function readPendingThinkingModelKey(
  agentId: string,
  sessionId: string,
) {
  return sessionStorage.getItem(`${key(agentId, sessionId)}:active`) || "";
}
