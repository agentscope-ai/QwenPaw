/**
 * pages/Chat/chatStatus.ts — backend chat status queries used by the
 * message-queue sender. Extracted from index.tsx so the logic is unit
 * testable without importing the full chat page module.
 */
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";

/**
 * One-shot chat status query. Returns the backend `status` string
 * ("running" / "idle"), or null when it cannot be determined (404, network
 * error, backend unreachable, id still a local timestamp). Callers treat
 * null as idle so the queue is never blocked forever.
 *
 * @param agentId - If provided, overrides X-Agent-Id in the status request
 *   so that switching agents does not cause a spurious status read.
 */
export async function queryChatStatus(
  chatIdForStatus: string,
  agentId?: string,
  signal?: AbortSignal,
): Promise<string | null> {
  if (!chatIdForStatus) return null;
  try {
    // Use direct fetch with the correct agent ID header to avoid
    // cross-agent status misreads when the user has switched agents.
    const headers = buildAuthHeaders();
    if (agentId) {
      headers["X-Agent-Id"] = agentId;
    }
    const res = await fetch(
      getApiUrl(`/chats/${encodeURIComponent(chatIdForStatus)}`),
      { headers, signal },
    );
    if (!res.ok) return null; // 404 / error → unknown
    const chat = await res.json();
    return typeof chat?.status === "string" ? chat.status : null;
  } catch {
    return null;
  }
}

/**
 * Wait until the backend reports the chat is no longer generating
 * (status !== "running"). Used so the next queued item is sent only after
 * the currently running task finishes — preserving order task1 → task2 → 3.
 *
 * Returns true when the chat became idle (or status is unknown / 404, which
 * we treat as idle to avoid blocking the queue forever); false if aborted.
 *
 * @param agentId - If provided, overrides X-Agent-Id in the status request
 *   so that switching agents does not cause a spurious "idle" result.
 */
export async function waitForChatIdle(
  chatIdForStatus: string,
  signal: AbortSignal,
  agentId?: string,
): Promise<boolean> {
  if (!chatIdForStatus) return true;
  while (!signal.aborted) {
    const status = await queryChatStatus(chatIdForStatus, agentId, signal);
    if (signal.aborted) return false;
    // null (unknown / 404 / unreachable, e.g. id is still a local
    // timestamp) is treated as idle so we don't block forever.
    if (status !== "running") return true;
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, 1000);
      const onAbort = () => {
        clearTimeout(timer);
        resolve();
      };
      signal.addEventListener("abort", onAbort, { once: true });
    });
  }
  return false;
}
