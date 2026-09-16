export interface ChatResumeSyncState {
  backendStatus?: string;
  backendMessageCount: number;
  currentMessageCount: number;
  frontendRunning: boolean;
}

export interface ChatResumeTriggerState {
  wasRunningWhenHidden: boolean;
  frontendRunning: boolean;
}

export type ChatResumeAction = "none" | "replace_history" | "reconnect";

/**
 * Resume synchronization exists to reconnect work that may have progressed
 * while the page was hidden. An already-idle chat has nothing to reconnect.
 */
export function shouldSyncChatAfterResume({
  wasRunningWhenHidden,
  frontendRunning,
}: ChatResumeTriggerState): boolean {
  return wasRunningWhenHidden || frontendRunning;
}

/**
 * Decide whether resuming the browser requires rebuilding the chat runtime.
 * An idle backend alone is not a change: completed chats normally stay idle.
 */
export function decideChatResumeAction({
  backendStatus,
  backendMessageCount,
  currentMessageCount,
  frontendRunning,
}: ChatResumeSyncState): ChatResumeAction {
  if (backendStatus === "idle") {
    const historyDiffers = backendMessageCount !== currentMessageCount;
    return frontendRunning || historyDiffers ? "replace_history" : "none";
  }
  if (backendStatus === "running") {
    // The backend counts every flat event (tool calls and outputs included),
    // while the SDK groups a complete assistant turn into one response card.
    // Their counts therefore cannot be used to decide whether a live stream
    // is behind. Reconnecting an already-active stream replays buffered events
    // after a tab resumes and duplicates the entire turn.
    return frontendRunning ? "none" : "reconnect";
  }
  return "none";
}
