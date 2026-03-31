import type { AgentSummary } from "@/api/types/agents";

export function reorderAgents(
  agents: AgentSummary[],
  activeId: string,
  overId: string,
): AgentSummary[] {
  if (activeId === overId) {
    return agents;
  }

  const oldIndex = agents.findIndex((agent) => agent.id === activeId);
  const newIndex = agents.findIndex((agent) => agent.id === overId);

  if (oldIndex === -1 || newIndex === -1) {
    return agents;
  }

  const nextAgents = [...agents];
  const [movedAgent] = nextAgents.splice(oldIndex, 1);
  nextAgents.splice(newIndex, 0, movedAgent);
  return nextAgents;
}
