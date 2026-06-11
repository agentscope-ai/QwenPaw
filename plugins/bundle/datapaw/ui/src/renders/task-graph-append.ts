import { createTaskGraphCard } from "../task-graph/card";
import { getDisplayPlan, subscribeCurrentPlan } from "../lib/plan-store";
import type { HostBundle } from "../types";

let lastRenderLogKey = "";

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

    // Trust host isLast — avoid latestResponseId races that hide the card
    // after the chat stream completes.
    const showOnThisBubble = ctx.isLast !== false;

    const fallback = ctx.fallback?.() ?? null;
    const graph =
      showOnThisBubble && plan
        ? React.createElement(TaskGraphCard, {
            data: { plan, showActions: true },
          })
        : null;

    const logKey = [
      ctx.isLast ? "last" : "not-last",
      showOnThisBubble ? "show" : "hide",
      plan?.id ?? "no-plan",
    ].join(":");
    if (logKey !== lastRenderLogKey) {
      lastRenderLogKey = logKey;
      console.info("[datapaw:task-graph] response render", {
        isLast: ctx.isLast,
        showOnThisBubble,
        hasPlan: Boolean(plan),
        planId: plan?.id,
        willRenderGraph: Boolean(graph),
      });
    }

    return React.createElement(React.Fragment, null, fallback, graph);
  };
}
