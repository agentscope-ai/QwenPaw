export const DATA_SOURCE_STORAGE_PREFIX = "qwenpaw_data_source_";

export function readSelectedDataSourceId(sessionKey: string): string | null {
  try {
    return sessionStorage.getItem(`${DATA_SOURCE_STORAGE_PREFIX}${sessionKey}`);
  } catch {
    return null;
  }
}

export function writeSelectedDataSourceId(
  sessionKey: string,
  value: string,
): void {
  try {
    sessionStorage.setItem(`${DATA_SOURCE_STORAGE_PREFIX}${sessionKey}`, value);
  } catch {
    /* ignore */
  }
}

/** Prefer stored selection when still valid; otherwise fall back to the first item. */
export function resolveSelectedDataSourceId(
  sessionKey: string,
  connectionIds: string[],
): string | null {
  if (connectionIds.length === 0) return null;

  const stored = readSelectedDataSourceId(sessionKey);
  if (stored && connectionIds.includes(stored)) {
    return stored;
  }
  return connectionIds[0];
}
