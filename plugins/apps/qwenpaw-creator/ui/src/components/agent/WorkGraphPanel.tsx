import { useEffect } from "react";
import { message } from "antd";
import { Check, Clock3, Loader2, AlertCircle, Circle } from "lucide-react";
import { useTranslation } from "react-i18next";
import type {
  WorkGraphNode,
  WorkNodeStatus,
} from "@/contracts/creator/workGraph";
import { navigateToLocator } from "@/routing/locators";
import { creatorWorkNodeLabel } from "@/lib/creatorPresentation";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useWorkGraphStore } from "@/store/workGraphStore";

const stateKeys: Record<WorkNodeStatus, string> = {
  done: "done",
  running: "running",
  waiting_review: "waiting_review",
  failed: "failed",
  gated: "waitingDeps",
  ready: "ready",
  stale: "stale",
};
function NodeRow({
  node,
  projectId,
}: {
  node: WorkGraphNode;
  projectId: string;
}) {
  const { t } = useTranslation();
  const project = useProjectSnapshotStore((state) =>
    state.projectId === projectId ? state.project : null,
  );
  const publicLabel = creatorWorkNodeLabel(node, project);
  const dispatch = useWorkGraphStore((state) => state.dispatchNode);
  const dispatching = useWorkGraphStore((state) =>
    Boolean(state.dispatching[node.id]),
  );
  const actionLabel = t(
    `workGraph.actions.${node.kind}.${
      node.status === "failed" ? "retry" : "generate"
    }`,
  );
  const showAction =
    node.dispatchable &&
    node.missing.length === 0 &&
    ["failed", "ready", "stale"].includes(node.status);
  const percent =
    node.status === "running" &&
    node.progress != null &&
    Number.isFinite(node.progress) &&
    node.progress >= 0 &&
    node.progress <= 1
      ? Math.round(node.progress * 100)
      : null;
  const Icon =
    node.status === "running"
      ? Loader2
      : node.status === "done"
      ? Check
      : node.status === "failed"
      ? AlertCircle
      : node.status === "ready"
      ? Circle
      : Clock3;
  return (
    <li data-node-id={node.id} className="agent-work-item">
      <Icon
        aria-hidden
        className={`h-3.5 w-3.5 shrink-0 ${
          node.status === "running"
            ? "animate-spin text-[var(--color-accent)]"
            : node.status === "done"
            ? "text-[var(--color-success)]"
            : node.status === "failed"
            ? "text-[var(--color-danger)]"
            : "text-[var(--color-text-tertiary)]"
        }`}
      />
      <button
        type="button"
        className="min-w-0 flex-1 text-left"
        onClick={() => navigateToLocator(projectId, node.locator ?? {})}
        title={publicLabel}
      >
        <span className="block truncate font-medium text-[var(--color-text-secondary)]">
          {publicLabel}
        </span>
        <span className="text-[11px] text-[var(--color-text-tertiary)]">
          {t(`agentActivity.${stateKeys[node.status]}`)}
          {percent != null && ` · ${percent}%`}
        </span>
      </button>
      {showAction && (
        <button
          type="button"
          disabled={dispatching}
          aria-label={`${actionLabel} · ${publicLabel}`}
          className="agent-work-action"
          onClick={() =>
            void dispatch(projectId, node.id).catch(() =>
              message.error(t("agentActivity.failureHint")),
            )
          }
        >
          {dispatching ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            actionLabel
          )}
        </button>
      )}
    </li>
  );
}
export default function WorkGraphPanel({ projectId }: { projectId: string }) {
  const graph = useWorkGraphStore((state) =>
    state.projectId === projectId ? state.graph : null,
  );
  const refresh = useWorkGraphStore((state) => state.refresh);
  useEffect(() => {
    void refresh(projectId);
  }, [projectId, refresh]);
  if (!graph?.nodes.length) return null;
  return (
    <div data-testid="work-graph-panel">
      <ul className="space-y-1">
        {graph.nodes.map((node) => (
          <NodeRow key={node.id} node={node} projectId={projectId} />
        ))}
      </ul>
    </div>
  );
}
