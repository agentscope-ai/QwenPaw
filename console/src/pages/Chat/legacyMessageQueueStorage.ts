const LEGACY_MESSAGE_QUEUE_STORAGE_PREFIX = "qwenpaw:message-queue:";

/**
 * Remove queue data written by the pre-SDK CoPaw implementation.
 *
 * Current InputQueue persistence is owned by @agentscope-ai/chat. CoPaw only
 * keeps this compatibility cleanup for sessions created before that migration.
 */
export function clearLegacyStoredMessageQueue(sessionId: string | undefined) {
  if (!sessionId) return;
  const key = `${LEGACY_MESSAGE_QUEUE_STORAGE_PREFIX}${sessionId}`;
  try {
    localStorage.removeItem(key);
  } catch {
    // Local storage can be unavailable in some browser modes.
  }
  try {
    sessionStorage.removeItem(key);
  } catch {
    // Session storage can be unavailable in some browser modes.
  }
}
