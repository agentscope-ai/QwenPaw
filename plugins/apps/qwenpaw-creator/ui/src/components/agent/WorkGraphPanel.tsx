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
import ProductionStageControl from "@/components/creator/ProductionStageControl";
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
  const [errorExpanded, setErrorExpanded] = useState(false);
  const actionLabel = t(
    `workGraph.actions.${node.kind}.${
      node.status === "failed" ? "retry" : "generate"
    }`,
  );
  const showAction =
    node.dispatchable &&
    node.missing.length === 0 &&
    ["failed", "ready", "stale"].includes(node.status);
  // A prompt-sync gate is invisible otherwise: the node is gated, shows
  // "waiting for deps", and the confirm action only exists inside the R2V
  // workbench regenerate flow, so users hit a dead end. Offer a direct
  // entry to the workbench where the sync banner lives.
  const promptSyncGated =
    node.status === "gated" && Boolean(node.promptSyncRequired);
  // The script gate shares the generic "waiting for deps" wording with
  // ordinary dependency waits; naming it points first-time users at the
  // confirm button instead of leaving them without a next action.
  const scriptGated =
    node.status === "gated" && project?.settings.production_stage === "script";
  const errorText = node.status === "failed" ? (node.error ?? "").trim() : "";
  // A skipped automatic review leaves a delivered artifact that looks
  // reviewed-but-clean; naming the environment fault (and the override
  // variable) is the only actionable next step for the user.
  const reviewSkip = node.reviewSkip ?? null;
  const reviewSkipText = reviewSkip
    ? t("workGraph.reviewSkipped", {
        reason: t(`workGraph.reviewSkipReasons.${reviewSkip.reason}`, {
          defaultValue: reviewSkip.reason,
        }),
        hint: reviewSkip.hint,
      })
    : "";
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
              : scriptGated
              ? "agentActivity.waitingScriptConfirm"
              : `agentActivity.${stateKeys[node.status]}`,
          )}
          {percent != null && ` · ${percent}%`}
        </span>
        {reviewSkipText && (
          <span
            role="status"
            data-work-node-review-skip
            className="mt-0.5 block text-[11px] text-[var(--color-text-tertiary)]"
          >
            {reviewSkipText}
          </span>
        )}
        {errorText && (
          <span
            role="status"
            data-work-node-error
            title={errorText}
            onClick={(event) => {
              // Expand/collapse the full reason instead of navigating away.
              event.stopPropagation();
              setErrorExpanded((expanded) => !expanded);
            }}
            className={`mt-0.5 block cursor-pointer text-[11px] text-[var(--color-danger)] ${
              errorExpanded ? "whitespace-pre-line" : "truncate"
            }`}
          >
            {errorText}
          </span>
        )}
      </button>
      {promptSyncGated && (
        <button
          type="button"
          aria-label={`${t("workGraph.actions.promptSync")} · ${publicLabel}`}
          className="agent-work-action"
          onClick={() =>
            // The confirmation banner lives in the Element workbench, not the
            // plan timeline: force the element route (keeping the timeline
            // scope so non-primary episodes resolve too).
            navigateToLocator(projectId, {
              ...(node.locator ?? {}),
              page: "element",
              ...(node.timelineId ? { timelineId: node.timelineId } : {}),
            })
          }
        >
          {t("workGraph.actions.promptSync")}
        </button>
      )}
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
  const { t } = useTranslation();
  const graph = useWorkGraphStore((state) =>
    state.projectId === projectId ? state.graph : null,
  );
  const refresh = useWorkGraphStore((state) => state.refresh);
  const project = useProjectSnapshotStore((state) =>
    state.projectId === projectId ? state.project : null,
  );
  useEffect(() => {
    void refresh(projectId);
  }, [projectId, refresh]);
  if (!graph || !graph.nodes.length) return null;
  const scriptPending =
    project?.settings.production_stage === "script" &&
    graph.nodes.some((node) => node.status === "gated");
  return (
    <div data-testid="work-graph-panel">
      {scriptPending && (
        <div
          role="status"
          data-script-gate-notice
          className="mb-2 flex flex-wrap items-center gap-1.5 rounded border border-[var(--color-border)] px-2 py-1.5 text-[11px] text-[var(--color-text-secondary)]"
        >
          <span className="flex-1">{t("workGraph.scriptGateNotice")}</span>
          <ProductionStageControl projectId={projectId} />
        </div>
      )}
      <ul className="space-y-1">
        {graph.nodes.map((node) => (
          <NodeRow key={node.id} node={node} projectId={projectId} />
        ))}
      </ul>
    </div>
  );
}
