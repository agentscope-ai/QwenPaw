import {
  modelViewUrl,
  readPendingModel,
} from "../session-settings/sessionModel";
import { request } from "@/api/request";
import type { ThinkingPreference, ThinkingView } from "./types";

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
export function withPendingThinking(
  body: Record<string, unknown>,
  agentId: string,
  sessionId: string,
): Record<string, unknown> {
  const model = readPendingModel(agentId, sessionId);
  const modelKey = model
    ? `${model.provider_id}:${model.model}`
    : sessionStorage.getItem(`${key(agentId, sessionId)}:active`) || "";
  const value = readPendingThinking(agentId, sessionId, modelKey);
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
  get: (agentId: string, chatId?: string | null, sessionId = "new") =>
    request<ThinkingView>(modelViewUrl(agentId, { chatId, sessionId }), {
      headers: { "X-Agent-Id": agentId },
    }),
  set: (
    agentId: string,
    chatId: string,
    value: ThinkingPreference,
    modelKey?: string,
  ) =>
    request<ThinkingView>(
      `/chats/${encodeURIComponent(chatId)}/thinking${
        modelKey ? `?model_key=${encodeURIComponent(modelKey)}` : ""
      }`,
      {
        method: "PUT",
        headers: { "X-Agent-Id": agentId },
        body: JSON.stringify(value),
      },
    ),
};
