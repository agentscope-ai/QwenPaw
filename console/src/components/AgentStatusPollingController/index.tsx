import { useAgentStatusPolling } from "@/hooks/useAgentStatusPolling";
import { useAgentStore } from "@/stores/agentStore";

export function AgentStatusPollingController() {
  const agents = useAgentStore((state) => state.agents);
  const refreshAgents = useAgentStore((state) => state.refreshAgents);

  useAgentStatusPolling(agents, refreshAgents);
  return null;
}
