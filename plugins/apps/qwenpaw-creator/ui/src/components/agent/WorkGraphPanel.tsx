import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  WorkGraphNode,
  WorkNodeStatus,
} from "@/contracts/creator/workGraph";
import { navigateToLocator } from "@/routing/locators";
import { useWorkGraphStore } from "@/store/workGraphStore";

const STATUS_ICON: Record<WorkNodeStatus, string> = {
  done: "✓",
  running: "◐",
  waiting_review: "⏱",
  failed: "✕",
  gated: "🔒",
  ready: "○",
  stale: "⚠",
};

const STATUS_COLOR: Record<WorkNodeStatus, string> = {
  done: "var(--color-success, #22c55e)",
  running: "var(--color-primary, #3b82f6)",
  waiting_review: "var(--color-warning, #f59e0b)",
  failed: "var(--color-danger, #ef4444)",
  gated: "var(--color-text-tertiary)",
  ready: "var(--color-text-secondary)",
  stale: "var(--color-warning, #f59e0b)",
};

const LANE_LABEL_KEYS: Record<string, string> = {
  visual: "workGraph.laneVisual",
  lineup: "workGraph.laneLineup",
  compose: "workGraph.laneCompose",
};

function laneTitle(
  lane: string,
  nodes: WorkGraphNode[],
  t: (key: string) => string,
): string {
  if (LANE_LABEL_KEYS[lane]) return t(LANE_LABEL_KEYS[lane]);
  // Element lanes carry the element label through their storyboard node.
  const labelled = nodes.find((node) => node.label.includes(" · "));
  return labelled ? labelled.label.split(" · ")[0] : lane;
}

function NodeRow({
  node,
  depth,
  projectId,
}: {
  node: WorkGraphNode;
  depth: number;
  projectId: string;
}) {
  const dispatchNode = useWorkGraphStore((state) => state.dispatchNode);
  const dispatching = useWorkGraphStore((state) =>
    Boolean(state.dispatching[node.id]),
  );
  const { t } = useTranslation();
  const showAction =
    node.dispatchable &&
    (node.status === "failed" ||
      node.status === "ready" ||
      node.status === "stale");
  return (
    <li
      className="flex items-center gap-1.5 py-0.5 text-[11px]"
      style={{ paddingLeft: depth * 14 }}
      data-node-id={node.id}
    >
      {depth > 0 && (
        <span
          aria-hidden
          className="shrink-0 text-[var(--color-text-tertiary)]"
        >
          └
        </span>
      )}
      <span
        aria-label={node.status}
        className={
          node.status === "running" ? "animate-spin shrink-0" : "shrink-0"
        }
        style={{ color: STATUS_COLOR[node.status] }}
      >
        {STATUS_ICON[node.status]}
      </span>
      <button
        type="button"
        className="min-w-0 flex-1 truncate text-left text-[var(--color-text-secondary)] hover:underline"
        onClick={() => navigateToLocator(projectId, node.locator ?? {})}
        title={
          node.error ||
          node.missing.join(t("workGraph.listSeparator")) ||
          node.label
        }
      >
        {node.label}
        {node.status === "running" && node.progress != null && (
          <span className="ml-1 text-[var(--color-text-tertiary)]">
            {Math.round(node.progress * 100)}%
          </span>
        )}
        {node.status === "failed" && node.error && (
          <span className="ml-1 text-[var(--color-danger,#ef4444)]">
            {node.error.slice(0, 40)}
          </span>
        )}
        {node.status === "gated" && node.missing.length > 0 && (
          <span className="ml-1 text-[var(--color-text-tertiary)]">
            {t("workGraph.waitingDeps", { count: node.missing.length })}
          </span>
        )}
      </button>
      {showAction && (
        <button
          type="button"
          disabled={dispatching}
          className="shrink-0 rounded border border-[var(--color-border)] px-1 text-[10px] text-[var(--color-text-secondary)] disabled:opacity-50"
          onClick={() => void dispatchNode(projectId, node.id)}
        >
          {dispatching
            ? "…"
            : node.status === "failed"
            ? t("workGraph.retry")
            : t("workGraph.generate")}
        </button>
      )}
    </li>
  );
}

export default function WorkGraphPanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const graph = useWorkGraphStore((state) => state.graph);
  const refresh = useWorkGraphStore((state) => state.refresh);

  useEffect(() => {
    void refresh(projectId);
  }, [projectId, refresh]);

  const lanes = useMemo(() => {
    if (!graph) return [] as Array<[string, WorkGraphNode[]]>;
    const grouped = new Map<string, WorkGraphNode[]>();
    for (const node of graph.nodes) {
      const bucket = grouped.get(node.lane) ?? [];
      bucket.push(node);
      grouped.set(node.lane, bucket);
    }
    // Stable production order: visual -> lineup -> element lanes -> compose.
    const order = (lane: string) =>
      lane === "visual"
        ? 0
        : lane === "lineup"
        ? 1
        : lane === "compose"
        ? 3
        : 2;
    return [...grouped.entries()].sort(
      (left, right) => order(left[0]) - order(right[0]),
    );
  }, [graph]);

  if (!graph || graph.nodes.length === 0) return null;
  const done = graph.counts.done ?? 0;
  const total = graph.counts.total ?? 0;
  const running = graph.counts.running ?? 0;

  return (
    <div data-testid="work-graph-panel">
      <p className="flex items-center gap-2 font-semibold text-[var(--color-text-secondary)]">
        {t("workGraph.productionProgress", { done, total })}
        {running > 0 && (
          <span className="text-[10px] font-normal text-[var(--color-primary,#3b82f6)]">
            {t("workGraph.parallel", { count: running })}
          </span>
        )}
        <span
          className={
            graph.mediaCalls >= graph.mediaCallBudget
              ? "text-[10px] font-normal text-[var(--color-danger,#ef4444)]"
              : "text-[10px] font-normal text-[var(--color-text-tertiary)]"
          }
          title={t("workGraph.mediaCallBudgetTitle")}
        >
          {t("workGraph.mediaCalls", {
            used: graph.mediaCalls,
            budget: graph.mediaCallBudget,
          })}
        </span>
      </p>
      <div className="mt-0.5 space-y-1">
        {lanes.map(([lane, nodes]) => (
          <div key={lane}>
            <p className="text-[10px] uppercase tracking-wide text-[var(--color-text-tertiary)]">
              {laneTitle(lane, nodes, t)}
            </p>
            <ul>
              {nodes.map((node) => (
                <NodeRow
                  key={node.id}
                  node={node}
                  depth={node.kind === "video" ? 1 : 0}
                  projectId={projectId}
                />
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
