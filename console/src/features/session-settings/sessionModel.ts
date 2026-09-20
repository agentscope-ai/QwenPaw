import { request } from "@/api/request";
import type { ActiveModelsInfo } from "@/api/types";
import type { ThinkingView } from "../thinking/types";

export interface SessionModelScope {
  sessionId: string;
  chatId?: string | null;
}
export interface SessionModel {
  provider_id: string;
  model: string;
}
const key = (agent: string, session: string) =>
  `qwenpaw-session-model:${agent}:${session}`;
export function readPendingModel(
  agent: string,
  session: string,
): SessionModel | null {
  const raw = sessionStorage.getItem(key(agent, session));
  return raw ? JSON.parse(raw) : null;
}
export function clearPendingModel(agent: string, session: string) {
  sessionStorage.removeItem(key(agent, session));
}
export function migratePendingModel(agent: string, from: string, to: string) {
  if (from === to) return;
  const raw = sessionStorage.getItem(key(agent, from));
  if (raw) {
    sessionStorage.setItem(key(agent, to), raw);
    sessionStorage.removeItem(key(agent, from));
  }
}
export function withPendingModel(
  body: Record<string, unknown>,
  agent: string,
  session: string,
) {
  const model = readPendingModel(agent, session);
  if (!model) return body;
  return {
    ...body,
    request_context: {
      ...((body.request_context as Record<string, unknown>) || {}),
      session_model: model,
    },
  };
}
export function modelViewUrl(agent: string, scope: SessionModelScope) {
  if (scope.chatId)
    return `/chats/${encodeURIComponent(scope.chatId)}/thinking`;
  const model = readPendingModel(agent, scope.sessionId);
  return `/chats/thinking-default${
    model ? `?${new URLSearchParams({ ...model })}` : ""
  }`;
}
function activeModels(view: ThinkingView): ActiveModelsInfo {
  return {
    active_llm:
      view.provider_id && view.model
        ? {
            provider_id: view.provider_id,
            model: view.model,
          }
        : null,
    effective_max_input_length: view.effective_max_input_length,
  };
}
export async function loadSessionModel(
  agent: string,
  scope: SessionModelScope,
) {
  return activeModels(
    await request<ThinkingView>(modelViewUrl(agent, scope), {
      headers: { "X-Agent-Id": agent },
    }),
  );
}
export async function saveSessionModel(
  agent: string,
  scope: SessionModelScope,
  model: SessionModel,
) {
  if (!scope.chatId) {
    const view = await request<ThinkingView>(
      `/chats/thinking-default?${new URLSearchParams({ ...model })}`,
      {
        headers: { "X-Agent-Id": agent },
      },
    );
    sessionStorage.setItem(key(agent, scope.sessionId), JSON.stringify(model));
    return activeModels(view);
  }
  return activeModels(
    await request<ThinkingView>(
      `/chats/${encodeURIComponent(scope.chatId)}/model`,
      {
        method: "PUT",
        headers: { "X-Agent-Id": agent },
        body: JSON.stringify(model),
      },
    ),
  );
}

export async function resetSessionModel(
  agent: string,
  scope: SessionModelScope,
) {
  if (!scope.chatId) {
    sessionStorage.removeItem(key(agent, scope.sessionId));
    return loadSessionModel(agent, scope);
  }
  return activeModels(
    await request<ThinkingView>(
      `/chats/${encodeURIComponent(scope.chatId)}/model`,
      {
        method: "PUT",
        headers: { "X-Agent-Id": agent },
        body: "null",
      },
    ),
  );
}
