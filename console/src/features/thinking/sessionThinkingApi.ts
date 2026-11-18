import {
  loadSessionThinkingView,
  readPendingModel,
} from "../session-settings/sessionModel";
import { request } from "@/api/request";
import type { ThinkingPreference, ThinkingView } from "./types";

import {
  readPendingThinking,
  readPendingThinkingModelKey,
} from "../session-settings/pendingThinking";
export {
  readPendingThinking,
  setPendingThinking,
  clearPendingThinking,
  migratePendingThinking,
} from "../session-settings/pendingThinking";

export function withPendingThinking(
  body: Record<string, unknown>,
  agentId: string,
  sessionId: string,
): Record<string, unknown> {
  const model = readPendingModel(agentId, sessionId);
  const modelKey = model
    ? `${model.provider_id}:${model.model}`
    : readPendingThinkingModelKey(agentId, sessionId);
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
    loadSessionThinkingView(agentId, { chatId, sessionId }),
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
