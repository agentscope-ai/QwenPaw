import type { DisplayMessage } from "../api/types";

const EMPTY_MESSAGES: DisplayMessage[] = [];

export function selectChatMessages(
  messages: Record<string, DisplayMessage[]>,
  chatId: string | undefined,
): DisplayMessage[] {
  if (!chatId) return EMPTY_MESSAGES;
  return messages[chatId] ?? EMPTY_MESSAGES;
}
