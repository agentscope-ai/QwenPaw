import { resolveBackendSessionId } from "../lib/session-id";
import {
  TASK_GRAPH_MESSAGE_ID,
  loadTaskCardMessage,
  saveTaskCardForSession,
  removeTaskCardForSession,
} from "../lib/task-card-storage";
import type { PlanSnapshot } from "../task-graph/types";
import { isTaskGraphMessageId } from "../lib/pin-task-card";

const PATCHED = Symbol("datapawSessionApiPatched");

let onSessionApiPatched: (() => void) | null = null;

export function setSessionApiPatchedListener(listener: (() => void) | null): void {
  onSessionApiPatched = listener;
}

function logTaskGraphDebug(
  event: string,
  payload?: Record<string, unknown>,
): void {
  void event;
  void payload;
}

function onHostChatRoute(): boolean {
  if (typeof window === "undefined") return false;
  const path = window.location.pathname;
  return path === "/" || path.startsWith("/chat");
}

function getSessionApiInstance(): Record<string, unknown> | null {
  const mod = (
    window as { QwenPaw?: { modules?: Record<string, Record<string, unknown>> } }
  ).QwenPaw?.modules?.["Chat/sessionApi/index"];
  const api = mod?.default;
  return (api as Record<string, unknown>) ?? null;
}

function resolveStorageSessionIds(sessionId: string): string[] {
  const ids = new Set<string>([sessionId]);
  const backendId = resolveBackendSessionId(sessionId);
  if (backendId) ids.add(backendId);
  const current = (window as Window & { currentSessionId?: string })
    .currentSessionId;
  if (current) ids.add(current);
  if (backendId !== sessionId) ids.add(sessionId);
  return [...ids];
}

function loadStoredCardMessage(
  sessionId: string,
): Record<string, unknown> | null {
  for (const id of resolveStorageSessionIds(sessionId)) {
    const msg = loadTaskCardMessage(id);
    if (msg) return msg as Record<string, unknown>;
  }
  return null;
}

function isStandaloneTaskGraphMessage(
  message: Record<string, unknown>,
): boolean {
  const cards = message.cards as Array<{ code?: string }> | undefined;
  return Boolean(
    message.id &&
      cards?.length === 1 &&
      cards[0]?.code === "task_graph" &&
      (String(message.id).startsWith("task_graph_") ||
        message.id === TASK_GRAPH_MESSAGE_ID),
  );
}

function getTaskGraphAnchorMessageId(
  message: Record<string, unknown>,
): string | null {
  const cards = message.cards as
    | Array<{ code?: string; data?: { plan?: { anchor_message_id?: string } } }>
    | undefined;
  const taskGraphCard = cards?.find((card) => card.code === "task_graph");
  const anchorMessageId = taskGraphCard?.data?.plan?.anchor_message_id;
  return typeof anchorMessageId === "string" && anchorMessageId
    ? anchorMessageId
    : null;
}

function getTaskGraphPlanId(message: Record<string, unknown>): string | null {
  const cards = message.cards as
    | Array<{ code?: string; data?: { plan?: { id?: string } } }>
    | undefined;
  const taskGraphCard = cards?.find((card) => card.code === "task_graph");
  const planId = taskGraphCard?.data?.plan?.id;
  return typeof planId === "string" && planId ? planId : null;
}

function outputMatchesPlan(
  item: { metadata?: { graph_id?: string } | null; graph_id?: string },
  planId?: string | null,
): boolean {
  if (!planId) return false;
  return item.metadata?.graph_id === planId || item.graph_id === planId;
}

function findAssistantResponseIndex(
  messages: Array<Record<string, unknown>>,
  anchorMessageId?: string | null,
  planId?: string | null,
): number {
  void anchorMessageId;
  if (!planId) return -1;
  return messages.findIndex((message) => {
    const cards = message.cards as
      | Array<{
          code?: string;
          data?: {
            output?: Array<{
              metadata?: { graph_id?: string } | null;
              graph_id?: string;
            }>;
          };
        }>
      | undefined;

    return (
      message.role === "assistant" &&
      cards?.some((card) =>
        card.code === "AgentScopeRuntimeResponseCard"
          ? card.data?.output?.some((item) =>
              outputMatchesPlan(item, planId),
            )
          : false,
      )
    );
  });
}

function mergePersistentMessages(
  messages: Array<Record<string, unknown>>,
  persistentMessages: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  const next = messages.filter(
    (message) => !isStandaloneTaskGraphMessage(message),
  );
  const seenIds = new Set<string>();
  const candidates = [...messages, ...persistentMessages].filter(
    (message) => {
      if (!isStandaloneTaskGraphMessage(message)) return false;
      const id = String(message.id);
      if (seenIds.has(id)) return false;
      seenIds.add(id);
      return true;
    },
  );

  for (const message of candidates) {
    const anchorMessageId = getTaskGraphAnchorMessageId(message);
    const planId = getTaskGraphPlanId(message);
    const targetIndex = findAssistantResponseIndex(next, anchorMessageId, planId);
    logTaskGraphDebug("session-merge-candidate", {
      messageId: message.id ?? null,
      anchorMessageId,
      planId,
      targetIndex,
      messageCount: messages.length,
      persistentCount: persistentMessages.length,
    });
    if (targetIndex < 0) {
      next.push(message);
      logTaskGraphDebug("session-merge-append-standalone", {
        messageId: message.id ?? null,
        anchorMessageId,
        planId,
      });
      continue;
    }

    const target = next[targetIndex];
    const targetCards = Array.isArray(target.cards) ? [...target.cards] : [];
    const sourceCards = Array.isArray(message.cards) ? message.cards : [];
    if (targetCards.some((card) => card.code === "task_graph")) {
      logTaskGraphDebug("session-merge-skip-existing-card", {
        messageId: message.id ?? null,
        targetIndex,
        targetMessageId: target.id ?? null,
      });
      continue;
    }
    next[targetIndex] = {
      ...target,
      cards: [...targetCards, ...sourceCards],
    };
    logTaskGraphDebug("session-merge-attached", {
      messageId: message.id ?? null,
      anchorMessageId,
      planId,
      targetIndex,
      targetMessageId: target.id ?? null,
    });
  }

  return next;
}

