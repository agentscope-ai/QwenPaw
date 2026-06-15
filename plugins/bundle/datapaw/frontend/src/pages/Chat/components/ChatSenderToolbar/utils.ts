import { resolveTaskApiSessionId } from "../../lib/taskApiSession";

/** Resolve the backend session id from chat runtime state. */
export function resolveBackendSessionId(
  currentSessionId?: string | null,
): string | null {
  return resolveTaskApiSessionId(currentSessionId);
}

/** Session key for persisting per-session UI preferences. */
export function resolveSessionStorageKey(
  currentSessionId?: string | null,
): string {
  return resolveBackendSessionId(currentSessionId) || "default";
}
