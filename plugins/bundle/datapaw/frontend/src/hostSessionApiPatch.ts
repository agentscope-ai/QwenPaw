import type { IAgentScopeRuntimeWebUIMessage } from "@agentscope-ai/chat";

const PATCHED = Symbol("datapawSessionApiPatched");

function onHostChatRoute(): boolean {
  if (typeof window === "undefined") return false;
  const path = window.location.pathname;
  return path === "/" || path.startsWith("/chat");
}

export function getHostSessionApi(): Record<string, unknown> | null {
  const api = (
    window as { QwenPaw?: { modules?: Record<string, Record<string, unknown>> } }
  ).QwenPaw?.modules?.["Chat/sessionApi/index"]?.default;
  return (api as Record<string, unknown>) ?? null;
}

export function patchHostSessionApi(): boolean {
  const host = getHostSessionApi();
  if (!host || (host as { [PATCHED]?: boolean })[PATCHED]) {
    return !!host;
  }

  const persistentMessages: IAgentScopeRuntimeWebUIMessage[] = [];

  host.setPersistentMessage = (message: IAgentScopeRuntimeWebUIMessage) => {
    const idx = persistentMessages.findIndex((m) => m.id === message.id);
    if (idx > -1) persistentMessages[idx] = message;
    else persistentMessages.push(message);
  };

  host.removePersistentMessage = (id: string) => {
    const i = persistentMessages.findIndex((m) => m.id === id);
    if (i > -1) persistentMessages.splice(i, 1);
  };

  host.clearPersistentMessages = () => {
    persistentMessages.length = 0;
  };

  host.getPersistentMessages = () => [...persistentMessages];

  const origGetSession = host.getSession as (
    sessionId: string,
  ) => Promise<{ messages?: IAgentScopeRuntimeWebUIMessage[] }>;

  if (typeof origGetSession === "function") {
    host.getSession = async (sessionId: string) => {
      const session = await origGetSession.call(host, sessionId);
      if (onHostChatRoute() && persistentMessages.length > 0) {
        session.messages = [
          ...(session.messages ?? []),
          ...persistentMessages,
        ];
      }
      return session;
    };
  }

  (host as { [PATCHED]?: boolean })[PATCHED] = true;
  return true;
}
