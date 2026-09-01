import { useCallback, useEffect, useRef, useState } from "react";

import { agentsApi } from "@/api";
import type {
  ReMeMemoryRuntimeStatus,
  ReMeMemoryStatusResponse,
} from "@/api/modules/agents";
import { useAgentStore } from "@/stores/agentStore";

type LoadableStatus<T> =
  | { type: "unknown" }
  | { type: "checking" }
  | { type: "healthy"; agentId: string; data: T }
  | { type: "error"; message: string };

export type ReMeRuntimeStatus = LoadableStatus<ReMeMemoryRuntimeStatus>;
export type ReMeDiagnosticsStatus = LoadableStatus<ReMeMemoryStatusResponse>;

export function useReMeRuntimeStatus(enabled: boolean) {
  const { selectedAgent } = useAgentStore();
  const agentId = selectedAgent || "default";
  const [runtimeStatus, setRuntimeStatus] = useState<ReMeRuntimeStatus>({
    type: "unknown",
  });
  const [diagnosticsStatus, setDiagnosticsStatus] =
    useState<ReMeDiagnosticsStatus>({ type: "unknown" });
  const requestRef = useRef<AbortController | null>(null);

  const checkMemoryStatus = useCallback(
    async (includeDiagnostics = false, silent = false) => {
      if (!enabled) {
        setRuntimeStatus({ type: "unknown" });
        setDiagnosticsStatus({ type: "unknown" });
        return;
      }
      requestRef.current?.abort();
      const controller = new AbortController();
      requestRef.current = controller;
      if (!silent) setRuntimeStatus({ type: "checking" });
      if (includeDiagnostics && !silent) {
        setDiagnosticsStatus({ type: "checking" });
      }
      let runtimeLoaded = false;
      try {
        const currentStatus = await agentsApi.getMemoryRuntimeStatus(
          agentId,
          controller.signal,
        );
        if (!controller.signal.aborted) {
          setRuntimeStatus({
            type: "healthy",
            agentId,
            data: currentStatus,
          });
          runtimeLoaded = true;
        }
        if (includeDiagnostics && !controller.signal.aborted) {
          const status = await agentsApi.getMemoryStatus(
            agentId,
            controller.signal,
          );
          if (!controller.signal.aborted) {
            setDiagnosticsStatus({ type: "healthy", agentId, data: status });
          }
        }
      } catch (error) {
        if (!controller.signal.aborted && !silent) {
          const failure = {
            type: "error",
            message: error instanceof Error ? error.message : String(error),
          } as const;
          if (runtimeLoaded) setDiagnosticsStatus(failure);
          else {
            setRuntimeStatus(failure);
            if (includeDiagnostics) setDiagnosticsStatus(failure);
          }
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

  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible" && !requestRef.current) {
        void checkMemoryStatus(false, true);
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [checkMemoryStatus, enabled]);

  return { runtimeStatus, diagnosticsStatus, checkMemoryStatus };
}
