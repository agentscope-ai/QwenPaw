import { useEffect } from "react";
import type { AgentSummary } from "@/api/types/agents";

const AGENT_STATUS_POLL_INTERVAL_MS = 1500;

export function useAgentStatusPolling(
  agents: AgentSummary[],
  refresh: () => Promise<void>,
) {
  useEffect(() => {
    const hasStartingAgent = agents.some(
      (agent) =>
        agent.startup_status === "pending" ||
        agent.startup_status === "starting",
    );
    if (!hasStartingAgent) {
      return undefined;
    }

    const timer = window.setTimeout(() => {
      void refresh();
    }, AGENT_STATUS_POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [agents, refresh]);
}
