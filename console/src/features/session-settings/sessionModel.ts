import { clearPendingThinking } from "./pendingThinking";
import { request } from "@/api/request";
import type { ActiveModelsInfo } from "@/api/types";
import type { DecisionSettings, ThinkingView } from "../thinking/types";

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
type PendingModelSettings = Partial<SessionModel> & {
  decision_enabled?: boolean;
};
function readPendingSettings(
  agent: string,
  session: string,
): PendingModelSettings {
  return JSON.parse(sessionStorage.getItem(key(agent, session)) || "{}");
}
function updatePendingSettings(
  agent: string,
  session: string,
  changes: PendingModelSettings,
) {
  sessionStorage.setItem(
    key(agent, session),
    JSON.stringify({ ...readPendingSettings(agent, session), ...changes }),
  );
}
export function readPendingModel(
  agent: string,
  session: string,
): SessionModel | null {
  const { provider_id, model } = readPendingSettings(agent, session);
  return provider_id && model ? { provider_id, model } : null;
}
export function clearPendingModel(agent: string, session: string) {
  sessionStorage.removeItem(key(agent, session));
}
function clearPendingChatModel(agent: string, session: string) {
  updatePendingSettings(agent, session, {
    provider_id: undefined,
    model: undefined,
  });
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
  const { decision_enabled } = readPendingSettings(agent, session);
  if (!model && decision_enabled === undefined) return body;
  return {
    ...body,
    request_context: {
      ...((body.request_context as Record<string, unknown>) || {}),
      ...(model ? { session_model: model } : {}),
      ...(decision_enabled !== undefined
        ? { session_decision_enabled: decision_enabled }
        : {}),
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
export async function loadSessionThinkingView(
  agent: string,
  scope: SessionModelScope,
): Promise<ThinkingView> {
  const pending = readPendingModel(agent, scope.sessionId);
  const view = await request<ThinkingView>(modelViewUrl(agent, scope), {
    headers: { "X-Agent-Id": agent },
  });
  const decision = readPendingSettings(agent, scope.sessionId).decision_enabled;
  if (view.decision && decision !== undefined) {
    if (scope.chatId && view.decision.override === decision)
      updatePendingSettings(agent, scope.sessionId, {
        decision_enabled: undefined,
      });
    else
      view.decision = {
        ...view.decision,
        override: decision,
        enabled: view.decision.configured && decision,
      };
  }
  if (!scope.chatId || !pending) return view;
  // A newly allocated chat can be read before the first turn saves its model.
  // Keep the submitted choice until the server acknowledges that exact model.
  if (
    view.model_source === "session" &&
    view.provider_id === pending.provider_id &&
    view.model === pending.model
  ) {
    const current = readPendingModel(agent, scope.sessionId);
    if (
      current?.model === pending.model &&
      current.provider_id === pending.provider_id
    ) {
      clearPendingChatModel(agent, scope.sessionId);
    }
    return view;
  }
  const preview = await request<ThinkingView>(
    `/chats/thinking-default?${new URLSearchParams({ ...pending })}`,
    { headers: { "X-Agent-Id": agent } },
  );
  return { ...preview, model_source: "session", decision: view.decision };
}

export async function loadSessionModel(
  agent: string,
  scope: SessionModelScope,
) {
  return activeModels(await loadSessionThinkingView(agent, scope));
}
export async function saveSessionModel(
  agent: string,
  scope: SessionModelScope,
  model: SessionModel | null,
) {
  if (!scope.chatId) {
    if (!model) {
      clearPendingChatModel(agent, scope.sessionId);
      return loadSessionModel(agent, scope);
    }
    const view = await request<ThinkingView>(
      `/chats/thinking-default?${new URLSearchParams({ ...model })}`,
      {
        headers: { "X-Agent-Id": agent },
      },
    );
    updatePendingSettings(agent, scope.sessionId, model);
    return activeModels(view);
  }
  const view = await request<ThinkingView>(
    `/chats/${encodeURIComponent(scope.chatId)}/model`,
    {
      method: "PUT",
      headers: { "X-Agent-Id": agent },
      body: JSON.stringify(model),
    },
  );
  clearPendingChatModel(agent, scope.sessionId);
  return activeModels(view);
}

export async function resetSessionModel(
  agent: string,
  scope: SessionModelScope,
) {
  const models = await saveSessionModel(agent, scope, null);
  clearPendingThinking(agent, scope.sessionId);
  return models;
}

export async function saveDecisionSettings(
  agent: string,
  scope: SessionModelScope,
  settings: DecisionSettings,
) {
  if (!scope.chatId) {
    updatePendingSettings(agent, scope.sessionId, {
      decision_enabled: settings.enabled,
    });
    return settings;
  }
  const saved = await request<DecisionSettings>(
    `/chats/${encodeURIComponent(scope.chatId)}/decision-settings`,
    {
      method: "PUT",
      headers: { "X-Agent-Id": agent },
      body: JSON.stringify(settings.enabled),
    },
  );
  updatePendingSettings(agent, scope.sessionId, {
    decision_enabled: undefined,
  });
  return saved;
}
