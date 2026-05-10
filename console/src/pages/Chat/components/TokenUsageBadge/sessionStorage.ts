import type { TokenUsageBadgeSnapshot } from "./TokenUsageBadge";

const KEY_PREFIX = "qwenpaw_token_badge_";

export function resolveTokenBadgeStorageKey(chatId: string): string | null {
  return chatId ? `${KEY_PREFIX}${chatId}` : null;
}

export function saveTokenBadgeSnapshot(
  key: string,
  snapshot: TokenUsageBadgeSnapshot,
): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(snapshot));
  } catch {
    // QuotaExceededError / SecurityError
  }
}

export function loadTokenBadgeSnapshot(
  chatIdOrKey: string,
): TokenUsageBadgeSnapshot | null {
  try {
    const key = chatIdOrKey.startsWith(KEY_PREFIX)
      ? chatIdOrKey
      : `${KEY_PREFIX}${chatIdOrKey}`;
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as TokenUsageBadgeSnapshot) : null;
  } catch {
    return null;
  }
}

export function migrateTokenBadgeSnapshot(
  oldChatId: string,
  newChatId: string,
): void {
  if (!oldChatId || !newChatId || oldChatId === newChatId) return;
  try {
    const oldKey = `${KEY_PREFIX}${oldChatId}`;
    const newKey = `${KEY_PREFIX}${newChatId}`;
    const raw = sessionStorage.getItem(oldKey);
    if (raw) {
      sessionStorage.setItem(newKey, raw);
      sessionStorage.removeItem(oldKey);
    }
  } catch {
    // ignore
  }
}
