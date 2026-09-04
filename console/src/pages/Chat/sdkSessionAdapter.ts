import type { IAgentScopeRuntimeWebUISessionAPI } from "@agentscope-ai/chat";

/** One adapter per Agent ownership epoch. The SDK remains the only history
 * loader; the host observes that load instead of racing it with another fetch.
 * Sender/queue guards read this synchronously, including before React commits. */
export function createSdkSessionAdapter(
  source: IAgentScopeRuntimeWebUISessionAPI,
) {
  const ready = new Set<string>();
  const pending = new Map<string, symbol>();
  const listeners = new Set<() => void>();
  let revision = 0;
  const publish = () => {
    revision++;
    listeners.forEach((listener) => listener());
  };
  const sessionIds = (
    requestedId: string,
    session?: Awaited<ReturnType<typeof source.getSession>>,
  ) => {
    const ids = new Set<string>([requestedId]);
    if (session?.id) ids.add(session.id);
    const realId = (session as { realId?: unknown } | undefined)?.realId;
    if (typeof realId === "string" && realId) ids.add(realId);
    return ids;
  };
  const api: IAgentScopeRuntimeWebUISessionAPI = {
    getSessionList: () => source.getSessionList(),
    updateSession: (session) => source.updateSession(session),
    removeSession: async (session) => {
      const result = await source.removeSession(session);
      if (session.id) {
        ready.delete(session.id);
        pending.delete(session.id);
        publish();
      }
      return result;
    },
    getSession: async (id) => {
      const token = Symbol(id);
      pending.set(id, token);
      ready.delete(id);
      publish();
      try {
        const session = await source.getSession(id);
        if (pending.get(id) === token && session) {
          // A restored route can be an opaque runtime session_id while the
          // canonical route is the Chat UUID returned as realId. One SDK load
          // makes both aliases safe to use; otherwise URL canonicalization
          // leaves the sender and its queue permanently disabled.
          for (const sessionId of sessionIds(id, session)) {
            ready.add(sessionId);
          }
        }
        return session;
      } finally {
        if (pending.get(id) === token) {
          pending.delete(id);
          publish();
        }
      }
    },
    createSession: async (draft) => {
      const result = await source.createSession(draft);
      // CoPaw returns the explicit SDK creation result; the SDK seeds this
      // empty session itself and intentionally skips a redundant history load.
      if (!Array.isArray(result)) ready.add(result.session.id);
      publish();
      return result;
    },
  };
  return {
    api,
    isReady: (id?: string | null) =>
      !id || id === "new" || (ready.has(id) && !pending.has(id)),
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    getSnapshot: () => revision,
  };
}
