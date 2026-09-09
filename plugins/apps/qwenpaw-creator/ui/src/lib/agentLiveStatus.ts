import type {
  AgentStatusBarView,
  CreatorSessionView,
  CreatorMessage,
  ProjectDocument,
  TaskView,
} from "@/contracts/creator";
import type { SubagentActivity } from "@/store/creatorSessionStore";
import type { ToolCallPresentation } from "@/lib/creatorMessagePresentation";
import {
  creatorRoleLabel,
  creatorStatusLabel,
  creatorTargetLabel,
  getRoleRunningLabel,
  getToolRunningLabel,
  taskKindLabel,
} from "./creatorPresentation";
import { taskProgressPercent } from "./taskPresentation";
import i18n from "@/i18n";

const WORKING_SESSION_STATUSES = new Set([
  "RUNNING",
  "RESUMING",
  "WAITING_RUNTIME",
  "INTERRUPT_REQUESTED",
]);

const ACTIVE_TASK_STATUSES = new Set(["QUEUED", "RUNNING"]);

export type AgentLiveState = "working" | "stopping" | "waiting" | "idle";
export type AgentIndicatorPhase =
  | "running"
  | "waiting"
  | "attention"
  | "completed"
  | "idle";

export interface AgentLiveStatus {
  state: AgentLiveState;
  /** Presentation only: `working` also includes queued or paused operations. */
  indicatorPhase: AgentIndicatorPhase;
  label: string;
  /** 0-100 only for quantifiable progress (e.g. ingestion); null hides bar. */
  progressPercent: number | null;
}

type ActivityLifecycle = Pick<
  SubagentActivity,
  "status" | "completed" | "waitingReview" | "terminalKind" | "modelRetry"
>;

/** Pass activity only for a delegation card, not its individual child tools. */
export function toolActivityPhase(
  tool: { status: string; executing?: boolean },
  activity?: ActivityLifecycle,
): AgentIndicatorPhase {
  if (activity) {
    if (activity.waitingReview) return "attention";
    if (activity.modelRetry && !activity.completed) return "waiting";
    if (activity.completed) {
      if (
        activity.terminalKind === "SUCCESS" ||
        activity.status === "SUCCEEDED"
      )
        return "completed";
      if (
        ["FAILED", "BLOCKED", "STALE"].includes(
          activity.terminalKind ?? activity.status ?? "",
        )
      )
        return "attention";
      return "idle";
    }
    if (
      ["WAITING_AUTHORIZATION", "BLOCKED", "FAILED", "STALE"].includes(
        activity.status ?? "",
      )
    )
      return "attention";
    if (
      ["QUEUED", "QUEUED_CAPACITY", "WAITING_RUNTIME"].includes(
        activity.status ?? "",
      )
    )
      return "waiting";
    if (activity.status === "RUNNING_MODEL") return "running";
    if (activity.status === "SUCCEEDED") return "completed";
    if (activity.status === "CANCELLED") return "idle";
    // A delegation's accepted tool result is not its specialist's completion.
    return tool.status === "started" && tool.executing === true
      ? "running"
      : "waiting";
  }
  if (["succeeded", "SUCCEEDED", "done"].includes(tool.status))
    return "completed";
  if (
    [
      "failed",
      "FAILED",
      "waiting_review",
      "WAITING_AUTHORIZATION",
      "BLOCKED",
      "STALE",
    ].includes(tool.status)
  )
    return "attention";
  if (["cancelled", "CANCELLED", "unknown"].includes(tool.status))
    return "idle";
  if (["RUNNING", "RUNNING_MODEL"].includes(tool.status)) return "running";
  return tool.status === "started" && tool.executing === true
    ? "running"
    : "waiting";
}

interface LiveOperation {
  label: string;
  indicatorPhase: AgentIndicatorPhase;
}

function activityPausesTools(activity: SubagentActivity): boolean {
  return (
    Boolean(activity.waitingReview) ||
    Boolean(activity.modelRetry) ||
    [
      "QUEUED",
      "QUEUED_CAPACITY",
      "WAITING_RUNTIME",
      "WAITING_AUTHORIZATION",
      "BLOCKED",
      "STALE",
      "FAILED",
      "CANCELLED",
      "SUCCEEDED",
    ].includes(activity.status ?? "")
  );
}

