import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useShallow } from "zustand/react/shallow";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { useLaunchUploadStore } from "@/store/launchUploadStore";
import {
  deriveAgentLiveStatus,
  type AgentIndicatorPhase,
} from "@/lib/agentLiveStatus";
import { toolCallPresentations } from "@/lib/creatorMessagePresentation";
import { pendingUserReviewOperations } from "@/lib/fileProjectReviewDecisions";

export interface AgentWorkingState {
  working: boolean;
  hint: string | null;
  state:
    | "working"
    | "preparing"
    | "waiting"
    | "stopping"
    | "stopped"
    | "idle"
    | "loading"
    | "reconnecting"
    | "error";
  indicatorPhase: AgentIndicatorPhase;
}

/** The workspace and conversation share public activity labels. Never show
 * raw backend milestones or specialist instructions in an empty panel. */
export function useAgentWorkingState(projectId?: string): AgentWorkingState {
  const { t } = useTranslation();
  const snapshot = useProjectSnapshotStore(
    useShallow((state) => ({
      projectId: state.projectId,
      project: state.project,
    })),
  );
  const id = projectId ?? snapshot.projectId;
  const launch = useLaunchUploadStore(
    useShallow((state) => ({
      projectId: state.projectId,
      phase: state.phase,
      done: state.done,
      total: state.total,
    })),
  );
  const sessionState = useCreatorSessionStore(
    useShallow((state) => ({
      projectId: state.projectId,
      session: state.session,
      agentStatusBar: state.agentStatusBar,
      queuedUi: state.queuedUi,
      subagentActivities: state.subagentActivities,
      messages: state.messages,
      events: state.events,
      stopping: state.stopping,
      isReplaying: state.isReplaying,
      loading: state.loading,
      connectionState: state.connectionState,
      rateLimitRetry: state.rateLimitRetry,
    })),
  );
  const tasks = useCreatorTaskViewStore((state) =>
    state.projectId === id ? state.tasks : null,
  );
  const pendingReviewCount = useFileProjectReviewStore((state) =>
    state.projectId === id
      ? state.reviews.reduce(
          (count, review) =>
            count +
            (review.status === "PENDING"
              ? pendingUserReviewOperations(review).length
              : 0),
          0,
        )
      : 0,
  );
  const toolCalls = useMemo(
    () =>
      sessionState.projectId === id
        ? toolCallPresentations(sessionState.messages, sessionState.events)
        : [],
    [id, sessionState.projectId, sessionState.messages, sessionState.events],
  );

  return useMemo(() => {
    const idle: AgentWorkingState = {
      working: false,
      hint: null,
      state: "idle",
      indicatorPhase: "idle",
    };
    if (!id) return idle;
    // Attachment preparation starts before the first Agent message and can
    // precede session hydration. The scoped launch store owns that interval.
    if (
      launch.projectId === id &&
      ["uploading", "messaging"].includes(launch.phase)
    )
      return {
        working: true,
        state: "preparing",
        indicatorPhase: "waiting",
        hint:
          launch.phase === "uploading"
            ? t("launchUpload.uploading", {
                done: launch.done,
                total: launch.total,
              })
            : t("launchUpload.messaging"),
      };
    if (sessionState.projectId !== id) return idle;
    const hasQueuedInput = sessionState.queuedUi.some(
      (item) => item.state !== "failed",
    );
    if (
      (sessionState.loading || sessionState.isReplaying) &&
      !sessionState.stopping &&
      sessionState.session?.status !== "INTERRUPT_REQUESTED"
    )
      return hasQueuedInput
        ? {
            working: true,
            state: "working",
            hint: t("liveStatus.commandSent"),
            indicatorPhase: "waiting",
          }
        : {
            ...idle,
            state: "loading",
            hint: t("liveStatus.loading"),
            indicatorPhase: "waiting",
          };
    const live = deriveAgentLiveStatus({
      session: sessionState.session,
      messages: sessionState.messages,
      agentStatusBar: sessionState.agentStatusBar,
      stopping: sessionState.stopping,
      hasQueuedInput,
      isReplaying: false,
      subagentActivities: sessionState.subagentActivities,
      toolCalls,
      tasks: tasks ?? [],
      project: snapshot.projectId === id ? snapshot.project : null,
      rateLimitRetry: sessionState.rateLimitRetry,
      pendingReviewCount,
    });
    if (
      live.state === "working" &&
      sessionState.connectionState === "reconnecting"
    )
      return {
        ...idle,
        state: "reconnecting",
        hint: t("agentActivity.reconnecting"),
        indicatorPhase: "waiting",
      };
    if (live.state === "idle" && live.indicatorPhase === "attention")
      return {
        ...idle,
        state: "error",
        hint: live.label,
        indicatorPhase: "attention",
      };
    if (live.state === "idle" && sessionState.session?.status === "CANCELLED")
      return { ...idle, state: "stopped", hint: t("agentActivity.cancelled") };
    return {
      state: live.state,
      working: live.state === "working",
      hint: live.state === "idle" ? null : live.label,
      indicatorPhase: live.indicatorPhase,
    };
  }, [
    id,
    launch,
    sessionState,
    snapshot,
    tasks,
    pendingReviewCount,
    toolCalls,
    t,
  ]);
}
