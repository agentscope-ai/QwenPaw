import AsyncStorage from "@react-native-async-storage/async-storage";

import type { ChatSpec } from "../api/types";

const PINNED_CHAT_KEY = "qwenpaw.mobile.pinned-chat";

export async function loadPinnedChatId(): Promise<string | null> {
  return AsyncStorage.getItem(PINNED_CHAT_KEY);
}

export async function savePinnedChatId(chatId: string | null): Promise<void> {
  if (chatId) {
    await AsyncStorage.setItem(PINNED_CHAT_KEY, chatId);
    return;
  }
  await AsyncStorage.removeItem(PINNED_CHAT_KEY);
}

export function sortChatsByPinned(
  chats: ChatSpec[],
  pinnedChatId: string | null,
): ChatSpec[] {
  if (!pinnedChatId) return chats;
  return [...chats].sort((left, right) => {
    if (left.id === pinnedChatId) return -1;
    if (right.id === pinnedChatId) return 1;
    return 0;
  });
}
