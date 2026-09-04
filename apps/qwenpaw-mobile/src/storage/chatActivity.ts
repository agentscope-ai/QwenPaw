import AsyncStorage from "@react-native-async-storage/async-storage";

import type { ChatActivityMap } from "./chatActivityModel";

export {
  type ChatActivity,
  chatActivityKey,
  type ChatActivityMap,
  type ChatActivityRecord,
  markActivityRead,
  reconcileChatActivity,
  resolveChatActivity,
} from "./chatActivityModel";

const CHAT_ACTIVITY_KEY = "qwenpaw.mobile.chat-activity.v1";

export async function loadChatActivity(): Promise<ChatActivityMap> {
  const stored = await AsyncStorage.getItem(CHAT_ACTIVITY_KEY);
  if (!stored) return {};
  try {
    const parsed = JSON.parse(stored) as ChatActivityMap;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    await AsyncStorage.removeItem(CHAT_ACTIVITY_KEY);
    return {};
  }
}

export async function saveChatActivity(
  activity: ChatActivityMap,
): Promise<void> {
  await AsyncStorage.setItem(CHAT_ACTIVITY_KEY, JSON.stringify(activity));
}
