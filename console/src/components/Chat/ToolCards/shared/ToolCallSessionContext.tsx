import { resolveBackendSessionId } from "../../../../utils/resolveBackendSessionId";

/** Backend session_id for tool-call control APIs (never a bare local library id). */
export function useToolCallSessionId(): string {
  return resolveBackendSessionId();
}
