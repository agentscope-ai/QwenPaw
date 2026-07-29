import { useEffect, useRef, useState } from "react";
import { Outlet } from "react-router-dom";
import { useShallow } from "zustand/react/shallow";
import { useParams, usePathname } from "@/routing/navigation";
import { navigateToLocator } from "@/routing/locators";
import type { FileProjectReviewOperation } from "@/contracts/creator";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import {
  CreatorPanel,
  useCreatorInteractionStore,
} from "@/store/creatorInteractionStore";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useNavigationStore } from "@/store/navigationStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import TopNav from "./TopNav";
import ReturnBanner from "@/components/creator/ReturnBanner";
import { AgentDock, SelectionToolbar } from "@/components/agent";
import { ProjectTour, AssetsTour } from "@/components/onboarding";
import PageSkeleton from "@/components/PageSkeleton";

const SUBAGENT_LIFECYCLE_EVENTS = new Set([
  "subagent.accepted",
  "subagent.started",
  "subagent.waiting_runtime",
  "subagent.completed",
  "subagent.blocked",
  "subagent.failed",
  "subagent.stale",
  "subagent.continuation_started",
  "subagent.continuation_completed",
]);

const FILE_AGENT_LIFECYCLE_EVENTS = new Set([
  "agent.run.started",
  "agent.run.completed",
  "agent.run.failed",
  "agent.run.cancelled",
  "agent.review.resolved",
  "agent.interrupt.idle",
]);

function isSubagentLifecycleEvent(type: string): boolean {
  return SUBAGENT_LIFECYCLE_EVENTS.has(type);
}

function isFileAgentLifecycleEvent(type: string): boolean {
  return FILE_AGENT_LIFECYCLE_EVENTS.has(type);
}

function isProjectShellEvent(type: string): boolean {
  return (
    type === "workspace.head_changed" ||
    type === "workspace.manual_edit_committed" ||
    type.startsWith("session.") ||
    type.startsWith("task.") ||
    type.startsWith("task_") ||
    isSubagentLifecycleEvent(type) ||
    isFileAgentLifecycleEvent(type)
  );
}

function reviewIdsFromEvent(data: Record<string, unknown>): string[] {
  if (!Array.isArray(data.reviewIds)) return [];
  return data.reviewIds.filter(
    (item): item is string => typeof item === "string" && item.length > 0,
  );
}

function elementIdFromPointer(pointer: string | null): string | null {
  if (!pointer) return null;
  const tokens = pointer
    .slice(1)
    .split("/")
    .map((token) => token.replace(/~1/g, "/").replace(/~0/g, "~"));
  if (
    tokens[0] !== "timelines" ||
    tokens[1] !== "items" ||
    !tokens[2] ||
    tokens[3] !== "elements_by_id" ||
    !tokens[4]
  )
    return null;
  return tokens[4];
}

/**
 * The place to land a reviewer after a run completes: prefer a generated media
 * artifact (jump to its Element workbench / asset detail), otherwise the first
 * text field so its diff can be flashed in place.  Derived entirely from the
 * server-provided ui_locator, falling back to the raw JSON pointer.
 */
function primaryReviewLocator(
  operations: FileProjectReviewOperation[],
): Record<string, string> | null {
  const pending = operations.filter(
    (operation) => operation.decision === "PENDING",
  );
  const media = pending.find((operation) => {
    const kind = operation.ui_locator?.mediaType;
    return kind === "image" || kind === "video";
  });
  if (media) return media.ui_locator;
  for (const operation of pending) {
    const locator = operation.ui_locator ?? {};
    if (locator.field || locator.elementId) return locator;
    const elementId = elementIdFromPointer(operation.json_pointer);
    if (elementId) {
      return {
        page: "plan",
        mediaType: "text",
        elementId,
        field: operation.json_pointer ?? "",
      };
    }
  }
  return null;
}

function LayoutSkeleton() {
  return (
    <div
      data-project-shell
      data-top-nav-height="58"
      className="app-shell grid h-screen grid-rows-[58px_minmax(0,1fr)]"
    >
      <TopNav />
      <main data-creator-workspace-root className="flex-1 overflow-hidden">
        <PageSkeleton type="list" />
      </main>
    </div>
  );
}

