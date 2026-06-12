import { createTaskGraphCard } from "../task-graph/card";
import {
  getDisplayPlans,
  subscribeCurrentPlan,
  type StoredPlanSnapshot,
} from "../lib/plan-store";
import type { HostBundle } from "../types";

let latestResponseId: string | null = null;
let nextResponseInstanceId = 0;
const latestResponseListeners = new Set<() => void>();
let lastRenderLogKey = "";
const EMPTY_PLANS: StoredPlanSnapshot[] = [];

function logTaskGraphDebug(
  event: string,
  payload?: Record<string, unknown>,
): void {
  console.info("[datapaw:task-graph-debug]", event, payload ?? {});
}

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

function collectResponseMessageIds(
  data: unknown,
  ids = new Set<string>(),
): Set<string> {
  if (!data || typeof data !== "object") return ids;
  const record = data as Record<string, unknown>;

  for (const key of ["id", "msg_id", "message_id", "response_id", "run_id"]) {
    const value = record[key];
    if (typeof value === "string" && value) ids.add(value);
  }

  const output = record.output;
  if (Array.isArray(output)) {
    for (const item of output) {
      collectResponseMessageIds(item, ids);
    }
  }

  const cards = record.cards;
  if (Array.isArray(cards)) {
    for (const card of cards) {
      collectResponseMessageIds(card, ids);
    }
  }

  for (const key of ["message", "response", "data", "raw"]) {
    const nested = record[key];
    if (nested && typeof nested === "object") {
      collectResponseMessageIds(nested, ids);
    }
  }

  return ids;
}

function isTerminalPlan(plan: StoredPlanSnapshot): boolean {
  return ["done", "failed", "abandoned"].includes(String(plan.state));
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
    const plans = useSyncExternalStore(
      subscribeCurrentPlan,
      getDisplayPlans,
      () => EMPTY_PLANS,
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

    const responseMessageIds = collectResponseMessageIds(ctx.data);

    const responseDataId = getResponseId(ctx.data);
    const responseId = responseDataId ?? instanceIdRef.current;

    useEffect(() => {
      setLatestResponseId(responseId);
    }, [responseId]);

    const isLatestResponse =
      Boolean(responseId && latestId && responseId === latestId) ||
      (!latestId && ctx.isLast !== false);
    const selectPlanForResponse = (): {
      plan: StoredPlanSnapshot | null;
      reason: string;
      anchorMessageId: string | null;
      isAnchoredResponse: boolean;
      isLiveMirror: boolean;
    } => {
      const anchored = plans.find((candidate) => {
        const anchor = candidate.anchor_message_id;
        return Boolean(anchor && responseMessageIds.has(anchor));
      });
      if (anchored) {
        return {
          plan: anchored,
          reason: "anchor",
          anchorMessageId: anchored.anchor_message_id ?? null,
          isAnchoredResponse: true,
          isLiveMirror: false,
        };
      }

      const liveCandidates = plans.filter((candidate) => {
        if (!candidate.__datapawCurrent) return false;
        return !isTerminalPlan(candidate);
      });

      const liveMirror = liveCandidates[liveCandidates.length - 1];
      if (liveMirror && isLatestResponse) {
        const anchor = liveMirror.anchor_message_id ?? null;
        return {
          plan: liveMirror,
          reason: anchor ? "latest-current-live-mirror" : "latest-current-no-anchor",
          anchorMessageId: anchor,
          isAnchoredResponse: false,
          isLiveMirror: true,
        };
      }

      return {
        plan: null,
        reason: "none",
        anchorMessageId: null,
        isAnchoredResponse: false,
        isLiveMirror: false,
      };
    };

    const selected = selectPlanForResponse();
    const plan = selected.plan;
    const shouldRenderGraph = Boolean(plan);

    const fallback = ctx.fallback?.() ?? null;
    const graph =
      shouldRenderGraph && plan
        ? React.createElement(TaskGraphCard, {
            data: { plan, showActions: true },
          })
        : null;

    const logKey = [
      ctx.isLast ? "last" : "not-last",
      shouldRenderGraph ? "show" : "hide",
      plan?.id ?? "no-plan",
      selected.anchorMessageId ?? "no-anchor",
      selected.reason,
      responseId,
    ].join(":");
    if (logKey !== lastRenderLogKey) {
      lastRenderLogKey = logKey;
      logTaskGraphDebug("response-append-render", {
        isLast: ctx.isLast ?? null,
        responseId,
        responseDataId,
        latestId,
        isLatestResponse,
        planCount: plans.length,
        hasPlan: Boolean(plan),
        planId: plan?.id ?? null,
        planState: plan?.state ?? null,
        planCurrent: plan?.__datapawCurrent ?? null,
        anchorMessageId: selected.anchorMessageId,
        responseMessageIds: [...responseMessageIds],
        isAnchoredResponse: selected.isAnchoredResponse,
        isLiveMirror: selected.isLiveMirror,
        selectedReason: selected.reason,
        shouldRenderGraph,
        willRenderGraph: Boolean(graph),
      });
    }

    return React.createElement(React.Fragment, null, fallback, graph);
  };
}
