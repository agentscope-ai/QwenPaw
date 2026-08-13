import { useCallback, useEffect, useRef, useState } from "react";

import { agentsApi } from "@/api";
import type {
  ReMeMemoryRuntimeStatus,
  ReMeMemoryStatusResponse,
} from "@/api/modules/agents";
import { useAgentStore } from "@/stores/agentStore";

export type ReMeRuntimeStatus =
  | { type: "unknown" }
  | { type: "checking" }
  | { type: "healthy"; agentId: string; data: ReMeMemoryStatusResponse }
  | { type: "error"; message: string };

const emptyMemoryStatus = (
  runtime: ReMeMemoryRuntimeStatus,
): ReMeMemoryStatusResponse => ({
  components: {},
  components_total: "—",
  process_rss: "—",
  runtime,
});

export function useReMeRuntimeStatus(enabled: boolean) {
  const { selectedAgent } = useAgentStore();
  const agentId = selectedAgent || "default";
  const [runtimeStatus, setRuntimeStatus] = useState<ReMeRuntimeStatus>({
    type: "unknown",
  });
  const requestRef = useRef<AbortController | null>(null);
  const latestDataRef = useRef<{
    agentId: string;
    data: ReMeMemoryStatusResponse;
  } | null>(null);

  const checkMemoryStatus = useCallback(
    async (includeDiagnostics = false) => {
      if (!enabled) {
        setRuntimeStatus({ type: "unknown" });
        return;
      }
      requestRef.current?.abort();
      const controller = new AbortController();
      requestRef.current = controller;
      setRuntimeStatus({ type: "checking" });
      try {
        const currentStatus = await agentsApi.getMemoryRuntimeStatus(
          agentId,
          controller.signal,
        );
        if (!controller.signal.aborted) {
          const cached = latestDataRef.current;
          const data =
            cached?.agentId === agentId
              ? { ...cached.data, runtime: currentStatus }
              : emptyMemoryStatus(currentStatus);
          latestDataRef.current = { agentId, data };
          setRuntimeStatus({
            type: "healthy",
            agentId,
            data,
          });
        }
        if (includeDiagnostics && !controller.signal.aborted) {
          const status = await agentsApi.getMemoryStatus(
            agentId,
            controller.signal,
          );
          if (!controller.signal.aborted) {
            latestDataRef.current = { agentId, data: status };
            setRuntimeStatus({ type: "healthy", agentId, data: status });
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setRuntimeStatus({
            type: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      } finally {
        if (requestRef.current === controller) requestRef.current = null;
      }
    },
    [agentId, enabled],
  );

  useEffect(() => {
    // Runtime state is returned before the optional diagnostic request, so an
    // exclusive maintenance job cannot hide its own reindexing/busy state.
    void checkMemoryStatus(true);
    return () => requestRef.current?.abort();
  }, [checkMemoryStatus]);

  return { runtimeStatus, checkMemoryStatus };
}
