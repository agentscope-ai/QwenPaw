import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { message, Modal, Tooltip } from "antd";
import { Bookmark, FileText, Info, Loader2, RefreshCw, X } from "lucide-react";
import { MenuUnfoldOutlined } from "@ant-design/icons";
import { navigate, useParams, useSearchParams } from "@/routing/navigation";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { useTimelineStore } from "@/store/timelineStore";
import { getArtifactVersionMediaUrl, renderTimeline } from "@/api/creator";
import {
  overlayContentKind,
  resolveTimelineRender,
  selectPrimaryTimeline,
  selectTimelineById,
  timelineEndTick,
} from "@/selectors/timelineElementSelectors";
import { resolveElementPlayback } from "@/selectors/elementPlaybackSelectors";
import { useReviewFieldFocus } from "@/routing/reviewFocus";
import { useProjectDraft } from "@/lib/useProjectDraft";
import { startVisiblePolling } from "@/lib/visiblePolling";
import { useNarrowWorkspace } from "@/lib/useNarrowWorkspace";
import TimelineCanvas from "@/components/timeline/TimelineCanvas";
import TimelineSnapshotPanel from "@/components/timeline/TimelineSnapshotPanel";
import ElementDetail from "@/components/timeline/ElementDetail";
import { storyboardOfOwner } from "@/components/workbench/referenceThumbs";
import WorkbenchModal from "@/components/workbench/WorkbenchModal";
import PageSkeleton from "@/components/PageSkeleton";
import PageLoadError from "@/components/PageLoadError";
import SaveAsTemplateDialog from "@/components/creator/SaveAsTemplateDialog";
import type {
  ProjectDocument,
  TimelineElementDocument,
} from "@/contracts/creator";
import { useTranslation } from "react-i18next";

/** 分镜图预览 rail tab (design 83:13383): the element's storyboard image. */
function StoryboardPreviewPanel({
  project,
  element,
}: {
  project: ProjectDocument;
  element: TimelineElementDocument | null;
}) {
  const { t } = useTranslation();
  const versionId = element
    ? storyboardOfOwner(project, `element:${element.element_id}`)
    : null;
  return (
    <div
      data-storyboard-preview-panel
      className="min-h-0 flex-1 overflow-y-auto p-3"
    >
      {versionId ? (
        <img
          src={getArtifactVersionMediaUrl(versionId)}
          alt=""
          className="w-full rounded-lg border border-[var(--color-border)]"
        />
      ) : (
        <p className="py-10 text-center text-xs text-[var(--color-text-tertiary)]">
          {t("plan.noStoryboard")}
        </p>
      )}
    </div>
  );
}

function sec(tick: number, ticksPerSecond: number): string {
  return (tick / ticksPerSecond).toFixed(1).replace(/\.0$/, "");
}

