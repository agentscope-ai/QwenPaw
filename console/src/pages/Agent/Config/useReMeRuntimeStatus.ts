import { useCallback, useEffect, useRef, useState } from "react";

import { agentsApi } from "@/api";
import type { ReMeMemoryStatusResponse } from "@/api/modules/agents";
import type { AgentRequestContext } from "@/api/modules/agentRequestContext";
import { useAgentStore } from "@/stores/agentStore";

export type ReMeRuntimeStatus =
  | { type: "unknown" }
  | { type: "checking" }
  | { type: "healthy"; agentId: string; data: ReMeMemoryStatusResponse }
  | { type: "error"; message: string };

const STATUS_POLL_INTERVAL_MS = 2_000;

const emptyMemoryStatus = (
  runtime: ReMeMemoryStatusResponse["runtime"],
): ReMeMemoryStatusResponse => ({
  components: {},
  components_total: "—",
  process_rss: "—",
  runtime,
});

export function useReMeRuntimeStatus(
  enabled: boolean,
  requestContext?: AgentRequestContext,
) {
  const { selectedAgent } = useAgentStore();
  const agentId = requestContext?.agentId || selectedAgent || "default";
  const [runtimeStatus, setRuntimeStatus] = useState<ReMeRuntimeStatus>({
    type: "unknown",
  });
  const requestRef = useRef<AbortController | null>(null);

  const checkMemoryStatus = useCallback(async () => {
    if (!enabled) {
      setRuntimeStatus({ type: "unknown" });
      return;
    }
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setRuntimeStatus((current) =>
      current.type === "healthy" && current.agentId === agentId
        ? current
        : { type: "checking" },
    );
    try {
      const status = requestContext
        ? await agentsApi.getMemoryStatus(
            agentId,
            controller.signal,
            requestContext,
          )
        : await agentsApi.getMemoryStatus(agentId, controller.signal);
      if (!controller.signal.aborted) {
        setRuntimeStatus({ type: "healthy", agentId, data: status });
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
  }, [agentId, enabled, requestContext]);

  useEffect(() => {
    if (!enabled) {
      setRuntimeStatus({ type: "unknown" });
      requestRef.current?.abort();
      return undefined;
    }
    let active = true;
    let timer: number | undefined;
    let controller: AbortController | null = null;

    const poll = async () => {
      controller = new AbortController();
      try {
        const runtime = requestContext
          ? await agentsApi.getMemoryRuntimeStatus(
              agentId,
              controller.signal,
              requestContext,
            )
          : await agentsApi.getMemoryRuntimeStatus(agentId, controller.signal);
        if (active) {
          setRuntimeStatus((current) => ({
            type: "healthy",
            agentId,
            data:
              current.type === "healthy" && current.agentId === agentId
                ? { ...current.data, runtime }
                : emptyMemoryStatus(runtime),
          }));
        }
      } catch (error) {
        if (active && !controller.signal.aborted) {
          setRuntimeStatus((current) =>
            current.type === "healthy" && current.agentId === agentId
              ? current
              : {
                  type: "error",
                  message:
                    error instanceof Error ? error.message : String(error),
                },
          );
        }
      } finally {
        if (active) {
          timer = window.setTimeout(poll, STATUS_POLL_INTERVAL_MS);
        }
      }
    };

    setRuntimeStatus({ type: "checking" });
    void poll();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
      controller?.abort();
      requestRef.current?.abort();
    };
  }, [agentId, enabled, requestContext]);

  return { runtimeStatus, checkMemoryStatus };
}
