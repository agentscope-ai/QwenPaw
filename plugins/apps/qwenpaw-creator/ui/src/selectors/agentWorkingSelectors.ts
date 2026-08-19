import { useMemo } from "react";
import i18n from "@/i18n";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";

// Same "working" criteria as AgentStatusBar's active check; additionally
// counts queuedUi messages not yet persisted, covering the window between
// clicking send and the backend responding.
const WORKING_SESSION_STATUSES = new Set([
  "RUNNING",
  "RESUMING",
  "WAITING_RUNTIME",
  "INTERRUPT_REQUESTED",
]);

export interface AgentWorkingState {
  working: boolean;
  hint: string | null;
}

export function useAgentWorkingState(): AgentWorkingState {
  const session = useCreatorSessionStore((state) => state.session);
  const agentStatusBar = useCreatorSessionStore(
    (state) => state.agentStatusBar,
  );
  const queuedUi = useCreatorSessionStore((state) => state.queuedUi);
  const subagentActivities = useCreatorSessionStore(
    (state) => state.subagentActivities,
  );

  return useMemo(() => {
    const working =
      (agentStatusBar?.activity?.runningTaskCount ?? 0) > 0 ||
      Boolean(session && WORKING_SESSION_STATUSES.has(session.status)) ||
      queuedUi.some((item) => item.state !== "failed");
    if (!working) return { working: false, hint: null };

    const label = agentStatusBar?.progress.label;
    if (label) return { working: true, hint: label };
    const activity = Object.values(subagentActivities)
      .filter((item) => !item.completed)
      .sort((left, right) => right.firstEventSeq - left.firstEventSeq)[0];
    if (activity) {
      const task =
        activity.delegationText || i18n.t("store.executingDelegatedTask");
      return {
        working: true,
        hint: activity.roleDisplayName
          ? `${activity.roleDisplayName}：${task}`
          : task,
      };
    }
    return { working: true, hint: null };
  }, [agentStatusBar, queuedUi, session, subagentActivities]);
}
