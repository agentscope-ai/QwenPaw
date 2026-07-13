import { useEffect, useState } from "react";
import { agentApi } from "../api/modules/agent";
import { useAgentStore } from "../stores/agentStore";
import { normalizeLevel, type ToolExecutionLevel } from "../utils/approval";

/**
 * Returns the running-config approval level for the currently selected agent.
 * Re-fetches automatically when the selected agent changes, and falls back to
 * "AUTO" on error.
 */
export function useAgentRunningConfigApprovalLevel(): ToolExecutionLevel {
  const { selectedAgent } = useAgentStore();
  const [level, setLevel] = useState<ToolExecutionLevel>("AUTO");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const config = await agentApi.getAgentRunningConfig();
        if (!cancelled) {
          setLevel(normalizeLevel(config.approval_level));
        }
      } catch {
        if (!cancelled) {
          setLevel("AUTO");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedAgent]);

  return level;
}
