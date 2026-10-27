import { useCallback, useEffect, useRef, useState } from "react";
import { Outlet } from "react-router-dom";
import { useShallow } from "zustand/react/shallow";
import { useTranslation } from "react-i18next";
import { useParams, usePathname } from "@/routing/navigation";
import LaunchUploadProgressCard from "@/components/creator/LaunchUploadProgressCard";
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
import { useWorkGraphStore } from "@/store/workGraphStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { startVisiblePolling } from "@/lib/visiblePolling";
import TopNav from "./TopNav";
import WorkspaceSidebar from "./WorkspaceSidebar";
import ReturnBanner from "@/components/creator/ReturnBanner";
import { SelectionToolbar } from "@/components/agent";
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
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const pathname = usePathname();
  const bootstrap = useCreatorSessionStore((state) => state.bootstrap);
  const refreshSession = useCreatorSessionStore(
    (state) => state.refreshSession,
  );
  const disconnect = useCreatorSessionStore((state) => state.disconnect);
  const sessionActive = useCreatorSessionStore(
    (state) =>
      state.projectId === id &&
      [
        "RUNNING",
        "WAITING_RUNTIME",
        "INTERRUPT_REQUESTED",
        "RESUMING",
      ].includes(state.session?.status ?? ""),
  );
  const events = useCreatorSessionStore(
    useShallow((state) =>
      state.events.filter((event) => isProjectShellEvent(event.type)),
    ),
  );
  const refreshTasks = useCreatorTaskViewStore((state) => state.refresh);
  const tasksActive = useCreatorTaskViewStore(
    (state) =>
      state.projectId === id &&
      (state.tasks.some(
        (task) =>
          task.projectId === id && ["QUEUED", "RUNNING"].includes(task.status),
      ) ||
        state.runs.some((run) =>
          [
            "QUEUED",
            "QUEUED_CAPACITY",
            "RUNNING_MODEL",
            "WAITING_RUNTIME",
          ].includes(run.status),
        )),
  );
  const workGraphActive = useWorkGraphStore((state) => {
    if (state.projectId !== id || state.graph?.projectId !== id) return false;
    const counts = state.graph?.counts;
    if (!counts) return false;
    return (counts.running ?? 0) > 0;
  });
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
  const fileReviews = useFileProjectReviewStore((state) => state.reviews);
  const fileReviewSyncStatus = useFileProjectReviewStore(
    (state) => state.syncStatus,
  );
  const [pendingReviewNavigation, setPendingReviewNavigation] = useState<{
    reviewId: string;
    ready: boolean;
  } | null>(null);
  const lastConsumedEvent = useRef(0);
  const currentProjectId = useRef(id);
  currentProjectId.current = id;
  const productionRequest = useRef<{
    projectId: string;
    promise: Promise<void>;
  } | null>(null);
  const refreshProduction = useCallback((): Promise<void> => {
    if (!id || currentProjectId.current !== id) return Promise.resolve();
    if (productionRequest.current?.projectId === id)
      return productionRequest.current.promise;
    const tasks = useCreatorTaskViewStore.getState();
    const graph = useWorkGraphStore.getState();
    // Join this shell's current read and respect reads already started by a
    // workbench. A slow request must not accumulate overlapping interval/SSE
    // requests; each store also fences responses across project changes.
    const requests: Promise<void>[] = [];
    if (tasks.projectId !== id || !tasks.loading)
      requests.push(refreshTasks(id));
    if (graph.projectId !== id || !graph.loading)
      requests.push(graph.refresh(id));
    const promise = Promise.allSettled(requests)
      .then(() => undefined)
      .finally(() => {
        if (productionRequest.current?.promise === promise)
          productionRequest.current = null;
      });
    productionRequest.current = { projectId: id, promise };
    return promise;
  }, [id, refreshTasks]);

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
    // Every poll holds the shared project lock; slower, visibility-aware
    // ticks keep the reader stream from starving project writers.
    const stop = startVisiblePolling(poll, 2_000);
    return () => {
      stop();
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
    void Promise.all([
      bootstrap(id),
      // Load the graph eagerly: the DAG panel only renders once nodes
      // exist, and its own mount-refresh cannot break that chicken-and-egg
      // after a page reload on a scheduler-driven project.
      refreshProduction(),
    ]).catch(() => undefined);
    return () => disconnect();
  }, [bootstrap, disconnect, id, refreshProduction]);

  useEffect(() => {
    if (!id) return;
    // Manual generation and another tab can create Tasks without an active
    // agent or a Project publication. Keep an idle discovery poll; once real
    // activity appears, the same loop tracks it at the faster cadence.
    return startVisiblePolling(
      () => {
        void refreshProduction();
      },
      sessionActive || tasksActive || workGraphActive ? 3_000 : 10_000,
    );
  }, [id, refreshProduction, sessionActive, tasksActive, workGraphActive]);

  useEffect(() => {
    let panel: CreatorPanel = "other";
    if (pathname.includes("/plan")) panel = "plan";
    else if (pathname.includes("/assets")) panel = "assets";
    useCreatorInteractionStore.getState().setPanel(panel);
  }, [pathname]);

  useEffect(() => {
    const pendingEvents = events.filter(
      (event) =>
        event.projectId === id && event.seq > lastConsumedEvent.current,
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
      // Task/subagent lifecycle changes move work-graph node states too.
      void refreshProduction();
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
  }, [events, id, refreshSession, refreshProduction]);

  useEffect(() => {
    if (!pendingReviewNavigation?.ready || fileReviewSyncStatus !== "healthy")
      return;
    // Batched specialist work leaves several PENDING Reviews at once, so
    // the freshly completed one is not necessarily the head of the list —
    // requiring reviews[0] to match swallowed the popup whenever older
    // Reviews were still open (哈兰勇闯偶综, 2026-08-05: six pending, zero
    // popups). Find the target anywhere in the pending list instead.
    const targetReview = fileReviews.find(
      (review) => review.review_id === pendingReviewNavigation.reviewId,
    );
    if (!targetReview) return;
    setPendingReviewNavigation(null);
    const locator = primaryReviewLocator(targetReview.operations);
    if (!locator) return;
    if (locator.elementId) {
      useCreatorInteractionStore
        .getState()
        .select(`element:${locator.elementId}`);
    }
    navigateToLocator(id, locator, {
      review: true,
      field: locator.field ?? undefined,
      description: t("lib.reviewOrViewChanges"),
    });
  }, [fileReviews, fileReviewSyncStatus, id, pendingReviewNavigation]);

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
        {/* Left workspace sidebar: 创作助手 / 剧集列表 tabs over the AgentDock
            (design 83:13383); the composer stays pinned at its bottom. */}
        <WorkspaceSidebar />
        <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
          <ReturnBanner />
          <main
            data-creator-workspace-root
            key={pathname}
            className="panel-enter relative min-h-0 flex-1 overflow-hidden"
          >
            <Outlet />
            <LaunchUploadProgressCard />
          </main>
        </div>
      </div>
      <SelectionToolbar />
      <ProjectTour />
      <AssetsTour />
    </div>
  );
}
