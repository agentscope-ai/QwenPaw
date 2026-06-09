/** Strip proxies / observables from chat message data before React traversal. */
export function toPlainJson<T>(value: T): T {
  if (value === null || value === undefined) {
    return value;
  }
  try {
    return JSON.parse(JSON.stringify(value)) as T;
  } catch {
    return value;
  }
}
