import { request } from "@/api/request";
import type { ThinkingPreference, ThinkingView } from "./types";

const key = (agentId: string, sessionId: string) =>
  `qwenpaw-thinking:${agentId}:${sessionId}`;
export function readPendingThinking(
  agentId: string,
  sessionId: string,
): ThinkingPreference | null {
  const raw = sessionStorage.getItem(key(agentId, sessionId));
  if (!raw) return null;
  try {
    return JSON.parse(raw) as ThinkingPreference;
  } catch {
    return null;
  }
}
export function setPendingThinking(
  agentId: string,
  sessionId: string,
  value: ThinkingPreference | null,
) {
  if (!value || value.level === "inherit")
    sessionStorage.removeItem(key(agentId, sessionId));
  else sessionStorage.setItem(key(agentId, sessionId), JSON.stringify(value));
}
export function migratePendingThinking(
  agentId: string,
  from: string,
  to: string,
) {
  if (from === to) return;
  const value = readPendingThinking(agentId, from);
  if (value) {
    setPendingThinking(agentId, to, value);
    setPendingThinking(agentId, from, null);
  }
}
export function withPendingThinking(
  body: Record<string, unknown>,
  agentId: string,
  sessionId: string,
): Record<string, unknown> {
  const value = readPendingThinking(agentId, sessionId);
  if (!value) return body;
  return {
    ...body,
    request_context: {
      ...((body.request_context as Record<string, unknown>) || {}),
      session_thinking: value,
    },
  };
}
export const sessionThinkingApi = {
  get: (agentId: string, chatId?: string | null) =>
    request<ThinkingView>(
      chatId
        ? `/chats/${encodeURIComponent(chatId)}/thinking`
        : "/chats/thinking-default",
      { headers: { "X-Agent-Id": agentId } },
    ),
  set: (agentId: string, chatId: string, value: ThinkingPreference) =>
    request<ThinkingView>(`/chats/${encodeURIComponent(chatId)}/thinking`, {
      method: "PUT",
      headers: { "X-Agent-Id": agentId },
      body: JSON.stringify(value),
    }),
};
