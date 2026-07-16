import { useEffect } from "react";
import type { AgentSummary } from "@/api/types/agents";

const AGENT_STATUS_POLL_INTERVAL_MS = 1500;

export function useAgentStatusPolling(
  agents: AgentSummary[],
  refresh: () => Promise<void>,
) {
  const hasStartingAgent = agents.some(
    (agent) =>
      agent.startup_status === "pending" || agent.startup_status === "starting",
  );

  useEffect(() => {
    if (!hasStartingAgent) {
      return undefined;
    }

    let cancelled = false;
    let timer: number | undefined;

    const schedule = () => {
      timer = window.setTimeout(async () => {
        try {
          await refresh();
        } catch {
          // Retry transient refresh failures on the next interval.
        } finally {
          if (!cancelled) {
            schedule();
          }
        }
      }, AGENT_STATUS_POLL_INTERVAL_MS);
    };

    schedule();
    return () => {
      cancelled = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
    };
  }, [hasStartingAgent, refresh]);
}
