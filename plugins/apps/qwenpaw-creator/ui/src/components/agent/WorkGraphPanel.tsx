import { useEffect, useState } from "react";
import { message, Modal } from "antd";
import {
  Check,
  Clock3,
  Loader2,
  AlertCircle,
  Circle,
  Pause,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { CreatorHttpError } from "@/api/creator/client";
import type {
  WorkGraphNode,
  WorkNodeStatus,
} from "@/contracts/creator/workGraph";
import { navigateToLocator } from "@/routing/locators";
import { creatorWorkNodeLabel } from "@/lib/creatorPresentation";
import { taskProgressPercent } from "@/lib/taskPresentation";
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

export function WorkGraphManualHoldNotice({
  projectId,
}: {
  projectId: string;
}) {
  const { t } = useTranslation();
  const hold = useWorkGraphStore((state) =>
    state.projectId === projectId ? state.graph?.manualHold : undefined,
  );
  const resuming = useWorkGraphStore(
    (state) => state.projectId === projectId && state.resuming,
  );
  const resume = useWorkGraphStore((state) => state.resume);
  const [confirmation, setConfirmation] = useState<{
    projectId: string;
    revision: number;
  } | null>(null);
  useEffect(() => setConfirmation(null), [projectId]);
  if (!hold?.nodeIds.length) return null;
  return (
    <div className="shrink-0 border-t border-[var(--color-border)] px-3 py-2 text-[11px]">
      <div role="status" className="flex flex-wrap items-center gap-1.5">
        <Pause aria-hidden className="h-3.5 w-3.5 shrink-0" />
        <span className="flex-1 text-[var(--color-text-secondary)]">
          {t("workGraph.manualHoldNotice")}
        </span>
        <button
          type="button"
          className="agent-work-action disabled:cursor-wait disabled:opacity-50"
          disabled={resuming || confirmation !== null}
          onClick={() =>
            setConfirmation({ projectId, revision: hold.revision })
          }
        >
          {t("workGraph.resume")}
        </button>
      </div>
      <Modal
        open={confirmation?.projectId === projectId}
        title={t("workGraph.resume")}
        okText={t("workGraph.resume")}
        cancelText={t("common.cancel")}
        confirmLoading={resuming}
        cancelButtonProps={{ disabled: resuming }}
        closable={!resuming}
        mask={{ closable: !resuming }}
        keyboard={!resuming}
        onCancel={() => !resuming && setConfirmation(null)}
        onOk={async () => {
          if (!confirmation || resuming) return;
          try {
            await resume(confirmation.projectId, confirmation.revision);
          } catch (error) {
            if (error instanceof CreatorHttpError && error.status === 409) {
              message.warning(t("workGraph.resumeStale"));
            } else {
              message.error(t("workGraph.resumeFailed"));
            }
          } finally {
            setConfirmation(null);
          }
        }}
      >
        <p>{t("workGraph.resumeConfirm")}</p>
      </Modal>
    </div>
  );
}

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
    !node.manuallyHeld &&
    node.status === "running" &&
    node.progress != null &&
    Number.isFinite(node.progress) &&
    node.progress >= 0 &&
    node.progress <= 1
      ? taskProgressPercent(node.progress, node.kind)
      : null;
  const Icon = node.manuallyHeld
    ? Pause
    : node.status === "running"
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
          node.manuallyHeld
            ? "text-[var(--color-text-secondary)]"
            : node.status === "running"
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
          {t(
            node.manuallyHeld
              ? "workGraph.manuallyHeld"
              : `agentActivity.${stateKeys[node.status]}`,
          )}
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
  if (!graph || !graph.nodes.length) return null;
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