function mergeTaskCardIntoSession(
  sessionId: string,
  session: { messages?: Array<Record<string, unknown>> },
): void {
  if (!onHostChatRoute()) return;
  const stored = loadStoredCardMessage(sessionId);
  logTaskGraphDebug("merge-stored-card", {
    sessionId,
    hasStored: Boolean(stored),
    messageCount: session.messages?.length ?? 0,
  });
  if (!stored) return;
  const messages = session.messages ?? [];
  session.messages = mergePersistentMessages(messages, [stored]);
}

function sortTaskCardsLast(
  messages: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  const regular: Array<Record<string, unknown>> = [];
  const taskCards: Array<Record<string, unknown>> = [];
  for (const msg of messages) {
    if (isTaskGraphMessageId(msg.id)) taskCards.push(msg);
    else regular.push(msg);
  }
  return [...regular, ...taskCards];
}

export function patchHostSessionApi(): boolean {
  const api = getSessionApiInstance();

  if (!api) {
    logTaskGraphDebug("patch-skip", { reason: "missing-api" });
    return false;
  }
  if ((api as { [PATCHED]?: boolean })[PATCHED]) {
    logTaskGraphDebug("patch-skip", { reason: "already-patched" });
    return true;
  }

  const persistentMessages: Array<Record<string, unknown>> = [];

  api.setPersistentMessage = (message: Record<string, unknown>) => {
    if (isTaskGraphMessageId(message.id)) {
      logTaskGraphDebug("set-persistent-task-card", {
        messageId: message.id,
        planId: getTaskGraphPlanId(message),
        anchorMessageId: getTaskGraphAnchorMessageId(message),
      });
      for (let i = persistentMessages.length - 1; i >= 0; i -= 1) {
        if (isTaskGraphMessageId(persistentMessages[i].id)) {
          persistentMessages.splice(i, 1);
        }
      }

      const cards = message.cards as
        | Array<{ data?: { plan?: PlanSnapshot } }>
        | undefined;
      const card = cards?.[0];
      const plan = card?.data?.plan;
      const sessionId = resolveBackendSessionId();
      if (plan && sessionId) {
        saveTaskCardForSession(sessionId, plan);
      }
    }

    const idx = persistentMessages.findIndex((m) => m.id === message.id);
    if (idx > -1) persistentMessages[idx] = message;
    else persistentMessages.push(message);
  };

  api.removePersistentMessage = (id: string) => {
    if (isTaskGraphMessageId(id)) {
      logTaskGraphDebug("remove-persistent-task-card", { messageId: id });
    }
    const i = persistentMessages.findIndex((m) => m.id === id);
    if (i > -1) persistentMessages.splice(i, 1);
    if (isTaskGraphMessageId(id)) {
      const sessionId = resolveBackendSessionId();
      if (sessionId) removeTaskCardForSession(sessionId);
    }
  };

  api.clearPersistentMessages = () => {
    logTaskGraphDebug("clear-persistent-messages", {
      count: persistentMessages.length,
    });
    persistentMessages.length = 0;
  };

  api.getPersistentMessages = () => [...persistentMessages];

  const origGetSession = api.getSession;
  if (typeof origGetSession === "function") {
    const boundGetSession = origGetSession.bind(api) as (
      sessionId: string,
    ) => Promise<{ messages?: Array<Record<string, unknown>> }>;
    api.getSession = async (sessionId: string) => {
      const session = await boundGetSession(sessionId);
      logTaskGraphDebug("get-session", {
        sessionId,
        messageCount: session.messages?.length ?? 0,
        persistentCount: persistentMessages.length,
      });

      mergeTaskCardIntoSession(sessionId, session);

      if (onHostChatRoute() && persistentMessages.length > 0) {
        const messages = session.messages ?? [];
        const merged = mergePersistentMessages(messages, persistentMessages);
        session.messages = sortTaskCardsLast(merged);
        logTaskGraphDebug("get-session-merged-persistent", {
          sessionId,
          messageCount: session.messages.length,
          persistentCount: persistentMessages.length,
        });
      } else if (session.messages?.length) {
        session.messages = sortTaskCardsLast(session.messages);
      }

      return session;
    };
  }

  (api as { [PATCHED]?: boolean })[PATCHED] = true;
  logTaskGraphDebug("patch-installed");
  onSessionApiPatched?.();
  return true;
}
