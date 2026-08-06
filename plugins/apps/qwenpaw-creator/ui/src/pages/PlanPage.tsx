import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Dropdown, message, Modal } from "antd";
import {
  ChevronDown,
  Download,
  FileOutput,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { navigate, useParams, useSearchParams } from "@/routing/navigation";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { getArtifactVersionMediaUrl, renderTimeline } from "@/api/creator";
import {
  elementsAtTick,
  overlayContentKind,
  resolveTimelineRender,
  selectPrimaryTimeline,
  timelineEndTick,
} from "@/selectors/timelineElementSelectors";
import { resolveElementPlayback } from "@/selectors/elementPlaybackSelectors";
import { projectJsonPointer } from "@/lib/projectJsonPointer";
import { useReviewFieldFocus } from "@/routing/reviewFocus";
import { useProjectDraft } from "@/lib/useProjectDraft";
import TimelineCanvas from "@/components/timeline/TimelineCanvas";
import ElementList from "@/components/timeline/ElementList";
import ElementDetail from "@/components/timeline/ElementDetail";
import PageSkeleton from "@/components/PageSkeleton";
import PageLoadError from "@/components/PageLoadError";
import VisualCoverageCheckpoint from "@/components/creator/VisualCoverageCheckpoint";
import {
  ExportProgressCard,
  saveExportFile,
  type ExportProgressState,
} from "@/components/creator/ProjectImportExport";
import type { TimelineElementDocument } from "@/contracts/creator";
import { selectVisualVariantCoverage } from "@/selectors/visualVariantCoverage";
import { useTranslation } from "react-i18next";

function sec(tick: number, ticksPerSecond: number): string {
  return (tick / ticksPerSecond).toFixed(1).replace(/\.0$/, "");
}

export default function PlanPage() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
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
  const timeline = useMemo(() => selectPrimaryTimeline(project), [project]);
  const visualCoverage = useMemo(
    () => (project ? selectVisualVariantCoverage(project) : null),
    [project],
  );
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
  const [previewOpen, setPreviewOpen] = useState(false);
  const [composing, setComposing] = useState(false);
  const [exportProgress, setExportProgress] =
    useState<ExportProgressState | null>(null);
  const [requestedComposeTaskId, setRequestedComposeTaskId] = useState<
    string | null
  >(null);
  const [composeFailed, setComposeFailed] = useState(false);
  const composeAttemptedGeneration = useRef<number | null>(null);
  const handledComposeTask = useRef<string | null>(null);
  const generation = useProjectSnapshotStore((state) => state.generation);
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
  const activeElementIds = useMemo(
    () =>
      explicitActiveIds ??
      (timeline
        ? elementsAtTick(timeline, clampedPlayheadTick).map(
            (element) => element.element_id,
          )
        : []),
    [explicitActiveIds, timeline, clampedPlayheadTick],
  );
  const reviewMode = query.get("review") === "1";
  const reviewField = query.get("field");
  const reviewPulse = query.get("reviewPulse");
  useReviewFieldFocus({
    path: `/project/${id}/plan`,
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

  const base = `/project/${id}/plan`;
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
    const timer = window.setInterval(() => void refresh(), 750);
    return () => {
      disposed = true;
      window.clearInterval(timer);
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
  useEffect(() => {
    if (!allReady || renderIsCurrent || isComposing) return;
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
  }, [allReady, renderIsCurrent, isComposing, generation, composeNow]);

  const downloadRender = useCallback(async () => {
    if (!freshRender) return;
    const url = getArtifactVersionMediaUrl(freshRender.version_id);
    const filename = `${
      freshRender.name || project?.name || t("plan.finalCut")
    }.mp4`;
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(blobUrl);
    } catch {
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
    }
  }, [freshRender, project?.name]);

  const exporting = exportProgress?.status === "running";
  const exportProject = useCallback(async () => {
    if (exporting) return;
    setExportProgress({
      receivedBytes: 0,
      totalBytes: null,
      status: "running",
    });
    try {
      await saveExportFile(id, (receivedBytes, totalBytes) =>
        setExportProgress({ receivedBytes, totalBytes, status: "running" }),
      );
      setExportProgress((state) =>
        state ? { ...state, status: "done" } : state,
      );
    } catch (error) {
      setExportProgress(null);
      message.error(
        t("plan.exportFailed", { detail: (error as Error).message }),
      );
    }
  }, [exporting, id]);

  // The finished card lingers briefly, then clears itself.
  useEffect(() => {
    if (exportProgress?.status !== "done") return;
    const timer = window.setTimeout(() => setExportProgress(null), 5000);
    return () => window.clearTimeout(timer);
  }, [exportProgress]);

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
  const openElementWorkbench = (element: TimelineElementDocument) =>
    leaveDraft(() =>
      navigate(`${base}/element/${encodeURIComponent(element.element_id)}`),
    );

  return (
    <div
      data-plan-page
      className={`flex h-full min-h-0 flex-col bg-[var(--color-bg-layout)] ${
        previewOpen ? "overflow-y-auto overscroll-contain" : "overflow-hidden"
      }`}
    >
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]/60 px-5 py-3 backdrop-blur">
        <div data-onboarding-id="creative-brief" className="min-w-0">
          {project.strategy.creative_brief ||
          project.strategy.creative_direction ? (
            <details className="max-w-3xl">
              <summary className="w-fit cursor-pointer select-none text-base font-semibold text-[var(--color-text-primary)]">
                {t("plan.creativeBrief")}
              </summary>
              <div
                data-creator-field="project:strategy/creative_brief"
                data-creator-path={projectJsonPointer(
                  "strategy",
                  "creative_brief",
                )}
                data-creator-field-label={t("plan.creativeBrief")}
                className="mt-2 max-h-[92px] overflow-y-auto whitespace-pre-wrap rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-primary)] p-3 text-xs leading-5 text-[var(--color-text-secondary)]"
              >
                {project.strategy.creative_brief}
                {project.strategy.creative_direction &&
                  `\n\n${t("plan.creativeDirectionLabel", {
                    direction: project.strategy.creative_direction,
                  })}`}
              </div>
            </details>
          ) : (
            <h2 className="text-base font-semibold text-[var(--color-text-primary)]">
              {t("plan.creativeBrief")}
            </h2>
          )}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 pr-5">
          <span className="rounded-full border border-[var(--color-border)] bg-white px-2.5 py-1 text-[11px] font-semibold text-[var(--color-text-secondary)]">
            {sec(durationTick, timeline.ticks_per_second)}s
          </span>
          <span className="rounded-full border border-[var(--color-border)] bg-white px-2.5 py-1 text-[11px] font-semibold text-[var(--color-text-secondary)]">
            {project.settings.aspect_ratio}
          </span>
          <span className="rounded-full border border-[var(--color-border)] bg-white px-2.5 py-1 text-[11px] font-semibold text-[var(--color-text-secondary)]">
            {t("plan.items", {
              count: Object.keys(timeline.elements_by_id).length,
            })}
          </span>
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
            title={t("plan.composeTooltip")}
            disabled={isComposing}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-accent)]/50 bg-[var(--color-accent-soft)] px-3 py-1.5 text-xs font-semibold text-[var(--color-accent)] transition hover:border-[var(--color-accent)] disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={() => void composeNow()}
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${isComposing ? "animate-spin" : ""}`}
            />
            {isComposing ? t("lib.composing") : t("lib.composeFinalCut")}
          </button>
          {/* Download-final-cut and export-project share one split entry. */}
          <Dropdown
            trigger={["click"]}
            menu={{
              items: [
                {
                  key: "download",
                  label: t("plan.downloadFinal"),
                  icon: <Download className="h-3.5 w-3.5" />,
                  disabled: !freshRender,
                  onClick: () => void downloadRender(),
                },
                {
                  key: "export",
                  label: exporting
                    ? t("plan.exporting")
                    : t("plan.exportProject"),
                  icon: <FileOutput className="h-3.5 w-3.5" />,
                  disabled: exporting,
                  onClick: () => void exportProject(),
                },
              ],
            }}
          >
            <button
              type="button"
              data-download-render
              title={
                freshRender
                  ? t("plan.downloadFinalTitle")
                  : isComposing
                  ? composeElementProgress
                    ? t("plan.composing", {
                        completed: composeElementProgress.completed,
                        total: composeElementProgress.total,
                      })
                    : t("plan.preparingCompose")
                  : readiness.total === 0
                  ? t("plan.noComposableContent")
                  : readiness.notReady > 0
                  ? t("plan.waitingForContent", {
                      count: readiness.notReady,
                    })
                  : t("plan.waitingForCompose")
              }
              className="relative inline-flex cursor-pointer items-center gap-1.5 overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 py-1.5 text-xs font-semibold text-[var(--color-text-primary)] transition hover:border-[var(--color-border-strong)] hover:bg-[var(--color-bg-secondary)]"
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
                  <Download className="h-3.5 w-3.5" />
                )}
                {isComposing ? composeLabel : t("plan.downloadOrExport")}
                <ChevronDown className="h-3.5 w-3.5" />
              </span>
            </button>
          </Dropdown>
        </div>
      </header>

      {syncStatus === "degraded" && (
        <div className="shrink-0 border-b border-[var(--color-warning)]/20 bg-[var(--color-warning-soft)] px-5 py-1.5 text-[11px] text-[var(--color-warning)]">
          {t("plan.syncDegraded")}
          {syncError ? ` ${syncError}` : ""}
        </div>
      )}

      {visualCoverage && <VisualCoverageCheckpoint report={visualCoverage} />}

      <TimelineCanvas
        project={project}
        timeline={timeline}
        durationTick={displayDurationTick}
        playheadTick={clampedPlayheadTick}
        selectedElementId={selectedElementId}
        previewOpen={previewOpen}
        tasks={tasks}
        onPreviewOpenChange={setPreviewOpen}
        onPlayheadChange={(tick) =>
          movePlayhead(Math.max(0, Math.min(displayDurationTick, tick)))
        }
        onSelectElement={selectElement}
        onActiveElementIdsChange={setExplicitActiveIds}
      />

      <main
        className={`grid min-h-0 gap-4 p-4 ${
          previewOpen
            ? "h-[340px] shrink-0 grid-cols-[minmax(280px,36fr)_minmax(0,64fr)]"
            : "flex-1 grid-cols-[minmax(280px,36fr)_minmax(0,64fr)]"
        }`}
      >
        <ElementList
          timeline={timeline}
          playheadTick={playheadTick}
          activeElementIds={activeElementIds}
          selectionPinned={explicitActiveIds !== null}
          selectedElementId={selectedElementId}
          tasks={tasks}
          onSelect={selectElement}
        />
        <ElementDetail
          project={project}
          timeline={timeline}
          element={elementDraft.value}
          tasks={tasks}
          applying={patching}
          dirtyCount={elementDraft.dirtyCount}
          conflictPaths={elementDraft.conflictPaths}
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
      </main>

      {exportProgress && (
        <ExportProgressCard
          projectName={project.name}
          progress={exportProgress}
          onDismiss={() => setExportProgress(null)}
        />
      )}
    </div>
  );
}
