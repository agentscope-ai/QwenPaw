import { useEffect, useState } from "react";
import { agentsApi } from "../../api/modules/agents";

/** Match the tag endpoints' backend requirement before exposing navigation. */
export function useMemoryTagSupport(agentId: string): boolean {
  const [supportedAgent, setSupportedAgent] = useState<string | null>(null);
  useEffect(() => {
    setSupportedAgent(null);
    let controller: AbortController | undefined;
    const refresh = () => {
      controller?.abort();
      const current = new AbortController();
      controller = current;
      void agentsApi.getAgent(agentId, current.signal).then(
        (config) => {
          if (current.signal.aborted) return;
          const running = config.running as
            | { memory_manager_backend?: string }
            | undefined;
          setSupportedAgent(
            running?.memory_manager_backend === "remelight" ? agentId : null,
          );
        },
        () => {
          if (!current.signal.aborted) setSupportedAgent(null);
        },
      );
    };
    refresh();
    window.addEventListener("focus", refresh);
    return () => {
      controller?.abort();
      window.removeEventListener("focus", refresh);
    };
  }, [agentId]);
  return supportedAgent === agentId;
}
