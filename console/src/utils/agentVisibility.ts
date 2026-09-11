import type { AgentSummary } from "../api/types/agents";

/**
 * App-managed profiles are execution engines for their owning PawApp, not
 * standalone personalities in the host's general-purpose Chat surface.
 * Treat an absent field as visible for compatibility with older hosts.
 */
export function isAgentAvailableInChat(agent: AgentSummary): boolean {
  return agent.available_in_chat !== false;
}
