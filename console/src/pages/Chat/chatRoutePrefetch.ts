import { chatApi } from "../../api/modules/chat";
import type { ChatHistory } from "../../api/types";

interface HistoryPrefetch {
  agentId: string;
  promise: Promise<ChatHistory>;
}

const historyPrefetches = new Map<string, HistoryPrefetch>();

/** Start the cold-route history request before the Chat SDK is available. */
export function prefetchChatHistory(
  chatId: string,
  agentId: string,
  signal: AbortSignal,
): Promise<ChatHistory> {
  const existing = historyPrefetches.get(chatId);
  if (existing?.agentId === agentId) return existing.promise;

  const promise = chatApi.getChat(chatId, {
    signal,
    agentId,
    include_app_owned: false,
  });
  const entry = { agentId, promise };
  historyPrefetches.set(chatId, entry);
  const discard = () => {
    if (historyPrefetches.get(chatId) === entry) {
      historyPrefetches.delete(chatId);
    }
  };
  signal.addEventListener("abort", discard, { once: true });
  void promise.catch(discard);
  return promise;
}

/** Consume a matching cold-route request once; ordinary loads return null. */
export function takeChatHistoryPrefetch(
  chatId: string,
  agentId: string,
): Promise<ChatHistory> | null {
  const entry = historyPrefetches.get(chatId);
  if (!entry || entry.agentId !== agentId) return null;
  historyPrefetches.delete(chatId);
  return entry.promise;
}
