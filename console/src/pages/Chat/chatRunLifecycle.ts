import { request } from "../../api/request";
import { useMessageQueueStore } from "../../stores/messageQueueStore";
import type { ChatHistory } from "../../api/types/chat";
import type { IAgentScopeRuntimeWebUIRunHandle } from "@agentscope-ai/chat";

/** A disconnected SDK Run intentionally remains non-terminal. Queue locks
 * belong to the mounted Chat scope, so they must not await that Run forever. */
export async function awaitQueueAcceptance(
  execution: Promise<IAgentScopeRuntimeWebUIRunHandle>,
  signal: AbortSignal,
) {
  const run = await awaitInChatScope(execution, signal);
  const session = await awaitInChatScope(run.session, signal);
  if (!session.resolved) {
    throw session.error || new Error("SDK chat session is not ready");
  }
  return awaitInChatScope(run.accepted, signal);
}

/** Release a view's send lock when it leaves; the backend run stays attached
 * to its Chat and is reconciled through history when that Chat is reopened. */
export function awaitInChatScope<T>(
  promise: Promise<T>,
  signal: AbortSignal,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      signal.removeEventListener("abort", onAbort);
      reject(new DOMException("Chat changed", "AbortError"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
    if (signal.aborted) onAbort();
    promise.then(
      (value) => {
        signal.removeEventListener("abort", onAbort);
        if (signal.aborted) onAbort();
        else resolve(value);
      },
      (error) => {
        signal.removeEventListener("abort", onAbort);
        if (signal.aborted) onAbort();
        else reject(error);
      },
    );
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

/** Call only while holding the queue's send lock. A persisted `sending`
 * marker is not a live sender: reconcile its receipt before allowing the
 * queue to continue. Unknown receipt must remain explicitly retryable rather
 * than being silently resent (or blocking the queue forever). */
export async function recoverSendingQueueHead(
  chatId: string,
  signal: AbortSignal,
  agentId: string,
  queueKey: string,
  errorMessage: string,
): Promise<void> {
  const head = useMessageQueueStore.getState().getQueue(queueKey)[0];
  if (head?.status !== "sending") return;
  try {
    if (!(await waitForChatIdle(chatId, signal, agentId, queueKey))) return;
  } catch (error) {
    if (signal.aborted) return;
    if (error instanceof Error) errorMessage = error.message;
  }
  const store = useMessageQueueStore.getState();
  const current = store.getQueue(queueKey).find((item) => item.id === head.id);
  if (
    !signal.aborted &&
    store.getRunState(queueKey) !== "paused" &&
    current?.status === "sending"
  ) {
    store.setItemStatus(queueKey, head.id, "failed", errorMessage);
  }
}
