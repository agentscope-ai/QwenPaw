import { resolveBackendSessionId } from "../lib/session-id";
import {
  TASK_GRAPH_MESSAGE_ID,
  loadTaskCardMessage,
  saveTaskCardForSession,
  removeTaskCardForSession,
} from "../lib/task-card-storage";
import type { PlanSnapshot } from "../task-graph/types";

const PATCHED = Symbol("datapawSessionApiPatched");

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

function isTaskGraphMessageId(id: unknown): boolean {
  return (
    typeof id === "string" &&
    (id === TASK_GRAPH_MESSAGE_ID || id.startsWith("task_graph_"))
  );
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

function mergeTaskCardIntoSession(
  sessionId: string,
  session: { messages?: Array<Record<string, unknown>> },
): void {
  if (!onHostChatRoute()) return;
  const stored = loadStoredCardMessage(sessionId);
  if (!stored) return;
  const messages = session.messages ?? [];
  if (messages.some((m) => m.id === TASK_GRAPH_MESSAGE_ID)) return;
  session.messages = [...messages, stored];
}

export function patchHostSessionApi(): boolean {
  const api = getSessionApiInstance();

  if (!api) return false;
  if ((api as { [PATCHED]?: boolean })[PATCHED]) return true;

  const persistentMessages: Array<Record<string, unknown>> = [];

  api.setPersistentMessage = (message: Record<string, unknown>) => {
    if (isTaskGraphMessageId(message.id)) {
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
    const i = persistentMessages.findIndex((m) => m.id === id);
    if (i > -1) persistentMessages.splice(i, 1);
    if (isTaskGraphMessageId(id)) {
      const sessionId = resolveBackendSessionId();
      if (sessionId) removeTaskCardForSession(sessionId);
    }
  };

  api.clearPersistentMessages = () => {
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

      mergeTaskCardIntoSession(sessionId, session);

      if (onHostChatRoute() && persistentMessages.length > 0) {
        const messages = session.messages ?? [];
        for (const msg of persistentMessages) {
          if (!messages.some((m) => m.id === msg.id)) {
            messages.push(msg);
          }
        }
        session.messages = messages;
      }

      return session;
    };
  }

  (api as { [PATCHED]?: boolean })[PATCHED] = true;
  console.info("[datapaw] Patched host sessionApi for task card persistence");
  return true;
}
