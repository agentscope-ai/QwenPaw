import { DATAPAW_AGENT_ID, STORAGE_KEY } from "./constants";

export function getSelectedAgentId(): string | null {
  const hostAgent = (
    window as { QwenPaw?: { host?: { getSelectedAgentId?: () => string } } }
  ).QwenPaw?.host?.getSelectedAgentId?.();
  if (typeof hostAgent === "string" && hostAgent) return hostAgent;

  try {
    const sessionRaw = sessionStorage.getItem(STORAGE_KEY);
    if (sessionRaw) {
      const agent = JSON.parse(sessionRaw)?.state?.selectedAgent;
      if (typeof agent === "string" && agent) return agent;
    }
    const localRaw = localStorage.getItem(STORAGE_KEY);
    if (localRaw) {
      const agent = JSON.parse(localRaw)?.state?.selectedAgent;
      if (typeof agent === "string" && agent) return agent;
    }
  } catch {
    /* ignore */
  }
  return null;
}

export function isDatapawAgentSelected(): boolean {
  return getSelectedAgentId() === DATAPAW_AGENT_ID;
}

import { resolveBackendSessionId } from "./session-id";

export function getSessionId(): string | null {
  return resolveBackendSessionId();
}