export default function PlanPage() {
  const { t } = useTranslation();
  const { id = "", timelineId: timelineIdParam } = useParams();
  const query = useSearchParams();
  const project = useProjectSnapshotStore((state) =>
    state.projectId === id ? state.project : null,
  );
  const syncStatus = useProjectSnapshotStore((state) => state.syncStatus);
  const syncError = useProjectSnapshotStore((state) => state.syncError);
  const patching = useProjectSnapshotStore((state) => state.patching);
  const patchProject = useProjectSnapshotStore((state) => state.patch);
  const pollOnce = useProjectSnapshotStore((state) => state.pollOnce);
  const tasks = useCreatorTaskViewStore((state) => state.tasks);
  const refreshTasks = useCreatorTaskViewStore((state) => state.refresh);
  const activeTimelineId = useTimelineStore((s) => s.activeTimelineId);
  const compareTimelineId = useTimelineStore((s) => s.compareTimelineId);
  // Route param wins (parameterized /t/:timelineId/plan); the legacy
  // unparameterized route follows the store's active timeline and degrades
  // to the primary one.
  const timeline = useMemo(
    () =>
      timelineIdParam
        ? selectTimelineById(project, timelineIdParam)
        : selectPrimaryTimeline(project, activeTimelineId),
    [project, timelineIdParam, activeTimelineId],
  );
  const compareTimeline = useMemo(
    () =>
      compareTimelineId && compareTimelineId !== activeTimelineId
        ? selectTimelineById(project, compareTimelineId)
        : null,
    [project, compareTimelineId, activeTimelineId],
  );
  const snapshotPanel = timeline ? (
    <TimelineSnapshotPanel
      project={project!}
      timeline={timeline}
      onPatch={async (operations) => {
        await patchProject(id, operations);
      }}
    />
  ) : undefined;
  const selectedElementId = query.get("element");
  const selectedElement =
    selectedElementId && timeline
      ? timeline.elements_by_id[selectedElementId] ?? null
      : null;
  const elementDraft = useProjectDraft(
    selectedElement,
    `${id}:${timeline?.timeline_id ?? "missing"}:${
      selectedElementId ?? "none"
    }:detail`,
    [
      "timelines",
      "items",
      timeline?.timeline_id ?? "missing",
      "elements_by_id",
      selectedElementId ?? "none",
    ],
  );
  const [playheadTick, setPlayheadTick] = useState(0);
  // Right rail tabs (design 83:13383): 视频概览 hosts the element overview,
  // 分镜图预览 shows the element's storyboard image (r2v elements only).
  const [railTab, setRailTab] = useState<"overview" | "storyboard">("overview");
  const storyboardTabAvailable = elementDraft.value?.creation.type === "r2v";
  useEffect(() => {
    if (!storyboardTabAvailable && railTab === "storyboard")
      setRailTab("overview");
  }, [railTab, storyboardTabAvailable]);
  const [composing, setComposing] = useState(false);
  const [requestedComposeTaskId, setRequestedComposeTaskId] = useState<
    string | null
  >(null);
  const [composeFailed, setComposeFailed] = useState(false);
  const [saveAsTemplateOpen, setSaveAsTemplateOpen] = useState(false);
  const [comparePreviewOpen, setComparePreviewOpen] = useState(true);
  const composeAttemptedGeneration = useRef<number | null>(null);
  const hadPendingReviews = useRef(false);
  const handledComposeTask = useRef<string | null>(null);
  const generation = useProjectSnapshotStore((state) => state.generation);
  // Media outputs awaiting user review are rejected by the compose admission
  // gate (409 WAITING_REVIEW), so auto-compose must wait them out.
  const pendingReviewCount = useFileProjectReviewStore((state) =>
    state.projectId === id ? state.reviews.length : 0,
  );
  // Explicit selection (range drag, block/lane clicks) pins a list; when
  // null, "content at the playhead" derives from timeline + playheadTick so
  // keyboard seeks, playback and span edits can never show stale elements.
  const [explicitActiveIds, setExplicitActiveIds] = useState<string[] | null>(
    null,
  );
  const durationTick = timelineEndTick(timeline);
  const displayDurationTick = timeline
    ? durationTick ||
      Math.round(
        (project?.settings.target_duration_seconds || 10) *
          timeline.ticks_per_second,
      )
    : 1;
  const clampedPlayheadTick = Math.min(playheadTick, displayDurationTick);
  // Any playhead motion (transport keys, scrub, playback, seeks) returns the
  // panel to follow mode so it can never describe a stale selection.
  const movePlayhead = useCallback((tick: number) => {
    setPlayheadTick(tick);
    setExplicitActiveIds(null);
  }, []);
  useEffect(() => {
    // Never carry one project's selection into another.
    setExplicitActiveIds(null);
  }, [id]);
  const reviewMode = query.get("review") === "1";
  const reviewField = query.get("field");
  const reviewPulse = query.get("reviewPulse");
  const base = timelineIdParam
    ? `/project/${id}/t/${encodeURIComponent(timelineIdParam)}/plan`
    : `/project/${id}/plan`;
  useReviewFieldFocus({
    path: base,
    field: reviewField,
    enabled: reviewMode,
    pulse: reviewPulse,
  });

  useEffect(() => {
    useCreatorInteractionStore
      .getState()
      .select(selectedElement ? `element:${selectedElement.element_id}` : null);
  }, [selectedElement]);

  useEffect(() => {
    if (!elementDraft.dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [elementDraft.dirty]);

  // Align the playhead to the element start only when the selected object's
  // identity changes (fallback for direct URL entry). Snapshot polling refreshes
  // selectedElement's object reference; depending on the reference would drag
  // the playhead back to the element start on every poll during playback,
  // showing up as "plays a few seconds then stops/jumps back".
  const lastAlignedElementId = useRef<string | null>(null);
  useEffect(() => {
    const elementId = selectedElement?.element_id ?? null;
    if (elementId === lastAlignedElementId.current) return;
    lastAlignedElementId.current = elementId;
    if (
      !selectedElement ||
      (playheadTick >= selectedElement.span.start_tick &&
        playheadTick <
          selectedElement.span.start_tick + selectedElement.span.duration_tick)
    )
      return;
    setPlayheadTick(selectedElement.span.start_tick);
    setExplicitActiveIds(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedElement]);

  const leaveDraft = useCallback(
    (next: () => void) => {
      if (!elementDraft.dirty) {
        next();
        return;
      }
      Modal.confirm({
        title: t("plan.unsavedChanges"),
        content: t("plan.unsavedChangesDesc"),
        okText: t("plan.discardAndLeave"),
        okButtonProps: { danger: true },
        cancelText: t("plan.continueEditing"),
        onOk: () => {
          elementDraft.discard();
          next();
        },
      });
    },
    [elementDraft],
  );
  const selectElement = useCallback(
    (elementId: string) => {
      leaveDraft(() => {
        const element = timeline?.elements_by_id[elementId];
        if (element) {
          setPlayheadTick((currentTick) => {
            const startTick = element.span.start_tick;
            const endTick = startTick + element.span.duration_tick;
            return currentTick >= startTick && currentTick < endTick
              ? currentTick
              : startTick;
          });
          // Follow mode by default; a track block click re-pins its own
          // explicit selection right after this handler in the same batch.
          setExplicitActiveIds(null);
        }
        navigate(
          selectedElementId === elementId
            ? base
            : `${base}?element=${encodeURIComponent(elementId)}`,
        );
      });
    },
    [base, leaveDraft, selectedElementId, timeline],
  );

  // Readiness criteria: main-track visuals and motion/media overlays that depend
  // on generation results must be ready; copy overlays are drawn
  // deterministically by the compositor, and transition/audio need no
  // independent generation.
  const readiness = useMemo(() => {
    if (!project || !timeline) return { total: 0, notReady: 0 };
    const items = Object.values(timeline.elements_by_id).filter(
      (element) =>
        element.enabled &&
        (element.creation.type === "r2v" ||
          element.creation.type === "t2v" ||
          element.creation.type === "i2v" ||
          element.creation.type === "s2v" ||
          element.creation.type === "edit" ||
          element.creation.type === "motion_clip" ||
          (element.creation.type === "overlay" &&
            overlayContentKind(element.creation) !== "copy")),
    );
    return {
      total: items.length,
      notReady: items.filter(
        (element) =>
          resolveElementPlayback(project, timeline, element, tasks).status !==
          "ready",
      ).length,
    };
  }, [project, tasks, timeline]);
  const renderOutput = useMemo(
    () =>
      project && timeline ? resolveTimelineRender(project, timeline) : null,
    [project, timeline],
  );
  const freshRender =
    renderOutput?.selected && !renderOutput.selected.stale
      ? renderOutput.selected
      : null;
  const renderIsCurrent =
    freshRender !== null &&
    (generation === null || freshRender.based_on_generation >= generation);
  const allReady = readiness.total > 0 && readiness.notReady === 0;
  const timelineTargetRef = timeline
    ? `timeline:${timeline.timeline_id}`
    : null;
  const activeComposeTask = useMemo(
    () =>
      timelineTargetRef
        ? tasks.find(
            (task) =>
              task.kind === "compose" &&
              task.targetRef === timelineTargetRef &&
              (task.status === "QUEUED" || task.status === "RUNNING"),
          ) ?? null
        : null,
    [tasks, timelineTargetRef],
  );
  const requestedComposeTask = useMemo(
    () =>
      requestedComposeTaskId
        ? tasks.find((task) => task.id === requestedComposeTaskId) ?? null
        : null,
    [requestedComposeTaskId, tasks],
  );
  const composePendingAdmission =
    requestedComposeTaskId !== null && requestedComposeTask === null;
  const isComposing =
    composing || composePendingAdmission || activeComposeTask !== null;
  const composeElementProgress = useMemo(() => {
    const completed = activeComposeTask?.completedElements;
    const total = activeComposeTask?.totalElements;
    if (
      !Number.isInteger(completed) ||
      !Number.isInteger(total) ||
      completed == null ||
      total == null ||
      total <= 0 ||
      completed < 0 ||
      completed > total
    )
      return null;
    return {
      completed,
      total,
      fraction: completed / total,
    };
  }, [activeComposeTask]);
  const composeLabel = composeElementProgress
    ? t("plan.composingLabel", {
        completed: composeElementProgress.completed,
        total: composeElementProgress.total,
      })
    : activeComposeTask
    ? t("plan.composingShort")
    : t("plan.preparingComposeShort");

  const composeNow = useCallback(async () => {
    if (!timeline || isComposing) return;
    setComposing(true);
    setComposeFailed(false);
    try {
      // The endpoint only dispatches a persistent Task; progress and the final
      // artifact are recovered via polling, so switching pages, refreshing, or a
      // takeover by another tab never loses compositing state.
      // The dispatch request itself may hang while the backend is busy; on
      // timeout, fall into the unified recovery branch so "preparing to
      // compose" doesn't hang until a manual refresh.
      const dispatch = await Promise.race([
        renderTimeline(id, timeline.timeline_id),
        new Promise<never>((_, reject) =>
          window.setTimeout(
            () => reject(new Error(t("plan.composeDispatchTimeout"))),
            15_000,
          ),
        ),
      ]);
      setRequestedComposeTaskId(dispatch.taskId);
      await Promise.allSettled([refreshTasks(id), pollOnce(id)]);
    } catch (error) {
      await refreshTasks(id).catch(() => undefined);
      const adopted = useCreatorTaskViewStore
        .getState()
        .tasks.find(
          (task) =>
            task.kind === "compose" &&
            task.targetRef === `timeline:${timeline.timeline_id}` &&
            (task.status === "QUEUED" || task.status === "RUNNING"),
        );
      if (adopted) {
        setRequestedComposeTaskId(adopted.id);
      } else {
        setComposeFailed(true);
        message.error(
          t("plan.composeFailed", { detail: (error as Error).message }),
        );
      }
    } finally {
      setComposing(false);
    }
  }, [id, isComposing, pollOnce, refreshTasks, timeline]);

  useEffect(() => {
    if (!isComposing) return;
    let disposed = false;
    const refresh = async () => {
      await Promise.allSettled([refreshTasks(id), pollOnce(id)]);
      if (disposed) return;
    };
    void refresh();
    // Compose progress polling shares the project lock with the compose
    // task itself; keep the tick slow and visibility-aware.
    const stop = startVisiblePolling(() => void refresh(), 1_500);
    return () => {
      disposed = true;
      stop();
    };
  }, [id, isComposing, pollOnce, refreshTasks]);

  useEffect(() => {
    if (requestedComposeTaskId || !activeComposeTask) return;
    // Adopt tasks started by other tabs or before a refresh, so their terminal
    // state also goes through the unified handling.
    composeAttemptedGeneration.current = generation;
    setRequestedComposeTaskId(activeComposeTask.id);
  }, [activeComposeTask, generation, requestedComposeTaskId]);

  useEffect(() => {
    if (!composePendingAdmission) return;
    // Self-heal when the dispatched taskId never shows up in the task list
    // (background dispatch failed, replaced, or intercepted by another writer),
    // so "preparing to compose" doesn't hang forever until a refresh.
    const pendingTaskId = requestedComposeTaskId;
    const timer = window.setTimeout(() => {
      void (async () => {
        await Promise.allSettled([refreshTasks(id), pollOnce(id)]);
        const latest = useCreatorTaskViewStore.getState();
        if (latest.tasks.some((task) => task.id === pendingTaskId)) return;
        setRequestedComposeTaskId(null);
        setComposeFailed(true);
      })();
    }, 10_000);
    return () => window.clearTimeout(timer);
  }, [
    composePendingAdmission,
    id,
    pollOnce,
    refreshTasks,
    requestedComposeTaskId,
  ]);

  useEffect(() => {
    if (
      !requestedComposeTask ||
      requestedComposeTask.status === "QUEUED" ||
      requestedComposeTask.status === "RUNNING" ||
      handledComposeTask.current === requestedComposeTask.id
    )
      return;
    handledComposeTask.current = requestedComposeTask.id;
    composeAttemptedGeneration.current = generation;
    setRequestedComposeTaskId(null);
    // The Project request already in-flight when the Task reached its terminal
    // state may return a stale snapshot; poll again serially so the final cut
    // published by a successful task lands on the page instead of stalling at 100%.
    void pollOnce(id).then(() => pollOnce(id));
    if (requestedComposeTask.status === "SUCCEEDED") {
      setComposeFailed(false);
      message.success(t("plan.composeSuccess"));
      return;
    }
    setComposeFailed(true);
    const detail =
      typeof requestedComposeTask.error?.message === "string"
        ? requestedComposeTask.error.message
        : requestedComposeTask.status === "QUARANTINED"
        ? t("plan.composeContentChanged")
        : t("plan.composeNotCompleted");
    message.error(t("plan.composeFailed", { detail }));
  }, [id, pollOnce, requestedComposeTask]);

  // Auto-compose once all main-track elements are ready and there is no
  // up-to-date final cut; only one attempt per generation (no auto-retry on
  // failure — a manual retry entry remains); a short debounce absorbs
  // successive edits.
  //
  // Review decisions do not bump the project generation, so once the pending
  // reviews drain, re-arm the one-attempt guard: the attempt blocked by the
  // review gate must not permanently disable auto-compose for this
  // generation.
  useEffect(() => {
    if (pendingReviewCount > 0) {
      hadPendingReviews.current = true;
      return;
    }
    if (hadPendingReviews.current) {
      hadPendingReviews.current = false;
      composeAttemptedGeneration.current = null;
    }
  }, [pendingReviewCount]);

  useEffect(() => {
    if (!allReady || renderIsCurrent || isComposing || pendingReviewCount > 0)
      return;
    if (
      generation !== null &&
      composeAttemptedGeneration.current === generation
    )
      return;
    const timer = window.setTimeout(() => {
      composeAttemptedGeneration.current = generation;
      void composeNow();
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [
    allReady,
    renderIsCurrent,
    isComposing,
    generation,
    composeNow,
    pendingReviewCount,
  ]);

  // Hooks must run unconditionally, before the loading early-returns.
  const narrowWorkspace = useNarrowWorkspace();
  // 折叠帧 (84:87110): when the left sidebar is collapsed the rail widens to
  // 509px and the stage header gains an inline expand button.
  const sidebarOpen = useAgentDockUiStore((state) => state.open);
  const setSidebarOpen = useAgentDockUiStore((state) => state.setOpen);

  if (!project) {
    if (syncStatus === "invalid" || syncStatus === "not_found") {
      return (
        <PageLoadError
          message={syncError || t("assets.projectReadError")}
          retry={() => void pollOnce(id)}
        />
      );
    }
    return <PageSkeleton type="list" />;
  }
  if (!timeline) {
    return (
      <PageLoadError
        message={t("plan.noTimeline")}
        retry={() => void pollOnce(id)}
      />
    );
  }

  const applyElementDraft = async () => {
    const draft = elementDraft.value;
    if (!draft || !elementDraft.operations.length) return;
    if (
      draft.creation.type === "overlay" &&
      overlayContentKind(draft.creation) === "copy" &&
      !draft.creation.text.trim()
    ) {
      message.error(t("plan.overlayTextEmpty"));
      return;
    }
    // A narration script or speech-rate edit needs the assistant to
    // re-synthesize the audio after the patch lands; captured before
    // markApplied clears it.
    const scriptEdit =
      draft.creation.type === "audio" &&
      draft.creation.script?.trim() &&
      elementDraft.operations.some(
        (operation) =>
          operation.path.endsWith("/creation/script") ||
          operation.path.endsWith("/creation/speech_rate"),
      )
        ? {
            elementId: draft.element_id,
            label: draft.label || draft.element_id,
            text: draft.creation.script.trim(),
            speechRate: draft.creation.speech_rate ?? 1.0,
            budgetSeconds: Number(
              (
                draft.span.duration_tick / (timeline?.ticks_per_second || 1000)
              ).toFixed(1),
            ),
          }
        : null;
    try {
      const response = await patchProject(id, elementDraft.operations);
      elementDraft.markApplied();
      if (scriptEdit) {
        void useCreatorSessionStore.getState().sendMessage({
          message: t("plan.ttsRegenerateMessage", scriptEdit),
        });
        message.success(t("plan.ttsRegenerateQueued"));
      } else if (response.editImpact?.regenerationRequired) {
        message.success(t("plan.applySuccessRegenRequired"));
      } else if (response.editImpact?.renderTimelineIds.length) {
        message.success(t("plan.applySuccessPreviewUpdated"));
      } else {
        message.success(t("plan.applySuccess"));
      }
    } catch (error) {
      message.error(
        t("plan.applyFailed", { detail: (error as Error).message }),
      );
    }
  };
  const closeElementDetail = () => leaveDraft(() => navigate(base));
  // 制作台改为方案页原地悬浮窗打开（毛玻璃 Modal），不再跳转独立页面；
  // 旧路由 /plan/element/:id 仍然保留用于深链。
  const [workbenchElementId, setWorkbenchElementId] = useState<string | null>(
    null,
  );
  const openElementWorkbench = (element: TimelineElementDocument) =>
    setWorkbenchElementId(element.element_id);

  const renderElementDetail = (frameless: boolean) => (
    <ElementDetail
      project={project}
      timeline={timeline}
      element={elementDraft.value}
      tasks={tasks}
      applying={patching}
      dirtyCount={elementDraft.dirtyCount}
      conflictPaths={elementDraft.conflictPaths}
      frameless={frameless}
      onClose={closeElementDetail}
      onChange={(mutator) =>
        elementDraft.update((draft) => {
          if (draft) mutator(draft);
        })
      }
      onApply={() => void applyElementDraft()}
      onDiscard={elementDraft.discard}
      onAcceptConflicts={elementDraft.acceptConflicts}
      onOpenWorkbench={openElementWorkbench}
    />
  );

  return (
    <div
      data-plan-page
      className="relative flex h-full min-h-0 flex-col bg-[var(--color-bg-layout)]"
    >
      {syncStatus === "degraded" && (
        <div className="shrink-0 border-b border-[var(--color-warning)]/20 bg-[var(--color-warning-soft)] px-5 py-1.5 text-[11px] text-[var(--color-warning)]">
          {t("plan.syncDegraded")}
          {syncError ? ` ${syncError}` : ""}
        </div>
      )}

      {/* Design 83:13383 grid: main column (header + stage) on the left, the
          389px overview rail beside it, transport + tracks spanning the full
          width at the bottom. TimelineCanvas(split) supplies rows 2–4. */}
      <div
        className={`relative grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)_auto_auto] bg-[var(--color-bg-primary)] ${
          narrowWorkspace
            ? "grid-cols-[minmax(0,1fr)]"
            : sidebarOpen
            ? "grid-cols-[minmax(0,1fr)_389px]"
            : "grid-cols-[minmax(0,1fr)_509px]"
        }`}
      >
        {/* Container queries are scoped to the header so the TimelineCanvas
            subtree never gains size containment. */}
        <header className="@container col-start-1 row-start-1 flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex min-w-0 items-center gap-2.5">
            {!sidebarOpen && (
              <button
                type="button"
                data-sidebar-expand
                title={t("plan.expandSidebar")}
                aria-label={t("plan.expandSidebar")}
                onClick={() => setSidebarOpen(true)}
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-[var(--color-border)] bg-white text-[var(--color-text-secondary)] transition hover:border-[var(--color-accent)]/50 hover:text-[var(--color-accent)] dark:bg-[var(--color-bg-elevated)]"
              >
                <MenuUnfoldOutlined className="text-base" />
              </button>
            )}
            <button
              type="button"
              onClick={() => leaveDraft(() => navigate(`/project/${id}`))}
              className="btn-secondary shrink-0"
            >
              {t("common.back")}
            </button>
            <h2 className="truncate text-sm font-medium text-[var(--color-text-primary)]">
              {timeline.title || t("blueprint.timelineEdit")}
            </h2>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2 pr-5">
            {/* When the workspace runs out of width the info chips fold
              into one tooltip so the action buttons keep their room. */}
            <div className="flex flex-wrap items-center gap-2 @max-[559px]:hidden">
              <span className="rounded-lg border border-[var(--color-border)] bg-white px-2.5 py-1.5 text-xs font-medium text-[var(--color-text-secondary)] dark:bg-[var(--color-bg-elevated)]">
                {project.settings.aspect_ratio}
              </span>
              <span className="rounded-lg border border-[var(--color-border)] bg-white px-2.5 py-1.5 text-xs font-medium text-[var(--color-text-secondary)] dark:bg-[var(--color-bg-elevated)]">
                {t("plan.items", {
                  count: Object.keys(timeline.elements_by_id).length,
                })}
              </span>
            </div>
            <Tooltip
              title={`${sec(durationTick, timeline.ticks_per_second)}s · ${
                project.settings.aspect_ratio
              } · ${t("plan.items", {
                count: Object.keys(timeline.elements_by_id).length,
              })}`}
            >
              <span className="hidden rounded-full border border-[var(--color-border)] bg-white px-2 py-1 text-[var(--color-text-secondary)] @max-[559px]:inline-flex dark:bg-[var(--color-bg-elevated)]">
                <Info className="h-3.5 w-3.5" />
              </span>
            </Tooltip>
            {/* 脚本方案 (84:46780): drill back up to the blueprint page. */}
            <button
              type="button"
              data-open-blueprint
              onClick={() => leaveDraft(() => navigate(`/project/${id}`))}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-white px-3 py-1.5 text-xs font-medium text-[var(--color-text-secondary)] transition hover:border-[var(--color-accent)]/50 hover:text-[var(--color-accent)] dark:bg-[var(--color-bg-elevated)]"
            >
              <FileText className="h-3.5 w-3.5" />
              {t("plan.scriptPlan")}
            </button>
            {composeFailed && !isComposing && (
              <button
                type="button"
                title={t("plan.retryComposeTitle")}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-danger)]/50 bg-[var(--color-danger-soft)] px-3 py-1.5 text-xs font-semibold text-[var(--color-danger)] transition hover:border-[var(--color-danger)]"
                onClick={() => void composeNow()}
              >
                <RefreshCw className="h-3.5 w-3.5" />
                {t("plan.retryCompose")}
              </button>
            )}
            <button
              type="button"
              data-compose-render
              title={
                isComposing
                  ? composeElementProgress
                    ? t("plan.composing", {
                        completed: composeElementProgress.completed,
                        total: composeElementProgress.total,
                      })
                    : t("plan.preparingCompose")
                  : t("plan.composeTooltip")
              }
              disabled={isComposing}
              className="relative inline-flex items-center gap-1.5 overflow-hidden rounded-lg border border-[var(--color-accent)]/50 bg-[var(--color-accent-soft)] px-3 py-1.5 text-xs font-semibold text-[var(--color-accent)] transition hover:border-[var(--color-accent)] disabled:opacity-70 disabled:cursor-not-allowed"
              onClick={() => void composeNow()}
            >
              {isComposing && (
                <span
                  aria-hidden="true"
                  className="absolute inset-x-0 bottom-0 h-0.5 overflow-hidden bg-[var(--color-border)]"
                >
                  {composeElementProgress ? (
                    <span
                      data-compose-progress
                      className="block h-full bg-[var(--color-accent)] transition-[width] duration-300 ease-out"
                      style={{
                        width: `${composeElementProgress.fraction * 100}%`,
                      }}
                    />
                  ) : (
                    <span
                      data-compose-activity
                      className="block h-full w-full animate-pulse bg-[var(--color-accent)]"
                    />
                  )}
                </span>
              )}
              <span className="relative z-[1] inline-flex items-center gap-1.5">
                {isComposing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                {isComposing ? composeLabel : t("lib.composeFinalCut")}
              </span>
            </button>
            <button
              type="button"
              data-save-template
              title={t("home.saveAsTemplate")}
              onClick={() => setSaveAsTemplateOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-1.5 text-xs font-semibold text-[var(--color-text-secondary)] transition hover:border-[var(--color-border-strong)] hover:text-[var(--color-text-primary)]"
            >
              <Bookmark className="h-3.5 w-3.5" />
              {t("home.saveAsTemplate")}
            </button>
            <SaveAsTemplateDialog
              open={saveAsTemplateOpen}
              onClose={() => setSaveAsTemplateOpen(false)}
              projectId={id}
            />
          </div>
        </header>

        {compareTimeline ? (
          <div className="flex min-h-0 shrink-0 divide-x divide-[var(--color-border)]">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 border-b border-[var(--color-border)] bg-[var(--color-accent-soft)] px-4 py-1">
                <span className="rounded bg-[var(--color-accent)] px-1.5 py-0.5 text-[10px] font-bold text-white">
                  A
                </span>
                <span className="truncate text-xs font-medium text-[var(--color-text-primary)]">
                  {timeline?.name ||
                    timeline?.title ||
                    t("timeline.snapshotCurrent")}
                </span>
              </div>
              <TimelineCanvas
                project={project}
                transportExtra={snapshotPanel}
                timeline={timeline}
                durationTick={displayDurationTick}
                playheadTick={clampedPlayheadTick}
                selectedElementId={selectedElementId}
                previewOpen={comparePreviewOpen}
                tasks={tasks}
                onPreviewOpenChange={setComparePreviewOpen}
                onPlayheadChange={(tick) =>
                  movePlayhead(Math.max(0, Math.min(displayDurationTick, tick)))
                }
                onSelectElement={selectElement}
                onActiveElementIdsChange={setExplicitActiveIds}
              />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 border-b border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-4 py-1">
                <span className="rounded bg-[var(--color-text-secondary)] px-1.5 py-0.5 text-[10px] font-bold text-white dark:bg-[var(--color-text-primary)]">
                  B
                </span>
                <span className="truncate text-xs font-medium text-[var(--color-text-secondary)]">
                  {(() => {
                    const raw = compareTimeline.name || "";
                    const match =
                      /^(?:快照\s*·\s*)?(.*?)(?:\s*·\s*\d{4}-\d{2}-\d{2} \d{2}:\d{2})?$/.exec(
                        raw,
                      );
                    const label = (match?.[1] ?? raw).trim();
                    return !label || /^(snapshot:)?timeline:/.test(label)
                      ? t("timeline.snapshotAutoName")
                      : label;
                  })()}
                </span>
                <button
                  type="button"
                  data-compare-close
                  title={t("timeline.snapshotExitCompare")}
                  onClick={() =>
                    useTimelineStore.getState().setCompareTimelineId(null)
                  }
                  className="ml-auto flex h-5 items-center gap-1 rounded px-1.5 text-[11px] font-medium text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-primary)] hover:text-[var(--color-text-primary)]"
                >
                  <X className="h-3.5 w-3.5" />
                  {t("timeline.snapshotExitCompare")}
                </button>
              </div>
              <TimelineCanvas
                project={project}
                timeline={compareTimeline}
                durationTick={Math.max(
                  displayDurationTick,
                  timelineEndTick(compareTimeline),
                )}
                playheadTick={clampedPlayheadTick}
                selectedElementId={null}
                previewOpen={comparePreviewOpen}
                tasks={tasks}
                onPreviewOpenChange={setComparePreviewOpen}
                onPlayheadChange={(tick) =>
                  movePlayhead(
                    Math.max(
                      0,
                      Math.min(
                        Math.max(
                          displayDurationTick,
                          timelineEndTick(compareTimeline),
                        ),
                        tick,
                      ),
                    ),
                  )
                }
                onSelectElement={() => {}}
                onActiveElementIdsChange={() => {}}
              />
            </div>
          </div>
        ) : (
          <TimelineCanvas
            variant="split"
            project={project}
            transportExtra={snapshotPanel}
            timeline={timeline}
            durationTick={displayDurationTick}
            playheadTick={clampedPlayheadTick}
            selectedElementId={selectedElementId}
            previewOpen
            tasks={tasks}
            onPreviewOpenChange={() => {}}
            onPlayheadChange={(tick) =>
              movePlayhead(Math.max(0, Math.min(displayDurationTick, tick)))
            }
            onSelectElement={selectElement}
            onActiveElementIdsChange={setExplicitActiveIds}
          />
        )}

        {/* Right rail (design 83:13383, 389px): 视频概览 hosts the element
          overview, 分镜图预览 the storyboard image; the rail spans the header
          and stage rows. On narrow workspaces it degrades to a drawer. */}
        {!narrowWorkspace ? (
          <aside
            data-element-rail
            className="col-start-2 row-span-2 row-start-1 flex min-h-0 flex-col overflow-hidden border-l border-[var(--color-border)] bg-[var(--color-bg-primary)]"
          >
            <div
              data-element-rail-tabs
              className="flex h-12 shrink-0 items-center gap-6 border-b border-[var(--color-border)] px-4"
            >
              {(
                [
                  { key: "overview", label: t("plan.railOverviewTab") },
                  ...(storyboardTabAvailable
                    ? [
                        {
                          key: "storyboard",
                          label: t("plan.railStoryboardTab"),
                        } as const,
                      ]
                    : []),
                ] as { key: "overview" | "storyboard"; label: string }[]
              ).map((item) => {
                const active = railTab === item.key;
                return (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => setRailTab(item.key)}
                    data-active={active}
                    className={`relative pb-1 text-sm transition-colors ${
                      active
                        ? "font-semibold text-[var(--color-text-primary)]"
                        : "font-medium text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]"
                    }`}
                  >
                    {item.label}
                    {active && (
                      <span className="absolute inset-x-0 -bottom-0.5 mx-auto h-0.5 w-6 rounded-full bg-[var(--color-text-primary)]" />
                    )}
                  </button>
                );
              })}
            </div>
            {railTab === "overview" ? (
              <div className="grid min-h-0 flex-1">
                {renderElementDetail(true)}
              </div>
            ) : (
              <StoryboardPreviewPanel
                project={project}
                element={elementDraft.value}
              />
            )}
          </aside>
        ) : elementDraft.value ? (
          <div className="absolute inset-y-4 right-4 z-40 grid w-[min(calc(100%-32px),420px)] min-h-0 shadow-2xl">
            {renderElementDetail(false)}
          </div>
        ) : null}
      </div>

      {workbenchElementId && timeline.elements_by_id[workbenchElementId] && (
        <WorkbenchModal
          projectId={id}
          element={timeline.elements_by_id[workbenchElementId]}
          timelineId={timeline.timeline_id}
          onClose={() => setWorkbenchElementId(null)}
        />
      )}
    </div>
  );
}
