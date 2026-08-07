/**
 * pages/Chat/chatStatus.ts — backend chat status queries used by the
 * message-queue sender. Extracted from index.tsx so the logic is unit
 * testable without importing the full chat page module.
 */
import { getApiUrl } from "../../api/config";
import { buildAuthHeaders } from "../../api/authHeaders";

/**
 * Result of a backend status probe. Distinguishes a *confirmed* state from
 * an *undetermined* one:
 *
 * - "running" — backend confirms the chat is still generating.
 * - "idle"    — backend confirms nothing is running for the chat. A 404 is
 *               also "idle": the chat does not exist, so no turn can be
 *               running for it.
 * - "unknown" — the status could not be determined (network failure, a
 *               non-404 HTTP error, or a response body without a usable
 *               status). The chat may or may not be running.
 */
export type ChatStatus = "running" | "idle" | "unknown";

/**
 * One-shot chat status probe.
 *
 * @param agentId - If provided, overrides X-Agent-Id in the status request
 *   so that switching agents does not cause a spurious status read.
 */
export async function queryChatStatus(
  chatIdForStatus: string,
  agentId?: string,
  signal?: AbortSignal,
): Promise<ChatStatus> {
  if (!chatIdForStatus) return "unknown";
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
    // A 404 means the chat does not exist on the backend, so it cannot be
    // running — treat it as confirmed idle (this also lets a desynced chat
    // id recover: the next send will create the chat).
    if (res.status === 404) return "idle";
    if (!res.ok) return "unknown"; // e.g. 5xx/4xx other than 404
    const chat = await res.json();
    const status = typeof chat?.status === "string" ? chat.status : null;
    if (status === "running") return "running";
    if (status == null) return "unknown"; // no usable status → undetermined
    return "idle";
  } catch {
    // Network failure / unreachable backend. The chat may still be running
    // (e.g. the SSE connection dropped), so this is "unknown", not "idle".
    return "unknown";
  }
}

/**
 * Watchdog decision for a stuck `chatLoading` flag: may we clear the SDK
 * loading state and send the next queued message?
 *
 * Only a *confirmed* non-running backend state permits that. An "unknown"
 * status (transient network failure, backend unreachable) must NOT clear
 * loading — doing so could submit the next turn while the previous one is
 * still running on the backend (out-of-order sends).
 */
export function shouldResetStuckLoading(status: ChatStatus): boolean {
  return status === "idle";
}

/**
 * Wait until the backend reports the chat is no longer generating
 * (status === "idle"). Used so the next queued item is sent only after the
 * currently running task finishes — preserving order task1 → task2 → 3.
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
    // "unknown" / "idle" both mean "not running": stop waiting. This keeps
    // the pre-existing behavior of not blocking the queue forever on a
    // failed probe (the subsequent POST attempt surfaces the failure as a
    // retryable queue item instead of wedging the queue).
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
