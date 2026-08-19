import { useMemo, useState } from "react";
import { Button, message } from "antd";
import { CircleCheck, CircleX, Clock3, PlayCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { interruptCreator } from "@/api/creator";
import type {
  CreatorEvent,
  ProjectDocument,
  SpecialistRunView,
} from "@/contracts/creator";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { useWorkGraphStore } from "@/store/workGraphStore";
import { isTechnicalControlText } from "@/lib/creatorMessagePresentation";
import {
  creatorRoleLabel,
  creatorStatusLabel,
  creatorTargetLabel,
  creatorToolLabel,
} from "@/lib/creatorPresentation";
import {
  authorizationApprovalPayload,
  authorizationDetail,
  authorizationJumpTarget,
} from "./ExecutionAuthorizationCard";
import { navigateToLocator } from "@/routing/locators";
import i18n from "@/i18n";

type OriginRunStatus =
  | "running"
  | "waiting_confirm"
  | "waiting_review"
  | "done"
  | "partial"
  | "timeout"
  | "error"
  | "cancelled";

function runStatusMeta(status: OriginRunStatus): {
  label: string;
  tone: string;
} {
  const tones: Record<OriginRunStatus, string> = {
    running: "text-[var(--color-warning)] bg-[var(--color-warning-soft)]",
    waiting_confirm: "text-[var(--color-accent)] bg-[var(--color-accent-soft)]",
    waiting_review: "text-[var(--color-accent)] bg-[var(--color-accent-soft)]",
    done: "text-[var(--color-success)] bg-[var(--color-success-soft)]",
    partial: "text-[var(--color-warning)] bg-[var(--color-warning-soft)]",
    timeout: "text-[var(--color-warning)] bg-[var(--color-warning-soft)]",
    error: "text-[var(--color-danger)] bg-[var(--color-danger-soft)]",
    cancelled:
      "text-[var(--color-text-tertiary)] bg-[var(--color-bg-secondary)]",
  };
  const labels: Record<OriginRunStatus, string> = {
    running: i18n.t("agentEventFeed.executing"),
    waiting_confirm: i18n.t("agentEventFeed.waitingConfirm"),
    waiting_review: i18n.t("agentEventFeed.waitingReview"),
    done: i18n.t("agentEventFeed.completed"),
    partial: i18n.t("agentEventFeed.partialComplete"),
    timeout: i18n.t("agentEventFeed.backendWaiting"),
    error: i18n.t("agentEventFeed.failed"),
    cancelled: i18n.t("agentEventFeed.cancelled"),
  };
  return { label: labels[status], tone: tones[status] };
}

const NESTED_SUBAGENT_DETAIL_EVENTS = new Set([
  "subagent.message_delta",
  "subagent.message_completed",
  "subagent.tool_progress",
  "subagent.tool_started",
  "subagent.tool_completed",
]);

// Durable wake/yield bookkeeping is model-facing control state. The origin
// run card already communicates the corresponding user-facing status, so raw
// Runtime envelopes must never appear as conversation-like copy.
const INTERNAL_RUNTIME_EVENTS = new Set([
  "creator.yielded",
  "creator.woken",
  "runtime.work_update_appended",
]);

function originRunStatus(
  sessionStatus: string | undefined,
  runs: SpecialistRunView[],
  pendingAuthorizationCount: number,
): OriginRunStatus {
  if (sessionStatus === "CANCELLED") return "cancelled";
  if (
    pendingAuthorizationCount > 0 ||
    sessionStatus === "WAITING_EXECUTION_AUTH"
  )
    return "waiting_confirm";
  if (
    sessionStatus === "PENDING_REVIEW" ||
    (sessionStatus !== "IDLE" && runs.some(isReviewWaitingRun))
  )
    return "waiting_review";
  if (
    sessionStatus === "RUNNING" ||
    sessionStatus === "RESUMING" ||
    sessionStatus === "INTERRUPT_REQUESTED"
  )
    return "running";
  if (
    sessionStatus === "WAITING_RUNTIME" ||
    runs.some((run) => run.status === "WAITING_RUNTIME")
  )
    return "timeout";
  const succeeded = runs.some((run) => run.status === "SUCCEEDED");
  const failed = runs.some(
    (run) =>
      ["FAILED", "BLOCKED"].includes(run.status) && !isReviewWaitingRun(run),
  );
  if (succeeded && failed) return "partial";
  if (failed || sessionStatus === "ERROR") return "error";
  if (
    runs.length > 0 &&
    runs.every((run) => ["STALE", "CANCELLED"].includes(run.status))
  )
    return "cancelled";
  if (
    succeeded &&
    runs.every(
      (run) =>
        ["SUCCEEDED", "STALE", "CANCELLED"].includes(run.status) ||
        isReviewWaitingRun(run),
    )
  )
    return "done";
  return "running";
}

function isReviewWaitingRun(run: SpecialistRunView): boolean {
  return (
    run.metadata.waitingReview === true ||
    (run.status === "BLOCKED" &&
      /等待(?:用户)?审阅|审阅通过后/u.test(run.finalSummaryText || ""))
  );
}

function runStatusLabel(status: SpecialistRunView["status"]): string {
  return creatorStatusLabel(status);
}

function eventText(event: CreatorEvent): string {
  const data = event.data;
  for (const key of ["summary", "message", "text", "outcome"]) {
    const value = data[key];
    if (
      typeof value === "string" &&
      value.trim() &&
      !isTechnicalControlText(value)
    )
      return value.trim();
  }
  const reason = data.reason;
  if (typeof reason === "string") {
    const value = reason.trim();
    const isTechnicalSnakeCase = /^[a-z0-9]+(?:_[a-z0-9]+)+$/.test(value);
    if (value && !isTechnicalSnakeCase && !isTechnicalControlText(value))
      return value;
  }
  return "";
}

function EventCard({
  event,
  project,
}: {
  event: CreatorEvent;
  project: ProjectDocument | null;
}) {
  const data = event.data;
  const summary = eventText(event);
  if (event.type === "agent.plan") {
    const steps = Array.isArray(data.steps) ? data.steps.map(String) : [];
    return (
      <div
        data-agent-event-card={event.type}
        className="rounded-lg border border-[var(--color-accent)]/30 bg-[var(--color-accent-soft)] p-3 text-[11px] leading-5 text-[var(--color-text-primary)]"
      >
        <b className="block text-xs text-[var(--color-accent)]">
          {i18n.t("agentEventFeed.executionPlan")}
          {summary}
        </b>
        {steps.length > 0 && (
          <ol className="mt-1 list-decimal space-y-0.5 pl-4 text-[var(--color-text-secondary)]">
            {steps.map((step, index) => (
              <li key={index}>{step}</li>
            ))}
          </ol>
        )}
        {Boolean(data.scope) && (
          <p className="mt-1 text-[var(--color-text-tertiary)]">
            {i18n.t("agentEventFeed.scope")}
            {(Array.isArray(data.scope) ? data.scope : [data.scope])
              .map((ref) => creatorTargetLabel(String(ref), project))
              .join("、")}
          </p>
        )}
      </div>
    );
  }
  if (
    event.type === "agent.tool_started" ||
    event.type === "agent.tool_completed"
  ) {
    const completed = event.type === "agent.tool_completed";
    return (
      <div
        data-agent-event-card={event.type}
        className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-2 py-1.5 text-[10px]"
      >
        <div className="flex items-center justify-between gap-2">
          <span className="text-[var(--color-text-secondary)]">
            {creatorToolLabel(String(data.tool ?? ""))}
          </span>
          <span
            className={
              completed
                ? "text-[var(--color-success)]"
                : "text-[var(--color-warning)]"
            }
          >
            {completed
              ? i18n.t("agentEventFeed.done")
              : i18n.t("agentEventFeed.executing")}
          </span>
        </div>
        {summary && (
          <p className="mt-0.5 text-[var(--color-text-tertiary)]">{summary}</p>
        )}
      </div>
    );
  }
  if (event.type.startsWith("subagent.")) {
    const label = data.roleDisplayName
      ? String(data.roleDisplayName)
      : creatorRoleLabel(String(data.role ?? ""));
    const completed = event.type.endsWith("completed");
    const failed =
      event.type.endsWith("failed") || event.type.endsWith("stale");
    return (
      <div
        data-agent-event-card={event.type}
        className="rounded-lg border border-[var(--color-accent)]/30 bg-[var(--color-accent-soft)] px-2.5 py-1.5 text-[11px]"
      >
        <b
          className={
            failed
              ? "text-[var(--color-danger)]"
              : completed
              ? "text-[var(--color-success)]"
              : "text-[var(--color-accent)]"
          }
        >
          {completed ? "✓ " : failed ? "× " : "→ "}
          {label}
        </b>
        {summary && (
          <p className="mt-0.5 text-[var(--color-text-secondary)]">{summary}</p>
        )}
      </div>
    );
  }
  if (!summary || event.type === "agent.message_delta") return null;
  const error = event.type.includes("error") || event.type.includes("failed");
  const success =
    event.type.includes("completed") ||
    event.type.includes("applied") ||
    event.type.includes("available");
  return (
    <p
      data-agent-event-card={event.type}
      className={`text-[11px] font-medium ${
        error
          ? "text-[var(--color-danger)]"
          : success
          ? "text-[var(--color-success)]"
          : "text-[var(--color-text-secondary)]"
      }`}
    >
      {summary}
    </p>
  );
}

function WorkGraphSummaryChip() {
  // One-line production summary sourced from the derived work graph; the
  // full lane view lives in the workspace dropdown (WorkGraphPanel).
  const { t } = useTranslation();
  const graph = useWorkGraphStore((state) => state.graph);
  if (!graph || !graph.counts.total) return null;
  const done = graph.counts.done ?? 0;
  const running = graph.counts.running ?? 0;
  const failed = graph.counts.failed ?? 0;
  return (
    <span
      data-testid="work-graph-summary"
      className="text-[10px] font-normal text-[var(--color-text-tertiary)]"
    >
      {t("workGraph.progress", { done, total: graph.counts.total })}
      {running > 0 && ` · ${t("workGraph.parallel", { count: running })}`}
      {failed > 0 && (
        <span className="text-[var(--color-danger,#ef4444)]">
          {` · ${t("workGraph.failed", { count: failed })}`}
        </span>
      )}
    </span>
  );
}

export default function AgentEventFeed() {
  const { t } = useTranslation();
  const taskProjectId = useCreatorTaskViewStore((state) => state.projectId);
  const runs = useCreatorTaskViewStore((state) => state.runs);
  const tasks = useCreatorTaskViewStore((state) => state.tasks);
  const events = useCreatorSessionStore((state) => state.events);
  const session = useCreatorSessionStore((state) => state.session);
  const project = useProjectSnapshotStore((state) => state.project);
  const projectId = taskProjectId ?? session?.projectId ?? null;
  const authorizations = useExecutionAuthorizationStore((state) => state.items);
  const approve = useExecutionAuthorizationStore((state) => state.approve);
  const decline = useExecutionAuthorizationStore((state) => state.decline);
  const [busy, setBusy] = useState(false);
  const pendingAuthorizations = authorizations.filter(
    (authorization) => authorization.status === "PENDING",
  );
  const status = originRunStatus(
    session?.status,
    runs,
    pendingAuthorizations.length,
  );
  const meta = runStatusMeta(status);
  // The DAG info tab (WorkGraphPanel) owns production tracking whenever
  // the derived work graph has nodes; the flat card then only surfaces
  // interactive states — pending authorization, failures, or a live run
  // that still needs its terminate control.
  const workGraphActive = useWorkGraphStore((state) =>
    Boolean(state.graph && state.graph.nodes.length > 0),
  );
  const failedTargetRuns = runs.flatMap((run) => {
    if (!["FAILED", "BLOCKED"].includes(run.status) || isReviewWaitingRun(run))
      return [];
    const targetRefs = run.targetRefs.filter(
      (targetRef) =>
        targetRef.startsWith("element:") || targetRef.startsWith("timeline:"),
    );
    return targetRefs.length > 0 ? [{ run, targetRefs }] : [];
  });
  const visibleEvents = useMemo(
    () =>
      events
        .filter(
          (event) =>
            ![
              "message.appended",
              "message.completed",
              "agent.message_delta",
              "agent.tool_progress",
              "agent.plan",
              "agent.tool_started",
              "agent.tool_completed",
            ].includes(event.type) &&
            !NESTED_SUBAGENT_DETAIL_EVENTS.has(event.type) &&
            // Lifecycle events that carry a parent action belong to the unified
            // delegate_to_agent card.  Rendering them again in the global feed made
            // one delegation appear as two or three separate "→ Agent" rows.
            !(
              event.type.startsWith("subagent.") &&
              typeof event.data.parentActionId === "string" &&
              event.data.parentActionId
            ) &&
            !INTERNAL_RUNTIME_EVENTS.has(event.type),
        )
        .slice(-12),
    [events],
  );
  const authorization = pendingAuthorizations[0];
  // With an active work graph the DAG info tab owns production tracking
  // end to end — failed nodes carry their own Retry there and the dock
  // composer owns the stop control — so the flat card only survives for
  // a pending execution authorization, which has no other home.
  const showProductionCard = !workGraphActive || Boolean(authorization);
  if (
    !runs.length &&
    !tasks.length &&
    !visibleEvents.length &&
    !authorization &&
    session?.status !== "CANCELLED"
  )
    return null;

  const continueRun = async () => {
    if (!authorization) return;
    setBusy(true);
    try {
      await approve(
        authorization.id,
        authorizationApprovalPayload(authorization),
      );
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const cancelRun = async () => {
    setBusy(true);
    try {
      if (authorization)
        await decline(authorization.id, authorization.authorizationToken);
      else if (projectId) await interruptCreator(projectId);
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-origin-run-block className="space-y-2">
      {showProductionCard && (
        <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/60 p-3">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-primary)]">
              <PlayCircle className="h-3.5 w-3.5 text-[var(--color-accent)]" />
              {t("agentEventFeed.productionFlow")}
            </span>
            <WorkGraphSummaryChip />
            <span className="flex items-center gap-1.5">
              <span
                className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${meta.tone}`}
              >
                {status === "running" && (
                  <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current align-middle" />
                )}
                {meta.label}
              </span>
              {(status === "running" || status === "waiting_confirm") && (
                <button
                  onClick={() => void cancelRun()}
                  className="text-[10px] text-[var(--color-text-tertiary)] hover:text-[var(--color-danger)]"
                >
                  {t("agentEventFeed.terminate")}
                </button>
              )}
            </span>
          </div>

          {!workGraphActive && runs.length > 0 && (
            <ul className="mt-2 space-y-1">
              {runs.slice(-8).map((run) => (
                <li
                  key={run.id}
                  className="flex items-start gap-1.5 text-[11px] leading-4 text-[var(--color-text-secondary)]"
                >
                  {run.status === "SUCCEEDED" ? (
                    <CircleCheck className="mt-0.5 h-3 w-3 shrink-0 text-[var(--color-success)]" />
                  ) : isReviewWaitingRun(run) ? (
                    <Clock3 className="mt-0.5 h-3 w-3 shrink-0 text-[var(--color-accent)]" />
                  ) : ["FAILED", "BLOCKED"].includes(run.status) ? (
                    <CircleX className="mt-0.5 h-3 w-3 shrink-0 text-[var(--color-danger)]" />
                  ) : (
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[var(--color-text-tertiary)]" />
                  )}
                  <span className="min-w-0">
                    {run.displayName} ·{" "}
                    {run.targetRefs
                      .map((ref) => creatorTargetLabel(ref, project))
                      .join(t("agentEventFeed.listSeparator")) ||
                      t("agentEventFeed.currentProject")}{" "}
                    ·{" "}
                    {isReviewWaitingRun(run)
                      ? t("agentEventFeed.waitingReview")
                      : runStatusLabel(run.status)}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {failedTargetRuns.length > 0 && (
            <div className="mt-2 rounded-md border border-[var(--color-danger)]/25 bg-[var(--color-danger-soft)] p-2 text-[11px] leading-4">
              <b className="text-[var(--color-danger)]">
                {failedTargetRuns.length}{" "}
                {t("agentEventFeed.specialistsFailed")}
              </b>
              <ul className="mt-1 space-y-0.5 text-[var(--color-text-secondary)]">
                {failedTargetRuns.slice(0, 3).map(({ run, targetRefs }) => (
                  <li key={run.id} className="truncate">
                    {targetRefs
                      .map((ref) => creatorTargetLabel(ref, project))
                      .join(t("agentEventFeed.listSeparator"))}
                    {t("agentEventFeed.summarySeparator")}
                    {run.finalSummaryText || creatorStatusLabel(run.status)}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {status === "waiting_confirm" && authorization && (
            <div className="mt-2 rounded-md border border-[var(--color-accent)]/30 bg-[var(--color-accent-soft)] p-2.5">
              <p className="text-[11px] font-medium leading-4 text-[var(--color-text-primary)]">
                {authorizationDetail(authorization, project)}
              </p>
              <div className="mt-2 flex items-center gap-2">
                <Button
                  type="primary"
                  size="small"
                  loading={busy}
                  onClick={() => void continueRun()}
                  className="!h-6 !text-[11px] !font-semibold"
                >
                  {t("agentEventFeed.continue")}
                </Button>
                <Button
                  size="small"
                  disabled={busy}
                  onClick={() => void cancelRun()}
                  className="!h-6 !text-[11px]"
                >
                  {t("agentEventFeed.cancel")}
                </Button>
                {projectId &&
                  (() => {
                    const jumpTarget = authorizationJumpTarget(
                      authorization,
                      project,
                    );
                    if (!jumpTarget) return null;
                    return (
                      <Button
                        size="small"
                        disabled={busy}
                        title={t("agentEventFeed.jumpToPrompt")}
                        onClick={() =>
                          navigateToLocator(projectId, jumpTarget.locator, {
                            review: true,
                            field: jumpTarget.field,
                            description: t(
                              "agentEventFeed.productionConfirmOrView",
                            ),
                          })
                        }
                        className="!h-6 !text-[11px]"
                      >
                        {t("agentEventFeed.view")}
                      </Button>
                    );
                  })()}
              </div>
            </div>
          )}
        </div>
      )}

      {visibleEvents.map((event) => (
        <EventCard key={event.eventId} event={event} project={project} />
      ))}
    </div>
  );
}
