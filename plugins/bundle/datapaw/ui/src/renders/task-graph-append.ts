import { createTaskGraphCard } from "../task-graph/card";
import {
  getDisplayPlans,
  subscribeCurrentPlan,
  type StoredPlanSnapshot,
} from "../lib/plan-store";
import type { HostBundle } from "../types";

let lastRenderLogKey = "";
const EMPTY_PLANS: StoredPlanSnapshot[] = [];

type ResponseIds = {
  graphIds: Set<string>;
  explicitGraphIds: string[];
};

function createResponseIds(): ResponseIds {
  return {
    graphIds: new Set<string>(),
    explicitGraphIds: [],
  };
}

function sampleIds(ids: Iterable<string>): string[] {
  return [...ids].slice(0, 8);
}

function addGraphId(ids: ResponseIds, id: string): void {
  if (!id) return;
  ids.graphIds.add(id);
  ids.explicitGraphIds.push(id);
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
  ids = createResponseIds(),
  seen = new WeakSet<object>(),
): ResponseIds {
  if (!data || typeof data !== "object") return ids;
  if (seen.has(data)) return ids;
  seen.add(data);
  if (Array.isArray(data)) {
    for (const item of data) collectResponseIds(item, ids, seen);
    return ids;
  }
  const record = data as Record<string, unknown>;
  if (record.code === "task_graph") return ids;

  const graphId = record.graph_id;
  if (typeof graphId === "string" && graphId) {
    addGraphId(ids, graphId);
  }
  const metadataGraphId = (record.metadata as { graph_id?: unknown } | undefined)
    ?.graph_id;
  if (typeof metadataGraphId === "string" && metadataGraphId) {
    addGraphId(ids, metadataGraphId);
  }

  for (const value of Object.values(record)) {
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
    const responseGraphIds = responseIds.graphIds;

    const responseId = getResponseId(ctx.data);
    const selectPlanForResponse = (): {
      plan: StoredPlanSnapshot | null;
      reason: string;
      anchorMessageId: string | null;
    } => {
      const planById = new Map(plans.map((item) => [item.id, item]));
      const matchingGraphIds = [
        ...new Set(
          responseIds.explicitGraphIds.filter((graphId) =>
            planById.has(graphId),
          ),
        ),
      ];
      if (matchingGraphIds.length === 1) {
        const explicitGraphMatch = planById.get(matchingGraphIds[0]);
        return {
          plan: explicitGraphMatch ?? null,
          reason: "graph-id",
          anchorMessageId: explicitGraphMatch?.anchor_message_id ?? null,
        };
      }
      if (matchingGraphIds.length > 1) {
        return {
          plan: null,
          reason: "multiple-graph-ids",
          anchorMessageId: null,
        };
      }

      return {
        plan: null,
        reason: "none",
        anchorMessageId: null,
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
          graphInResponse: responseGraphIds.has(item.id),
        })),
        hasPlan: Boolean(plan),
        planId: plan?.id ?? null,
        planState: plan?.state ?? null,
        anchorMessageId: selected.anchorMessageId,
        responseGraphIds: sampleIds(responseGraphIds),
        explicitGraphIds: sampleIds(responseIds.explicitGraphIds),
        selectedReason: selected.reason,
        willRenderGraph: Boolean(graph),
      });
    }

    return React.createElement(React.Fragment, null, fallback, graph);
  };
}
