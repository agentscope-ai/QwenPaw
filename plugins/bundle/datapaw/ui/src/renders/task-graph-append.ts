import { createTaskGraphCard } from "../task-graph/card";
import { getCurrentPlan, subscribeCurrentPlan } from "../lib/plan-store";
import type { HostBundle } from "../types";

let lastRenderLogKey = "";
let latestResponseId: string | null = null;
let nextResponseInstanceId = 0;
const latestResponseListeners = new Set<() => void>();

function subscribeLatestResponse(listener: () => void): () => void {
  latestResponseListeners.add(listener);
  return () => latestResponseListeners.delete(listener);
}

function getLatestResponseId(): string | null {
  return latestResponseId;
}

function setLatestResponseId(responseId: string | null): void {
  if (!responseId || latestResponseId === responseId) return;
  latestResponseId = responseId;
  latestResponseListeners.forEach((listener) => listener());
}

function getResponseId(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const record = data as Record<string, unknown>;
  if (typeof record.id === "string" && record.id) return record.id;
  if (typeof record.msg_id === "string" && record.msg_id) return record.msg_id;
  if (typeof record.message_id === "string" && record.message_id) {
    return record.message_id;
  }
  if (typeof record.response_id === "string" && record.response_id) {
    return record.response_id;
  }
  if (typeof record.run_id === "string" && record.run_id) {
    return record.run_id;
  }
  if (typeof record.sequence_number === "number") {
    return `seq:${record.sequence_number}`;
  }
  if (typeof record.created_at === "number") {
    return `created:${record.created_at}`;
  }
  return null;
}

export function createTaskGraphAppend(host: HostBundle) {
  const { React } = host;
  const { useEffect, useRef, useSyncExternalStore } = React;
  const TaskGraphCard = createTaskGraphCard(host);

  return function TaskGraphResponseRender(ctx: {
    data?: Record<string, unknown>;
    fallback?: () => unknown;
    isLast?: boolean;
  }) {
    const plan = useSyncExternalStore(
      subscribeCurrentPlan,
      getCurrentPlan,
      () => null,
    );
    const latestId = useSyncExternalStore(
      subscribeLatestResponse,
      getLatestResponseId,
      () => null,
    );
    const instanceIdRef = useRef<string | null>(null);
    if (!instanceIdRef.current) {
      nextResponseInstanceId += 1;
      instanceIdRef.current = `instance:${nextResponseInstanceId}`;
    }
    const responseDataId = getResponseId(ctx.data);
    const responseId = responseDataId ?? instanceIdRef.current;

    useEffect(() => {
      setLatestResponseId(responseId);
    }, [responseId]);

    const isLatestResponse =
      Boolean(responseId && latestId && responseId === latestId) ||
      (!latestId && ctx.isLast !== false);

    const fallback = ctx.fallback?.() ?? null;
    const graph =
      isLatestResponse && plan
        ? React.createElement(TaskGraphCard, {
            data: { plan, showActions: true },
          })
        : null;

    const logKey = [
      ctx.isLast ? "last" : "not-last",
      responseId ?? "no-response-id",
      latestId ?? "no-latest-id",
      isLatestResponse ? "latest" : "not-latest",
      plan?.id ?? "no-plan",
    ].join(":");
    if (logKey !== lastRenderLogKey) {
      lastRenderLogKey = logKey;
      console.info("[datapaw:task-graph] response render", {
        isLast: ctx.isLast,
        responseId,
        latestId,
        isLatestResponse,
        hasPlan: Boolean(plan),
        planId: plan?.id,
        willRenderGraph: Boolean(graph),
      });
    }

    return React.createElement(React.Fragment, null, fallback, graph);
  };
}
