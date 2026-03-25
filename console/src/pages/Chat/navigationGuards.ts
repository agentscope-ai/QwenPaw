export function shouldAutoSyncChatUrl(currentChatId?: string): boolean {
  return !currentChatId || currentChatId === "undefined" || currentChatId === "null";
}
