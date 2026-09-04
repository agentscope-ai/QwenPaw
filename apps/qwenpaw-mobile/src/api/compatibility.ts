import type { AgentSummary } from "./types";

export function isChatGroupsUnsupported(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return message.trim().toLowerCase() === "chat not found: groups";
}

export function availableAgents(agents: AgentSummary[]): AgentSummary[] {
  return agents.filter((agent) => (
    agent.enabled !== false && agent.available_in_chat !== false
  ));
}