export interface AgentLiveStatusInput {
  session: CreatorSessionView | null;
  messages?: CreatorMessage[];
  agentStatusBar: AgentStatusBarView | null;
  stopping: boolean;
  hasQueuedInput: boolean;
  isReplaying: boolean;
  subagentActivities: Record<string, SubagentActivity>;
  toolCalls: ToolCallPresentation[];
  tasks: TaskView[];
  project: ProjectDocument | null;
  /** Current project's actual undecided review units, including media reviews. */
  pendingReviewCount?: number;
  /** Latest model throttling retry, while the run keeps going. */
  rateLimitRetry?: {
    attempt: number;
    maxAttempts: number;
    reason?: string;
  } | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function toolTargetRef(
  args: Record<string, unknown> | undefined,
  fallbackRefs: string[] = [],
): string {
  const direct = args?.targetRef ?? args?.target_ref;
  if (typeof direct === "string" && direct) return direct;
  return fallbackRefs[0] ?? "";
}

// Truncate long target names so trailing keywords ("storyboard") stay visible.
const MAX_TARGET_NAME_LENGTH = 10;

function clampTargetName(name: string): string {
  return name.length > MAX_TARGET_NAME_LENGTH
    ? `${name.slice(0, MAX_TARGET_NAME_LENGTH - 1)}…`
    : name;
}

/** Generic fallback copy = unresolved; avoid "timeline content" storyboard. */
function resolvedTargetName(
  ref: string,
  project: ProjectDocument | null,
): string | null {
  if (!ref) return null;
  const label = creatorTargetLabel(ref, project);
  const fallbacks = new Set([
    i18n.t("presentation.targets.currentProject"),
    i18n.t("presentation.targets.timelineContent"),
    i18n.t("presentation.targets.currentSource"),
    i18n.t("presentation.targets.sourceVersion"),
    i18n.t("presentation.targets.genResult"),
    i18n.t("presentation.targets.sourceFile"),
  ]);
  return fallbacks.has(label) ? null : clampTargetName(label);
}

function imageGenerationLabel(
  ref: string,
  project: ProjectDocument | null,
): string {
  const name = resolvedTargetName(ref, project);
  if (ref.startsWith("element:") || ref.startsWith("timeline:"))
    return name
      ? i18n.t("liveStatus.generatingStoryboardOf", { name })
      : i18n.t("liveStatus.generatingStoryboard");
  if (ref.startsWith("asset") || ref.startsWith("artifact"))
    return name
      ? i18n.t("liveStatus.generatingVisualOf", { name })
      : i18n.t("liveStatus.generatingVisual");
  return i18n.t("liveStatus.generatingImage");
}

function r2vGenerationLabel(
  ref: string,
  project: ProjectDocument | null,
): string {
  const name = resolvedTargetName(ref, project);
  return name
    ? i18n.t("liveStatus.generatingVideoOf", { name })
    : i18n.t("liveStatus.generatingVideo");
}

function runningToolLabel(
  tool: string,
  args: Record<string, unknown> | undefined,
  fallbackRefs: string[],
  project: ProjectDocument | null,
): string | null {
  if (tool === "image_generation")
    return imageGenerationLabel(toolTargetRef(args, fallbackRefs), project);
  if (tool === "r2v_generation")
    return r2vGenerationLabel(toolTargetRef(args, fallbackRefs), project);
  return getToolRunningLabel(tool, args);
}

function subagentRoleName(activity: SubagentActivity): string {
  return activity.roleDisplayName || creatorRoleLabel(activity.role);
}

function roleWorkingLabel(activity: SubagentActivity): string {
  if (activity.modelRetry && !activity.completed)
    return `${subagentRoleName(activity)} · ${i18n.t(
      `agentRetry.${activity.modelRetry.reason ?? "rate_limit"}`,
    )}`;
  if (activity.waitingReview)
    return `${subagentRoleName(activity)} · ${creatorStatusLabel(
      "PENDING_REVIEW",
    )}`;
  if (activity.status && activity.status !== "RUNNING_MODEL")
    return `${subagentRoleName(activity)} · ${creatorStatusLabel(
      activity.status,
    )}`;
  const runningLabel = getRoleRunningLabel(activity.role);
  if (runningLabel) return runningLabel;
  return i18n.t("liveStatus.roleWorking", { name: subagentRoleName(activity) });
}

function activeSubagentToolLabel(
  activities: Record<string, SubagentActivity>,
  project: ProjectDocument | null,
): LiveOperation | null {
  // Internal project tools are meaningless to users; skip them to avoid
  // vague states like "modifying project".
  const internalProjectTools = new Set([
    "jq_project",
    "read_project",
    "read_project_file",
    "elements_at",
  ]);
  let latestSeq = -1;
  let latestLabel: string | null = null;
  Object.values(activities).forEach((activity) => {
    if (activity.completed || activityPausesTools(activity)) return;
    Object.values(activity.tools).forEach((tool) => {
      if (
        tool.status !== "started" ||
        tool.executing !== true ||
        tool.firstEventSeq <= latestSeq
      )
        return;
      if (internalProjectTools.has(tool.tool)) return;
      const label = runningToolLabel(
        tool.tool,
        tool.arguments,
        activity.targetRefs,
        project,
      );
      if (!label) return;
      latestSeq = tool.firstEventSeq;
      latestLabel = label;
    });
  });
  return latestLabel ? { label: latestLabel, indicatorPhase: "running" } : null;
}

function activeMainToolLabel(
  toolCalls: ToolCallPresentation[],
  activities: Record<string, SubagentActivity>,
  project: ProjectDocument | null,
): LiveOperation | null {
  // Internal project tools are meaningless to users; skip them to avoid
  // vague states like "modifying project".
  const internalProjectTools = new Set([
    "jq_project",
    "read_project",
    "read_project_file",
    "elements_at",
  ]);
  for (let index = toolCalls.length - 1; index >= 0; index -= 1) {
    const call = toolCalls[index];
    if (call.status !== "started") continue;
    if (call.executing !== true) continue;
    if (call.tool === "delegate_to_agent") {
      const activity = activities[call.actionId];
      if (activity && !activity.completed) {
        if (activityPausesTools(activity)) continue;
        return {
          label: roleWorkingLabel(activity),
          indicatorPhase: toolActivityPhase(call, activity),
        };
      }
      // Subagent already finished (incl. cancelled) → defer to the activity
      // card, which renders the terminal state. Returning null here avoids
      // showing "正在安排" for a delegation that has already ended, which
      // would contradict the card's "已取消/已完成" status.
      if (activity && activity.completed) return null;
      // No subagent activity yet → the delegation was just issued; show a
      // brief "正在安排" until the specialist reports in.
      const args = isRecord(call.arguments) ? call.arguments : undefined;
      const role = typeof args?.role === "string" ? args.role : "";
      return {
        label: role
          ? i18n.t("liveStatus.arrangingRole", { name: creatorRoleLabel(role) })
          : i18n.t("liveStatus.assigningTask"),
        indicatorPhase: "running",
      };
    }
    if (internalProjectTools.has(call.tool)) continue;
    const label = runningToolLabel(call.tool, call.arguments, [], project);
    if (label) return { label, indicatorPhase: "running" };
  }
  return null;
}

function activeTask(tasks: TaskView[]): TaskView | null {
  const running = tasks.filter((task) => ACTIVE_TASK_STATUSES.has(task.status));
  if (running.length === 0) return null;
  return [...running].sort((left, right) =>
    (left.updatedAt ?? "").localeCompare(right.updatedAt ?? ""),
  )[running.length - 1];
}

function preparingToolOperation(
  toolCalls: ToolCallPresentation[],
  activities: Record<string, SubagentActivity>,
): LiveOperation | null {
  const preparingMain = toolCalls.some(
    (call) =>
      call.status === "started" &&
      call.executing !== true &&
      !(call.tool === "delegate_to_agent" && activities[call.actionId]),
  );
  const preparingChild = Object.values(activities).some(
    (activity) =>
      !activity.completed &&
      !activityPausesTools(activity) &&
      Object.values(activity.tools).some(
        (tool) => tool.status === "started" && tool.executing !== true,
      ),
  );
  return preparingMain || preparingChild
    ? { label: i18n.t("agentActivity.preparing"), indicatorPhase: "waiting" }
    : null;
}

function activeTaskLabel(
  task: TaskView,
  project: ProjectDocument | null,
): string {
  const name = resolvedTargetName(task.targetRef, project);
  const kind = taskKindLabel(task.kind);
  if (task.status === "QUEUED")
    return `${kind} · ${creatorStatusLabel("QUEUED")}`;
  return name
    ? i18n.t("liveStatus.taskKindWorking", { name, kind })
    : i18n.t("liveStatus.kindWorking", { kind });
}

function firstIncompleteActivity(
  activities: Record<string, SubagentActivity>,
): SubagentActivity | null {
  const pending = Object.values(activities)
    .filter((activity) => !activity.completed)
    .sort((left, right) => right.firstEventSeq - left.firstEventSeq);
  return pending[0] ?? null;
}

export function deriveAgentLiveStatus(
  input: AgentLiveStatusInput,
): AgentLiveStatus {
  const {
    session,
    agentStatusBar,
    stopping,
    hasQueuedInput: hasOptimisticInput,
    messages = [],
    isReplaying,
    subagentActivities,
    toolCalls,
    tasks,
    project,
    rateLimitRetry,
    pendingReviewCount = 0,
  } = input;
  // Atomic project creation persists the first user message before the
  // scheduler enters RUNNING. After refresh, the optimistic queue is empty.
  // Only unconsumed user messages count; assistant/tool history does not.
  const hasPersistedInput =
    session?.status === "IDLE" &&
    (Boolean(
      session.activeGoalId &&
        session.lastMessageSeq === 1 &&
        session.lastConsumedMessageSeq === 0,
    ) ||
      messages.some(
        (message) =>
          message.role === "user" &&
          message.messageSeq > session.lastConsumedMessageSeq,
      ));
  const hasQueuedInput = hasOptimisticInput || hasPersistedInput;

  if (stopping || session?.status === "INTERRUPT_REQUESTED")
    return {
      state: "stopping",
      indicatorPhase: "waiting",
      label: i18n.t("liveStatus.stopping"),
      progressPercent: null,
    };

  // During replay show loading and suppress the "working" animation.
  if (isReplaying)
    return {
      state: "idle",
      indicatorPhase: "waiting",
      label: i18n.t("liveStatus.loading"),
      progressPercent: null,
    };

  // A newly sent instruction can precede the SSE transition out of a terminal
  // session. Its optimistic state must not inherit the previous run's result.
  if (
    hasQueuedInput &&
    session &&
    ["IDLE", "ERROR", "CANCELLED"].includes(session.status) &&
    pendingReviewCount === 0 &&
    !firstIncompleteActivity(subagentActivities) &&
    !activeTask(tasks)
  )
    return {
      state: "working",
      indicatorPhase: "waiting",
      label: i18n.t("liveStatus.commandSent"),
      progressPercent: null,
    };

  // ERROR is terminal with a specific error message to surface.
  if (session?.status === "ERROR")
    return {
      state: "idle",
      indicatorPhase: "attention",
      label: i18n.t("liveStatus.executionFailed"),
      progressPercent: null,
    };

  // User-action states take priority over unrelated concurrent work.
  if (session?.status === "WAITING_USER_INPUT")
    return {
      state: "waiting",
      indicatorPhase: "attention",
      label: i18n.t("liveStatus.waitingUserInput"),
      progressPercent: null,
    };
  if (
    session?.status === "WAITING_EXECUTION_AUTH" ||
    toolCalls.some(
      (call) => call.status === "started" && call.waitingAuthorization,
    )
  )
    return {
      state: "waiting",
      indicatorPhase: "attention",
      label: i18n.t("liveStatus.waitingExecAuth"),
      progressPercent: null,
    };
  // Detached media publication may leave the main session IDLE. The review
  // record is the authority for its undecided result until the user acts.
  if (session?.status === "PENDING_REVIEW" || pendingReviewCount > 0)
    return {
      state: "waiting",
      indicatorPhase: "attention",
      label: i18n.t("liveStatus.waitingReview"),
      progressPercent: null,
    };

  // These are current unfinished lifecycles. Completed review history must
  // not override a later mainline run after the user has already reviewed it.
  const attentionActivity = Object.values(subagentActivities)
    .filter(
      (activity) =>
        !activity.completed &&
        (activity.waitingReview || activity.status === "WAITING_AUTHORIZATION"),
    )
    .sort((left, right) => right.firstEventSeq - left.firstEventSeq)[0];
  if (attentionActivity && session?.status !== "CANCELLED")
    return {
      state: "waiting",
      indicatorPhase: "attention",
      label: roleWorkingLabel(attentionActivity),
      progressPercent: null,
    };

  // CANCELLED is terminal. IDLE remains actionable: an optimistic
  // queued message must be visible while the backend transitions to RUNNING.
  // Async delegations and runtime tasks outlive the mainline run, so an
  // IDLE session with live background work keeps the working indicator —
  // otherwise the project looks stalled while a specialist still edits.
  const hasActiveBackgroundWork =
    Object.values(subagentActivities).some((activity) => !activity.completed) ||
    tasks.some((task) => ACTIVE_TASK_STATUSES.has(task.status)) ||
    (agentStatusBar?.activity?.runningTaskCount ?? 0) > 0;
  if (
    session?.status === "CANCELLED" ||
    (session?.status === "IDLE" && !hasQueuedInput && !hasActiveBackgroundWork)
  )
    return {
      state: "idle",
      indicatorPhase: "idle",
      label: i18n.t("liveStatus.idle"),
      progressPercent: null,
    };

  const runningTask = activeTask(tasks);
  const working =
    (agentStatusBar?.activity?.runningTaskCount ?? 0) > 0 ||
    Boolean(session && WORKING_SESSION_STATUSES.has(session.status)) ||
    Boolean(runningTask) ||
    Object.values(subagentActivities).some((activity) => !activity.completed) ||
    hasQueuedInput;

  if (working) {
    const operation: LiveOperation | null =
      (rateLimitRetry
        ? {
            label: i18n.t(
              rateLimitRetry.reason && rateLimitRetry.reason !== "rate_limit"
                ? "liveStatus.modelRetrying"
                : "liveStatus.rateLimitRetrying",
              {
                attempt: rateLimitRetry.attempt,
                max: rateLimitRetry.maxAttempts,
              },
            ),
            indicatorPhase: "waiting" as const,
          }
        : null) ??
      activeSubagentToolLabel(subagentActivities, project) ??
      activeMainToolLabel(toolCalls, subagentActivities, project);
    // A percentage belongs to the task actually named by this row. Project
    // milestone counts can describe an earlier run and belong in the overview.
    const labelledTask = operation == null ? runningTask : null;
    const progressPercent =
      labelledTask?.status === "RUNNING" &&
      labelledTask.progress != null &&
      Number.isFinite(labelledTask.progress) &&
      labelledTask.progress >= 0 &&
      labelledTask.progress <= 1
        ? taskProgressPercent(labelledTask.progress)
        : null;
    const activity = firstIncompleteActivity(subagentActivities);
    const preparing = preparingToolOperation(toolCalls, subagentActivities);
    const currentOperation =
      operation ??
      (runningTask
        ? {
            label: activeTaskLabel(runningTask, project),
            indicatorPhase:
              runningTask.status === "RUNNING"
                ? ("running" as const)
                : ("waiting" as const),
          }
        : null) ??
      preparing ??
      (activity
        ? {
            label: roleWorkingLabel(activity),
            indicatorPhase: toolActivityPhase({ status: "started" }, activity),
          }
        : null) ??
      (session?.status === "WAITING_RUNTIME"
        ? {
            label: creatorStatusLabel("WAITING_RUNTIME"),
            indicatorPhase: "waiting" as const,
          }
        : null);
    const label =
      currentOperation?.label ??
      // Backend progress.label is also its latestMilestone, including old
      // terminal results. It has no run identity proving current ownership.
      (hasQueuedInput && session?.status !== "RUNNING"
        ? i18n.t("liveStatus.commandSent")
        : i18n.t("agent.processing"));
    return {
      state: "working",
      indicatorPhase:
        currentOperation?.indicatorPhase ??
        (session?.status === "RUNNING" ? "running" : "waiting"),
      label,
      progressPercent:
        progressPercent != null && progressPercent < 100
          ? progressPercent
          : null,
    };
  }

  return {
    state: "idle",
    indicatorPhase: "idle",
    label: i18n.t("liveStatus.idle"),
    progressPercent: null,
  };
}
