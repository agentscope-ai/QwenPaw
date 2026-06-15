import { createTaskGraphCard } from "../task-graph/card";
import {
  getDisplayPlans,
  subscribeCurrentPlan,
  type StoredPlanSnapshot,
} from "../lib/plan-store";
import type { HostBundle } from "../types";

let lastRenderLogKey = "";
const EMPTY_PLANS: StoredPlanSnapshot[] = [];
const GRAPH_ID_PATTERN = /\bgraph_[A-Za-z0-9_-]+\b/g;

function sampleIds(ids: Set<string>): string[] {
  return [...ids].slice(0, 8);
}

function logTaskGraphDebug(
  event: string,
  payload?: Record<string, unknown>,
): void {
  void event;
  void payload;
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

function collectResponseIds(
  data: unknown,
  ids = { messageIds: new Set<string>(), graphIds: new Set<string>() },
  seen = new WeakSet<object>(),
): { messageIds: Set<string>; graphIds: Set<string> } {
  if (!data || typeof data !== "object") return ids;
  if (seen.has(data)) return ids;
  seen.add(data);
  if (Array.isArray(data)) {
    for (const item of data) collectResponseIds(item, ids, seen);
    return ids;
  }
  const record = data as Record<string, unknown>;

  for (const key of ["id", "msg_id", "message_id", "response_id", "run_id"]) {
    const value = record[key];
    if (typeof value === "string" && value) ids.messageIds.add(value);
  }
  const graphId = record.graph_id;
  if (typeof graphId === "string" && graphId) {
    ids.graphIds.add(graphId);
  }

  for (const value of Object.values(record)) {
    if (typeof value === "string") {
      for (const match of value.matchAll(GRAPH_ID_PATTERN)) {
        ids.graphIds.add(match[0]);
      }
      continue;
    }
    collectResponseIds(value, ids, seen);
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
    const plans = useSyncExternalStore(
      subscribeCurrentPlan,
      getDisplayPlans,
      () => EMPTY_PLANS,
    );
    const responseIds = collectResponseIds(ctx.data);
    const responseMessageIds = responseIds.messageIds;
    const responseGraphIds = responseIds.graphIds;

    const responseId = getResponseId(ctx.data);
    const selectPlanForResponse = (): {
      plan: StoredPlanSnapshot | null;
      reason: string;
      anchorMessageId: string | null;
      isAnchoredResponse: boolean;
    } => {
      const anchored = plans.find((candidate) => {
        const anchor = candidate.anchor_message_id;
        return Boolean(
          (anchor && responseMessageIds.has(anchor)) ||
            responseGraphIds.has(candidate.id),
        );
      });
      if (anchored) {
        return {
          plan: anchored,
          reason: responseGraphIds.has(anchored.id) ? "graph-id" : "anchor",
          anchorMessageId: anchored.anchor_message_id ?? null,
          isAnchoredResponse: true,
        };
      }

      return {
        plan: null,
        reason: "none",
        anchorMessageId: null,
        isAnchoredResponse: false,
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
        planCount: plans.length,
        plans: plans.map((item) => ({
          id: item.id,
          state: item.state,
          current: Boolean(item.__datapawCurrent),
          anchorMessageId: item.anchor_message_id ?? null,
          anchorInResponse: item.anchor_message_id
            ? responseMessageIds.has(item.anchor_message_id)
            : false,
          graphInResponse: responseGraphIds.has(item.id),
        })),
        hasPlan: Boolean(plan),
        planId: plan?.id ?? null,
        planState: plan?.state ?? null,
        anchorMessageId: selected.anchorMessageId,
        responseMessageIdCount: responseMessageIds.size,
        responseMessageIdSample: sampleIds(responseMessageIds),
        responseGraphIds: sampleIds(responseGraphIds),
        selectedReason: selected.reason,
        willRenderGraph: Boolean(graph),
      });
    }

    return React.createElement(React.Fragment, null, fallback, graph);
  };
}
