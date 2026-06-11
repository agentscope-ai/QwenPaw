import { createTaskGraphCard } from "../task-graph/card";
import { getDisplayPlan, subscribeCurrentPlan } from "../lib/plan-store";
import type { HostBundle } from "../types";

const seenMessageIds = new Set<string>();
let responseTrackingPlanKey = "";
let lastRenderLogKey = "";

function logTaskGraphDebug(
  event: string,
  payload?: Record<string, unknown>,
): void {
  console.info("[datapaw:task-graph-debug]", event, payload ?? {});
}

function resetResponseTrackingIfNeeded(planKey: string): void {
  if (responseTrackingPlanKey === planKey) return;
  responseTrackingPlanKey = planKey;
  seenMessageIds.clear();
}

function collectResponseMessageIds(
  data: unknown,
  ids = new Set<string>(),
): Set<string> {
  if (!data || typeof data !== "object") return ids;
  const record = data as Record<string, unknown>;

  for (const key of ["id", "msg_id", "message_id"]) {
    const value = record[key];
    if (typeof value === "string" && value) ids.add(value);
  }

  const output = record.output;
  if (Array.isArray(output)) {
    for (const item of output) {
      collectResponseMessageIds(item, ids);
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

export function createTaskGraphAppend(host: HostBundle) {
  const { React } = host;
  const { useSyncExternalStore } = React;
  const TaskGraphCard = createTaskGraphCard(host);

  return function TaskGraphResponseRender(ctx: {
    data?: Record<string, unknown>;
    fallback?: () => unknown;
    isLast?: boolean;
  }) {
    const plan = useSyncExternalStore(
      subscribeCurrentPlan,
      getDisplayPlan,
      () => null,
    );

    const anchorMessageId = plan?.anchor_message_id ?? null;
    const responseMessageIds = collectResponseMessageIds(ctx.data);
    resetResponseTrackingIfNeeded(
      `${plan?.id ?? "no-plan"}:${anchorMessageId ?? "no-anchor"}`,
    );
    for (const messageId of responseMessageIds) {
      seenMessageIds.add(messageId);
    }

    // Trust host isLast for the fallback bubble. The old latestResponseId
    // tracking raced with stream completion and could hide the graph.
    const showOnThisBubble = ctx.isLast !== false;
    const isAnchoredResponse = Boolean(
      anchorMessageId && responseMessageIds.has(anchorMessageId),
    );
    const hasSeenAnchor = Boolean(
      anchorMessageId && seenMessageIds.has(anchorMessageId),
    );
    const shouldRenderGraph = plan
      ? isAnchoredResponse ||
        (!hasSeenAnchor && showOnThisBubble) ||
        (!anchorMessageId && showOnThisBubble)
      : false;

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
      anchorMessageId ?? "no-anchor",
    ].join(":");
    if (logKey !== lastRenderLogKey) {
      lastRenderLogKey = logKey;
      logTaskGraphDebug("response-append-render", {
        isLast: ctx.isLast ?? null,
        showOnThisBubble,
        hasPlan: Boolean(plan),
        planId: plan?.id ?? null,
        planState: plan?.state ?? null,
        anchorMessageId,
        responseMessageIds: [...responseMessageIds],
        isAnchoredResponse,
        hasSeenAnchor,
        shouldRenderGraph,
        willRenderGraph: Boolean(graph),
      });
    }

    return React.createElement(React.Fragment, null, fallback, graph);
  };
}