export default function ProjectLayout() {
  const { id = "" } = useParams();
  const pathname = usePathname();
  const bootstrap = useCreatorSessionStore((state) => state.bootstrap);
  const refreshSession = useCreatorSessionStore(
    (state) => state.refreshSession,
  );
  const disconnect = useCreatorSessionStore((state) => state.disconnect);
  const sessionStatus = useCreatorSessionStore(
    (state) => state.session?.status ?? null,
  );
  const events = useCreatorSessionStore(
    useShallow((state) =>
      state.events.filter((event) => isProjectShellEvent(event.type)),
    ),
  );
  const refreshTasks = useCreatorTaskViewStore((state) => state.refresh);
  const startProjectSnapshotPolling = useProjectSnapshotStore(
    (state) => state.startPolling,
  );
  const projectSnapshot = useProjectSnapshotStore((state) => state.project);
  const snapshotRevision = useProjectSnapshotStore(
    useShallow((state) => ({
      projectId: state.projectId,
      generation: state.generation,
      etag: state.etag,
    })),
  );
  const startFileReviewPolling = useFileProjectReviewStore(
    (state) => state.startPolling,
  );
  const activeFileReview = useFileProjectReviewStore(
    (state) => state.reviews[0] ?? null,
  );
  const fileReviewSyncStatus = useFileProjectReviewStore(
    (state) => state.syncStatus,
  );
  const [pendingReviewNavigation, setPendingReviewNavigation] = useState<{
    reviewId: string;
    ready: boolean;
  } | null>(null);
  const lastConsumedEvent = useRef(0);

  useEffect(() => {
    setPendingReviewNavigation(null);
  }, [id]);

  useEffect(() => {
    if (!id) return;
    // Project snapshot is the shared domain authority for every Creator page.
    return startProjectSnapshotPolling(id);
  }, [id, startProjectSnapshotPolling]);

  useEffect(() => {
    if (!id) return;
    const stop = startFileReviewPolling(id);
    return () => {
      stop();
      const reviewStore = useFileProjectReviewStore.getState();
      if (reviewStore.projectId === id) reviewStore.reset();
    };
  }, [id, startFileReviewPolling]);

  useEffect(() => {
    if (!id) return;
    const authorizationStore = useExecutionAuthorizationStore.getState();
    authorizationStore.bindProject(id);
    const poll = () => {
      void useExecutionAuthorizationStore
        .getState()
        .load(id)
        .catch(() => undefined);
    };
    poll();
    const timer = window.setInterval(poll, 1_000);
    return () => {
      window.clearInterval(timer);
      const current = useExecutionAuthorizationStore.getState();
      if (current.projectId === id) current.reset();
    };
  }, [id]);

  useEffect(() => {
    if (!id) return;
    const sessionState = useCreatorSessionStore.getState();
    const switchingProject = sessionState.projectId !== id;
    lastConsumedEvent.current = switchingProject
      ? 0
      : sessionState.lastEventSeq;
    if (switchingProject) {
      useCreatorTaskViewStore.getState().reset();
      useCreatorInteractionStore.getState().reset();
      useAgentDockUiStore.getState().reset();
      useNavigationStore.getState().clear();
    }
    void Promise.all([bootstrap(id), refreshTasks(id)]).catch(() => undefined);
    return () => disconnect();
  }, [bootstrap, disconnect, id, refreshTasks]);

  useEffect(() => {
    if (
      !id ||
      !sessionStatus ||
      sessionStatus === "IDLE" ||
      sessionStatus === "CANCELLED"
    )
      return;
    // Runtime Tasks are file-native and no longer emit the legacy bridge's
    // in-process progress callbacks to the browser.  Poll their durable heads
    // so AgentDock and Timeline surfaces expose QUEUED /
    // RUNNING progress while the blocking command request is still active.
    const timer = window.setInterval(() => {
      void refreshTasks(id).catch(() => undefined);
    }, 750);
    return () => window.clearInterval(timer);
  }, [id, refreshTasks, sessionStatus]);

  useEffect(() => {
    let panel: CreatorPanel = "other";
    if (pathname.includes("/plan")) panel = "plan";
    else if (pathname.includes("/assets")) panel = "assets";
    useCreatorInteractionStore.getState().setPanel(panel);
  }, [pathname]);

  useEffect(() => {
    const pendingEvents = events.filter(
      (event) => event.seq > lastConsumedEvent.current,
    );
    if (!pendingEvents.length) return;
    lastConsumedEvent.current = pendingEvents.at(-1)!.seq;
    pendingEvents.forEach((event) =>
      useCreatorTaskViewStore.getState().consumeEvent(event),
    );
    const completedReviewIds = pendingEvents
      .filter((event) => event.type === "agent.run.completed")
      .flatMap((event) => reviewIdsFromEvent(event.data));
    const completedReviewId = completedReviewIds.at(-1);
    if (completedReviewId) {
      setPendingReviewNavigation({ reviewId: completedReviewId, ready: false });
      const reviewStore = useFileProjectReviewStore.getState();
      void reviewStore
        .pollOnce(id)
        // If this call joined a request that began before run completion, the
        // second poll is guaranteed to observe the completed Review boundary.
        .then(() => useFileProjectReviewStore.getState().pollOnce(id))
        .then(() =>
          setPendingReviewNavigation((current) =>
            current?.reviewId === completedReviewId
              ? { ...current, ready: true }
              : current,
          ),
        )
        .catch(() => undefined);
    }
    if (
      pendingEvents.some(
        (event) =>
          event.type.startsWith("task.") ||
          event.type.startsWith("task_") ||
          isSubagentLifecycleEvent(event.type),
      )
    ) {
      void refreshTasks(id);
    }
    if (
      pendingEvents.some(
        (event) =>
          event.type.startsWith("session.") ||
          event.type.startsWith("task.") ||
          event.type.startsWith("task_") ||
          isSubagentLifecycleEvent(event.type) ||
          isFileAgentLifecycleEvent(event.type),
      )
    ) {
      void refreshSession().catch(() => undefined);
    }
    // File-native Review is synchronized independently by
    // useFileProjectReviewStore.  Runtime events can refresh Session/Task
    // projections, but must never be interpreted as legacy Transaction IDs or
    // trigger requests to the removed Transaction/Review API.
  }, [events, id, refreshSession, refreshTasks]);

  useEffect(() => {
    if (
      !pendingReviewNavigation?.ready ||
      fileReviewSyncStatus !== "healthy" ||
      activeFileReview?.review_id !== pendingReviewNavigation.reviewId
    )
      return;
    setPendingReviewNavigation(null);
    const locator = primaryReviewLocator(activeFileReview.operations);
    if (!locator) return;
    if (locator.elementId) {
      useCreatorInteractionStore
        .getState()
        .select(`element:${locator.elementId}`);
    }
    navigateToLocator(id, locator, {
      review: true,
      field: locator.field ?? undefined,
      description: "审阅 / 查看修改",
    });
  }, [activeFileReview, fileReviewSyncStatus, id, pendingReviewNavigation]);

  // A background Header revalidation must not unmount the active route.  The
  // initial skeleton is only needed before the first authoritative Header is
  // available.  Transient background Header/Session failures keep the last
  // authoritative shell mounted so AgentDock and the active editor do not
  // disappear while the durable SSE connection catches up.
  if (!projectSnapshot || snapshotRevision.projectId !== id) {
    return <LayoutSkeleton />;
  }

  return (
    <div
      data-project-shell
      data-top-nav-height="58"
      className="app-shell grid h-screen grid-rows-[58px_minmax(0,1fr)]"
    >
      <TopNav />
      <div className="flex min-h-0 overflow-hidden">
        <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
          <ReturnBanner />
          <main
            data-creator-workspace-root
            key={pathname}
            className="panel-enter relative min-h-0 flex-1 overflow-hidden"
          >
            <Outlet />
          </main>
        </div>
        <AgentDock sidebar />
      </div>
      <SelectionToolbar />
      <ProjectTour />
      <AssetsTour />
    </div>
  );
}
