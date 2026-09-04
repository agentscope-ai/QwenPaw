import { request } from "../../api/request";
import { useMessageQueueStore } from "../../stores/messageQueueStore";
import type { ChatHistory } from "../../api/types/chat";

/** Release a view's send lock when it leaves; the backend run stays attached
 * to its Chat and is reconciled through history when that Chat is reopened. */
export function awaitInChatScope<T>(
  promise: Promise<T>,
  signal: AbortSignal,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const onAbort = () =>
      reject(new DOMException("Chat changed", "AbortError"));
    signal.addEventListener("abort", onAbort, { once: true });
    if (signal.aborted) onAbort();
    promise.then(resolve, reject).finally(() => {
      signal.removeEventListener("abort", onAbort);
    });
  });
}

function waitForPoll(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    };
    const timer = setTimeout(finish, 1000);
    signal.addEventListener("abort", finish, { once: true });
    if (signal.aborted) finish();
  });
}

/** Only an explicit backend idle state permits a subsequent queued turn. */
export async function waitForChatIdle(
  chatId: string,
  signal: AbortSignal,
  agentId: string,
  queueKey = chatId,
): Promise<boolean> {
  while (!signal.aborted) {
    try {
      const chat = await request<ChatHistory>(
        `/chats/${encodeURIComponent(chatId)}`,
        { headers: { "X-Agent-Id": agentId }, signal },
      );
      if (signal.aborted) return false;
      useMessageQueueStore
        .getState()
        .reconcileHistory(queueKey, agentId, chat.messages || []);
      if (chat.status === "idle") return true;
      if (chat.status !== "running") {
        throw new Error("Unable to confirm chat status");
      }
    } catch (error) {
      if (signal.aborted) return false;
      throw error;
    }
    await waitForPoll(signal);
  }
  return false;
}
