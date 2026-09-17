import type { AgentSummary } from "@/api/types/agents";

export type AgentAccessGroup = "owner" | "collaborator" | "user";

export function groupAgentsByAccess(
  agents: AgentSummary[],
): Record<AgentAccessGroup, AgentSummary[]> {
  const grouped: Record<AgentAccessGroup, AgentSummary[]> = {
    owner: [],
    collaborator: [],
    user: [],
  };
  for (const agent of agents) {
    grouped[agent.access_role ?? "owner"].push(agent);
  }
  return grouped;
}
