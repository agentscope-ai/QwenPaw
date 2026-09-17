export const AUTHENTICATED_USER_ID_KEY =
  "qwenpaw_authenticated_user_id";

export function getAuthenticatedStorageUserId(): string | undefined {
  try {
    return localStorage.getItem(AUTHENTICATED_USER_ID_KEY) || undefined;
  } catch {
    return undefined;
  }
}

export function getUserScopedStorageKey(
  baseKey: string,
  userId: string | undefined = getAuthenticatedStorageUserId(),
): string {
  if (!userId) return baseKey;
  return `${baseKey}:user:${userId}`;
}

export function getUserScopedStoragePrefix(
  basePrefix: string,
  userId: string | undefined = getAuthenticatedStorageUserId(),
): string {
  if (!userId) return basePrefix;
  const normalized = basePrefix.endsWith(":")
    ? basePrefix.slice(0, -1)
    : basePrefix;
  return `${getUserScopedStorageKey(normalized, userId)}:`;
}
