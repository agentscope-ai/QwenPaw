import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { message } from "antd";
import {
  ChevronDown,
  ChevronUp,
  Loader2,
  Magnet,
  Pause,
  Play,
  SkipBack,
  SkipForward,
  Volume2,
  VolumeX,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import type {
  ProjectDocument,
  TaskView,
  TimelineDocument,
  TimelineSpanDocument,
} from "@/contracts/creator";
import { getArtifactVersionMediaUrl } from "@/api/creator";
import { renderTimeline } from "@/api/creator/tasks";
import {
  elementsAtTick,
  groupDisplayTracks,
  resolveTimelineRender,
} from "@/selectors/timelineElementSelectors";
import type { ElementPlaybackStatus } from "@/selectors/elementPlaybackSelectors";
import { resolveElementPlayback } from "@/selectors/elementPlaybackSelectors";
import TimelineLivePreview from "@/components/timeline/TimelineLivePreview";
import TimelineTracks from "@/components/timeline/TimelineTracks";
import {
  buildSpanOperations,
  computeRippleChanges,
  type SpanChange,
} from "@/lib/timelineEditing";
import { formatSeconds } from "@/lib/timecode";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useCreatorEditBufferStore } from "@/store/creatorEditBufferStore";
import { useAgentWorkingState } from "@/selectors/agentWorkingSelectors";
import { useTranslation } from "react-i18next";

interface TimelineCanvasProps {
  project: ProjectDocument;
  timeline: TimelineDocument;
  durationTick: number;
  playheadTick: number;
  selectedElementId: string | null;
  previewOpen: boolean;
  tasks: TaskView[];
  onPreviewOpenChange: (open: boolean) => void;
  onPlayheadChange: (tick: number) => void;
  onSelectElement: (elementId: string) => void;
  onActiveElementIdsChange: (ids: string[] | null) => void;
}

const ZOOM_MIN = 1;
const ZOOM_MAX = 4;
/** Undo history depth for immediate write-back span edits. */
const HISTORY_LIMIT = 50;
const ZOOM_STEP = 0.5;
/** A final render that already painted a ready frame keeps that frame during
 * transient seeks/buffer stalls; the opaque locating cover only appears when
 * the gap persists this long. First loads still cover immediately. */
const FINAL_COVER_DELAY_MS = 300;

/** One committed span edit: inverse spans plus the values it applied. */
interface SpanHistoryEntry {
  undoChanges: SpanChange[];
  redoChanges: SpanChange[];
}

function spansMatch(
  timeline: TimelineDocument | null | undefined,
  changes: SpanChange[],
): boolean {
  if (!timeline) return false;
  return changes.every((change) => {
    const span = timeline.elements_by_id[change.elementId]?.span;
    return (
      span !== undefined &&
      span.start_tick === change.span.start_tick &&
      span.duration_tick === change.span.duration_tick
    );
  });
}

function seconds(tick: number, ticksPerSecond: number): string {
  return formatSeconds(tick, ticksPerSecond);
}

/** NLE-style timecode `MM:SS.t`, matching the reference transport display. */
function timecode(tick: number, ticksPerSecond: number): string {
  const totalSeconds = Math.max(0, tick / Math.max(1, ticksPerSecond));
  const minutes = Math.floor(totalSeconds / 60);
  const rest = totalSeconds - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${
    rest < 10 ? "0" : ""
  }${rest.toFixed(1)}`;
}

function percent(tick: number, durationTick: number): number {
  return durationTick > 0
    ? Math.min(100, Math.max(0, (tick / durationTick) * 100))
    : 0;
}

export default function TimelineCanvas({
  project,
  timeline,
  durationTick,
  playheadTick,
  selectedElementId,
  previewOpen,
  tasks,
  onPreviewOpenChange,
  onPlayheadChange,
  onSelectElement,
  onActiveElementIdsChange,
}: TimelineCanvasProps) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(false);
  const [muted, setMuted] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [finalFrameReady, setFinalFrameReady] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [snapEnabled, setSnapEnabled] = useState(true);
  const [dragOverrides, setDragOverrides] = useState<Map<
    string,
    TimelineSpanDocument
  > | null>(null);

  const agentWorking = useAgentWorkingState();
  const patch = useProjectSnapshotStore((state) => state.patch);
  const pollOnce = useProjectSnapshotStore((state) => state.pollOnce);
  const commitChain = useRef<Promise<void>>(Promise.resolve());
  // Undo/redo stacks hold committed edit entries; replays run through the
  // same serialized commit chain. Entries only leave a stack once the
  // replay patch succeeded, so a failed request never loses history.
  const undoStack = useRef<SpanHistoryEntry[]>([]);
  const redoStack = useRef<SpanHistoryEntry[]>([]);
  useEffect(() => {
    undoStack.current = [];
    redoStack.current = [];
  }, [project.project_id, timeline.timeline_id]);
  const videoRef = useRef<HTMLVideoElement>(null);
  const previewScrubberRef = useRef<HTMLDivElement>(null);
  const previewScrub = useRef<{
    pointerId: number;
    resumeAfterScrub: boolean;
  } | null>(null);

  // Effective timeline: authoritative document plus in-flight drag overrides,
  // so both the track blocks and the live preview follow the pointer without
  // waiting for the patch round-trip.
  const effectiveTimeline = useMemo(() => {
    if (!dragOverrides?.size) return timeline;
    const elements = { ...timeline.elements_by_id };
    dragOverrides.forEach((span, elementId) => {
      const element = elements[elementId];
      if (element) elements[elementId] = { ...element, span };
    });
    return { ...timeline, elements_by_id: elements };
  }, [timeline, dragOverrides]);

  const { tracks } = useMemo(
    () => groupDisplayTracks(effectiveTimeline),
    [effectiveTimeline],
  );
  const totalLanes = tracks.reduce((sum, track) => sum + track.lanes.length, 0);
  const scrollable = totalLanes > 4;
  const active = useMemo(
    () => elementsAtTick(effectiveTimeline, playheadTick),
    [playheadTick, effectiveTimeline],
  );
  const renderOutput = useMemo(
    () => resolveTimelineRender(project, timeline),
    [project, timeline],
  );
  const renderedVersion = renderOutput?.selected ?? null;
  const renderUrl = renderedVersion
    ? getArtifactVersionMediaUrl(renderedVersion.version_id)
    : null;
  const pendingAffectedElementIds = useMemo(() => {
    const raw = renderedVersion?.metadata.pendingAffectedElementIds;
    return new Set(
      Array.isArray(raw)
        ? raw.filter(
            (value): value is string =>
              typeof value === "string" && value.length > 0,
          )
        : [],
    );
  }, [renderedVersion]);
  // Locally recorded edit ranges (union of pre/post spans of edited elements):
  // old final-render frames inside them are wrong even when the element has
  // since moved away from the playhead's current tick.
  const localAffectedRanges = useCreatorEditBufferStore((state) =>
    state.projectId === project.project_id
      ? state.affectedRangesByTimeline[timeline.timeline_id]
      : undefined,
  );
  const clearAffectedRanges = useCreatorEditBufferStore(
    (state) => state.clearAffectedRanges,
  );
  const playheadLocallyAffected = (localAffectedRanges ?? []).some(
    (range) => playheadTick >= range.startTick && playheadTick < range.endTick,
  );
  useEffect(() => {
    if (renderedVersion && !renderedVersion.stale) {
      clearAffectedRanges(
        timeline.timeline_id,
        renderedVersion.based_on_generation,
      );
    }
  }, [clearAffectedRanges, renderedVersion, timeline.timeline_id]);
  const staleFrameIsUnaffected =
    Boolean(renderedVersion?.stale) &&
    pendingAffectedElementIds.size > 0 &&
    !playheadLocallyAffected &&
    active.every(
      (element) => !pendingAffectedElementIds.has(element.element_id),
    );
  // A fresh final render always wins. When the final render is only stale
  // because of a local Element edit, old final-render frames outside that
  // Element's time range are still complete and correct; the affected range
  // switches to live assembly instead — never pass off pre-edit footage as the
  // new result.
  const previewMode =
    renderUrl && (!renderedVersion?.stale || staleFrameIsUnaffected)
      ? "final"
      : "live";
  // Readiness states for the live-assembly preview; also drive the
  // generating/failed styling of track blocks.
  const playbackStates = useMemo(() => {
    const states = new Map<string, ElementPlaybackStatus>();
    Object.values(effectiveTimeline.elements_by_id).forEach((element) => {
      states.set(
        element.element_id,
        resolveElementPlayback(project, effectiveTimeline, element, tasks)
          .status,
      );
    });
    return states;
  }, [project, tasks, effectiveTimeline]);
  const timelineDuration = Math.max(1, durationTick);
  const finalVideo = videoRef.current;
  const finalPreviewReady =
    finalFrameReady &&
    Boolean(
      finalVideo &&
        !finalVideo.error &&
        finalVideo.readyState >= 2 &&
        !finalVideo.seeking &&
        (playing ||
          Math.abs(
            finalVideo.currentTime - playheadTick / timeline.ticks_per_second,
          ) <= 0.35),
    );
  // Debounced locating cover: once this render URL has shown a ready frame,
  // a transient seek or buffer stall keeps the last frame on screen instead
  // of flashing the opaque cover for a few frames.
  const hadReadyFinalFrame = useRef(false);
  const [finalCoverArmed, setFinalCoverArmed] = useState(true);
  useEffect(() => {
    hadReadyFinalFrame.current = false;
  }, [renderUrl]);
  useEffect(() => {
    if (finalPreviewReady) {
      hadReadyFinalFrame.current = true;
      setFinalCoverArmed(false);
      return;
    }
    if (!hadReadyFinalFrame.current) {
      setFinalCoverArmed(true);
      return;
    }
    const timer = window.setTimeout(
      () => setFinalCoverArmed(true),
      FINAL_COVER_DELAY_MS,
    );
    return () => window.clearTimeout(timer);
  }, [finalPreviewReady]);
  // First paint has no effect pass yet: the no-ready-frame rule keeps a
  // fresh load covered from the very first frame.
  const showFinalCover =
    !finalPreviewReady && (finalCoverArmed || !hadReadyFinalFrame.current);

  // ------------------------------------------------------------------
  // Direct write-back: span changes coming from the track surface commit to
  // project.json immediately (default-apply), serialized so consecutive drags
  // never race each other's base generation.
  // ------------------------------------------------------------------
  const performSpanCommit = async (
    changes: SpanChange[],
    history?: { kind: "undo" | "redo"; entry: SpanHistoryEntry },
  ) => {
    const snapshot = useProjectSnapshotStore.getState();
    const latestTimeline =
      snapshot.projectId === project.project_id
        ? snapshot.project?.timelines.items[timeline.timeline_id]
        : null;
    const clearCommitted = () =>
      setDragOverrides((previous) => {
        if (!previous) return null;
        const next = new Map(previous);
        changes.forEach((change) => next.delete(change.elementId));
        return next.size ? next : null;
      });
    if (!latestTimeline) {
      clearCommitted();
      return;
    }
    const rippleChanges = computeRippleChanges(latestTimeline, changes);
    const allChanges = [...changes, ...rippleChanges];
    const operations = buildSpanOperations(
      latestTimeline,
      timeline.timeline_id,
      allChanges,
    );
    if (!operations.length) {
      clearCommitted();
      return;
    }
    // Inverse spans captured before the patch make the edit undoable.
    const applied = allChanges.filter(
      (change) => latestTimeline.elements_by_id[change.elementId],
    );
    const inverseChanges: SpanChange[] = applied.map((change) => ({
      elementId: change.elementId,
      span: { ...latestTimeline.elements_by_id[change.elementId].span },
    }));
    try {
      const response = await patch(project.project_id, operations);
      if (history?.kind === "undo") {
        redoStack.current.push(history.entry);
      } else if (history?.kind === "redo") {
        undoStack.current.push(history.entry);
      } else {
        undoStack.current.push({
          undoChanges: inverseChanges,
          redoChanges: applied.map((change) => ({
            elementId: change.elementId,
            span: { ...change.span },
          })),
        });
        if (undoStack.current.length > HISTORY_LIMIT) {
          undoStack.current.shift();
        }
        redoStack.current = [];
      }
      clearCommitted();
      if (response.editImpact?.regenerationRequired) {
        message.success(t("timeline.timingAppliedRegenRequired"));
      } else if (response.editImpact?.renderTimelineIds.length) {
        message.success(t("timeline.timingAppliedRecomposing"));
        // Auto-trigger recompose so the final render stays in sync
        void renderTimeline(project.project_id, timeline.timeline_id).catch(
          () => undefined,
        );
      } else {
        message.success(t("timeline.timingApplied"));
      }
    } catch (error) {
      // A failed replay must not lose history: the entry goes back onto
      // the stack it came from.
      if (history?.kind === "undo") undoStack.current.push(history.entry);
      if (history?.kind === "redo") redoStack.current.push(history.entry);
      clearCommitted();
      message.error(
        t("timeline.applyTimingFailed", { detail: (error as Error).message }),
      );
      void pollOnce(project.project_id);
    }
  };

  const commitSpans = (changes: SpanChange[]) => {
    commitChain.current = commitChain.current.then(() =>
      performSpanCommit(changes),
    );
  };

  /**
   * Undo/redo run entirely inside the serialized commit chain: the stack is
   * only read after every queued edit has settled, and the collaboration
   * guard re-checks the freshest snapshot right before the patch. This
   * prevents a queued undo from reverting past an edit that was still
   * committing when the key was pressed.
   */
  const replayHistory = (kind: "undo" | "redo") => {
    commitChain.current = commitChain.current.then(async () => {
      const stack = kind === "undo" ? undoStack.current : redoStack.current;
      const entry = stack.pop();
      if (!entry) return;
      const snapshot = useProjectSnapshotStore.getState();
      const latest =
        snapshot.projectId === project.project_id
          ? snapshot.project?.timelines.items[timeline.timeline_id]
          : null;
      const expected = kind === "undo" ? entry.redoChanges : entry.undoChanges;
      if (!spansMatch(latest, expected)) {
        message.warning(
          kind === "undo"
            ? t("timeline.undoCancelled")
            : t("timeline.redoCancelled"),
        );
        return;
      }
      await performSpanCommit(
        kind === "undo" ? entry.undoChanges : entry.redoChanges,
        { kind, entry },
      );
    });
  };

  const seekPreviewToPlayhead = (video: HTMLVideoElement) => {
    if (!Number.isFinite(video.duration)) return;
    const target = playheadTick / timeline.ticks_per_second;
    if (Math.abs(video.currentTime - target) > 0.35) {
      setFinalFrameReady(false);
      video.currentTime = Math.min(video.duration || target, target);
    } else if (video.readyState >= 2 && !video.seeking) {
      setFinalFrameReady(true);
    }
  };

  useEffect(() => setFinalFrameReady(false), [renderUrl]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    seekPreviewToPlayhead(video);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playheadTick, previewOpen, renderUrl, timeline.ticks_per_second]);

  useEffect(() => {
    if (!previewOpen || previewMode !== "final" || !renderUrl) return;
    const synchronizeReadyState = () => {
      const video = videoRef.current;
      const ready = Boolean(
        video &&
          !video.error &&
          video.readyState >= 2 &&
          !video.seeking &&
          (playing ||
            Math.abs(
              video.currentTime - playheadTick / timeline.ticks_per_second,
            ) <= 0.35),
      );
      setFinalFrameReady((current) => (current === ready ? current : ready));
    };
    // Some browsers recover from waiting/stalled with readyState=4 without
    // emitting another canplay event.  Reconcile against the media element so
    // a complete frame cannot remain hidden behind a stale loading cover.
    synchronizeReadyState();
    const timer = window.setInterval(synchronizeReadyState, 250);
    return () => window.clearInterval(timer);
  }, [
    playheadTick,
    playing,
    previewMode,
    previewOpen,
    renderUrl,
    timeline.ticks_per_second,
  ]);

  useEffect(() => {
    if (!previewOpen) setPlaying(false);
    else if (previewMode === "final" && !renderUrl) setPlaying(false);
  }, [previewOpen, previewMode, renderUrl]);

  const previewTickAt = (clientX: number): number => {
    const rect = previewScrubberRef.current?.getBoundingClientRect();
    if (!rect) return playheadTick;
    const fraction = Math.min(
      1,
      Math.max(0, (clientX - rect.left) / Math.max(1, rect.width)),
    );
    return Math.round(fraction * timelineDuration);
  };

  const pausePreviewForScrub = () => {
    if (!playing) return;
    if (previewMode === "live") setPlaying(false);
    else videoRef.current?.pause();
  };

  const resumePreviewAfterScrub = () => {
    if (previewMode === "live") {
      setPlaying(true);
      return;
    }
    void videoRef.current?.play();
  };

  const beginPreviewScrub = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    previewScrub.current = {
      pointerId: event.pointerId,
      resumeAfterScrub: playing,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    pausePreviewForScrub();
    onPlayheadChange(previewTickAt(event.clientX));
  };

  const movePreviewScrub = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (previewScrub.current?.pointerId !== event.pointerId) return;
    event.preventDefault();
    onPlayheadChange(previewTickAt(event.clientX));
  };

  const finishPreviewScrub = (
    event: ReactPointerEvent<HTMLDivElement>,
    commitPointerPosition: boolean,
  ) => {
    const current = previewScrub.current;
    if (!current || current.pointerId !== event.pointerId) return;
    event.preventDefault();
    if (commitPointerPosition) {
      onPlayheadChange(previewTickAt(event.clientX));
    }
    previewScrub.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (current.resumeAfterScrub) resumePreviewAfterScrub();
  };

  const movePreviewScrubberByKeyboard = (
    event: React.KeyboardEvent<HTMLDivElement>,
  ) => {
    const oneSecond = Math.max(1, timeline.ticks_per_second);
    const fiveSeconds = oneSecond * 5;
    let nextTick: number | null = null;
    switch (event.key) {
      case "ArrowLeft":
      case "ArrowDown":
        nextTick = playheadTick - oneSecond;
        break;
      case "ArrowRight":
      case "ArrowUp":
        nextTick = playheadTick + oneSecond;
        break;
      case "PageDown":
        nextTick = playheadTick - fiveSeconds;
        break;
      case "PageUp":
        nextTick = playheadTick + fiveSeconds;
        break;
      case "Home":
        nextTick = 0;
        break;
      case "End":
        nextTick = timelineDuration;
        break;
      default:
        return;
    }
    event.preventDefault();
    onPlayheadChange(Math.min(timelineDuration, Math.max(0, nextTick)));
  };

  const adjustZoom = (delta: number) => {
    setZoom((value) =>
      Math.min(
        ZOOM_MAX,
        Math.max(ZOOM_MIN, Number((value + delta).toFixed(2))),
      ),
    );
  };
  const changeZoom = (next: number) => {
    setZoom(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next)));
  };

  const togglePlayback = () => {
    if (!previewOpen) {
      onPreviewOpenChange(true);
      if (previewMode === "live") setPlaying(true);
      return;
    }
    if (previewMode === "live") {
      if (!playing && playheadTick >= timelineDuration) onPlayheadChange(0);
      setPlaying((value) => !value);
      return;
    }
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void video.play();
    else video.pause();
  };
  const togglePlaybackRef = useRef(togglePlayback);
  togglePlaybackRef.current = togglePlayback;
  const undoRef = useRef(() => {});
  undoRef.current = () => replayHistory("undo");
  const redoRef = useRef(() => {});
  redoRef.current = () => replayHistory("redo");
  const seekByRef = useRef((deltaTick: number) => {
    onPlayheadChange(
      Math.min(timelineDuration, Math.max(0, playheadTick + deltaTick)),
    );
  });
  seekByRef.current = (deltaTick: number) => {
    onPlayheadChange(
      Math.min(timelineDuration, Math.max(0, playheadTick + deltaTick)),
    );
  };

  // NLE keyboard shortcuts: Space play/pause, ←/→ ±1s (Shift ±0.1s),
  // Home/End. Ignored while typing or when another control owns the key.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target?.closest(
          "input, textarea, select, [contenteditable='true'], [role='slider']",
        )
      )
        return;
      const tps = Math.max(1, timeline.ticks_per_second);
      if (
        (event.metaKey || event.ctrlKey) &&
        (event.key === "z" || event.key === "Z")
      ) {
        // Standard NLE history: ⌘/Ctrl+Z undo, ⌘/Ctrl+Shift+Z redo.
        event.preventDefault();
        if (event.shiftKey) redoRef.current();
        else undoRef.current();
        return;
      }
      if (event.key === " " || event.code === "Space") {
        if (target?.closest("button, a")) return;
        event.preventDefault();
        togglePlaybackRef.current();
        return;
      }
      const stepTick = Math.max(1, Math.round(event.shiftKey ? tps / 10 : tps));
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        seekByRef.current(-stepTick);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        seekByRef.current(stepTick);
      } else if (event.key === "Home") {
        event.preventDefault();
        seekByRef.current(Number.NEGATIVE_INFINITY);
      } else if (event.key === "End") {
        event.preventDefault();
        seekByRef.current(Number.POSITIVE_INFINITY);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [timeline.ticks_per_second]);

  return (
    <section
      data-timeline-panel
      className={`relative mx-4 mt-3 shrink-0 overflow-visible rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-primary)] shadow-sm ${
        previewOpen ? "flex max-h-[66vh] flex-col" : ""
      }`}
    >
      <div className="flex min-h-10 flex-wrap items-center justify-between gap-2 border-b border-[var(--color-border)] px-3 py-1.5 text-[11px] text-[var(--color-text-tertiary)]">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <b className="text-[var(--color-text-primary)]">
            {t("timeline.timeline")}
          </b>
          <span
            data-timeline-playhead-summary
            className="rounded-full bg-[var(--color-accent-soft)] px-2 py-0.5 font-semibold text-[var(--color-accent)]"
          >
            {/* Pure playhead semantics: derived from the timeline at the
                playhead tick, never from an explicit selection. */}
            {seconds(playheadTick, timeline.ticks_per_second)}s ·{" "}
            {t("timeline.itemsCount", { count: active.length })}
          </span>
          <span
            className={`rounded-full bg-[var(--color-bg-secondary)] px-2 py-0.5 ${
              scrollable ? "ring-1 ring-[var(--color-border)]" : ""
            }`}
          >
            {tracks.length} {t("timeline.track")}
            {scrollable ? t("timeline.scrollable") : ""}
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 pr-3">
          <button
            type="button"
            onClick={() => onPreviewOpenChange(!previewOpen)}
            className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 font-semibold ${
              previewOpen
                ? "border-[var(--color-accent)]/40 bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                : "border-[var(--color-border)] text-[var(--color-text-secondary)]"
            }`}
          >
            {previewOpen ? (
              <ChevronUp className="h-3 w-3" />
            ) : (
              <ChevronDown className="h-3 w-3" />
            )}
            {previewOpen
              ? t("timeline.collapsePreview")
              : t("timeline.videoPreview")}
          </button>
          <button
            type="button"
            onClick={() => setCollapsed((value) => !value)}
            className="rounded-md border border-[var(--color-border)] px-2 py-1 font-semibold text-[var(--color-text-secondary)]"
          >
            {collapsed
              ? t("timeline.expandTimeline")
              : t("timeline.collapseTimeline")}
          </button>
        </div>
      </div>

      {previewOpen && (
        <div
          data-timeline-video-preview
          className="relative flex h-[clamp(220px,40vh,400px)] min-h-0 w-full shrink items-center justify-center overflow-hidden bg-[#12100f]"
        >
          {previewMode === "live" ? (
            <TimelineLivePreview
              project={project}
              timeline={effectiveTimeline}
              durationTick={timelineDuration}
              playheadTick={playheadTick}
              playing={playing}
              muted={muted}
              tasks={tasks}
              onPlayheadChange={onPlayheadChange}
              onPlayingChange={setPlaying}
            />
          ) : renderUrl ? (
            <video
              ref={videoRef}
              src={renderUrl}
              className="h-full w-full bg-black object-contain"
              muted={muted}
              playsInline
              preload="auto"
              onLoadedMetadata={(event) =>
                seekPreviewToPlayhead(event.currentTarget)
              }
              onLoadedData={(event) =>
                seekPreviewToPlayhead(event.currentTarget)
              }
              onCanPlay={(event) => {
                if (!event.currentTarget.seeking) setFinalFrameReady(true);
              }}
              onSeeking={() => setFinalFrameReady(false)}
              onSeeked={() => setFinalFrameReady(true)}
              onWaiting={() => setFinalFrameReady(false)}
              onStalled={() => setFinalFrameReady(false)}
              onError={() => setFinalFrameReady(false)}
              onPlay={() => {
                setFinalFrameReady(true);
                setPlaying(true);
              }}
              onPause={() => setPlaying(false)}
              onTimeUpdate={(event) =>
                onPlayheadChange(
                  Math.round(
                    event.currentTarget.currentTime * timeline.ticks_per_second,
                  ),
                )
              }
              onEnded={(event) => {
                setPlaying(false);
                event.currentTarget.pause();
              }}
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center bg-[radial-gradient(circle_at_center,#28221e_0,#151210_64%,#0d0b0a_100%)] text-center text-sm text-white/58">
              <span>{t("timeline.noPreview")}</span>
            </div>
          )}
          {previewMode === "final" && renderUrl && showFinalCover && (
            <div
              data-final-preview-incomplete
              role="status"
              aria-live="polite"
              className="absolute inset-0 z-[5] flex flex-col items-center justify-center gap-2 bg-[radial-gradient(circle_at_center,#2b2521_0,#161210_62%,#0d0b0a_100%)] px-6 text-center"
            >
              <Loader2 className="h-7 w-7 animate-spin text-white/75" />
              <span className="text-sm font-semibold text-white/90">
                {t("timeline.locatingFrame")}
              </span>
              <span className="text-xs leading-5 text-white/60">
                {t("timeline.renderDoneDesc")}
              </span>
            </div>
          )}
          <div
            data-preview-source-chip
            className="absolute left-3 top-3 z-10 flex items-center gap-1.5 rounded-full border border-white/20 bg-black/45 px-2.5 py-1 text-[11px] font-semibold text-white/85 backdrop-blur"
            title={
              previewMode === "final"
                ? renderedVersion?.stale
                  ? t("timeline.notAffected")
                  : t("timeline.playingFinal")
                : t("timeline.liveRenderDesc")
            }
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                previewMode === "final"
                  ? "bg-[var(--color-success)]"
                  : "animate-pulse bg-[var(--color-accent)]"
              }`}
            />
            {previewMode === "final"
              ? renderedVersion?.stale
                ? t("timeline.notAffectedLabel")
                : t("timeline.finalCut")
              : renderedVersion?.stale
              ? t("timeline.contentUpdated")
              : t("timeline.livePreview")}
          </div>
        </div>
      )}

      {/* Transport bar mirrors the reference design: playback controls and
          the shared progress in the center, snapping/zoom on the right. The
          flex bases let the snap/zoom cluster wrap to its own row on narrow
          workspaces instead of overlapping the timecode. */}
      <div
        data-timeline-transport
        className="flex min-h-[38px] flex-wrap items-center gap-x-2 gap-y-1 border-b border-[var(--color-border)] bg-[var(--color-bg-secondary)]/45 px-2.5 py-1 text-[11px]"
      >
        <div className="flex min-w-0 flex-[1_1_280px] items-center gap-1.5">
          <button
            type="button"
            onClick={() => {
              onPlayheadChange(
                Math.max(0, playheadTick - timeline.ticks_per_second),
              );
            }}
            className="flex h-7 w-7 items-center justify-center rounded-[7px] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
            aria-label={t("timeline.skipBack1s")}
          >
            <SkipBack className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={togglePlayback}
            className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--color-accent)] text-white"
            aria-label={t("timeline.playPause")}
          >
            {playing ? (
              <Pause className="h-3.5 w-3.5" />
            ) : (
              <Play className="h-3.5 w-3.5 fill-current" />
            )}
          </button>
          <button
            type="button"
            onClick={() => {
              onPlayheadChange(
                Math.min(
                  timelineDuration,
                  playheadTick + timeline.ticks_per_second,
                ),
              );
            }}
            className="flex h-7 w-7 items-center justify-center rounded-[7px] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
            aria-label={t("timeline.skipForward1s")}
          >
            <SkipForward className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => setMuted((value) => !value)}
            className="flex h-7 w-7 items-center justify-center rounded-[7px] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
            aria-label={muted ? t("timeline.unmute") : t("timeline.mute")}
          >
            {muted ? (
              <VolumeX className="h-3.5 w-3.5" />
            ) : (
              <Volume2 className="h-3.5 w-3.5" />
            )}
          </button>
          <div
            ref={previewScrubberRef}
            data-preview-scrubber
            role="slider"
            tabIndex={0}
            aria-label={t("timeline.dragTimeline")}
            aria-valuemin={0}
            aria-valuemax={timelineDuration}
            aria-valuenow={Math.min(playheadTick, timelineDuration)}
            aria-valuetext={`${seconds(
              playheadTick,
              timeline.ticks_per_second,
            )} ${t("timeline.seconds")}`}
            onPointerDown={beginPreviewScrub}
            onPointerMove={movePreviewScrub}
            onPointerUp={(event) => finishPreviewScrub(event, true)}
            onPointerCancel={(event) => finishPreviewScrub(event, false)}
            onKeyDown={movePreviewScrubberByKeyboard}
            className="relative h-6 min-w-[80px] flex-1 cursor-pointer touch-none rounded-full focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent)]"
          >
            <span className="pointer-events-none absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 overflow-hidden rounded-full bg-[var(--color-border)]">
              <i
                className="block h-full rounded-full bg-[var(--color-accent)]"
                style={{
                  width: `${percent(playheadTick, timelineDuration)}%`,
                }}
              />
            </span>
            <i
              aria-hidden
              className="pointer-events-none absolute top-1/2 block h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-[var(--color-accent)] shadow-sm"
              style={{
                left: `${percent(playheadTick, timelineDuration)}%`,
              }}
            />
          </div>
          <span
            data-timeline-timecode
            className="shrink-0 whitespace-nowrap font-mono text-[11px] tabular-nums text-[var(--color-text-secondary)]"
          >
            {timecode(playheadTick, timeline.ticks_per_second)} /{" "}
            {timecode(timelineDuration, timeline.ticks_per_second)}
          </span>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          <label
            className="flex cursor-pointer items-center gap-1.5 text-[var(--color-text-secondary)]"
            title={t("timeline.snapTooltip")}
          >
            <button
              type="button"
              data-timeline-snap-toggle
              aria-pressed={snapEnabled}
              onClick={() => setSnapEnabled((value) => !value)}
              className={`inline-flex h-7 items-center gap-1 rounded-[7px] px-2 font-semibold ${
                snapEnabled
                  ? "bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                  : "text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
              }`}
            >
              <Magnet className="h-3.5 w-3.5" />
              {t("timeline.snap")}
            </button>
          </label>
          <div className="flex items-center gap-0.5">
            <button
              type="button"
              data-timeline-zoom-out
              disabled={zoom <= ZOOM_MIN}
              onClick={() => adjustZoom(-ZOOM_STEP)}
              className="flex h-7 w-7 items-center justify-center rounded-[7px] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] disabled:opacity-30"
              aria-label={t("timeline.zoomOut")}
            >
              <ZoomOut className="h-3.5 w-3.5" />
            </button>
            <span
              data-timeline-zoom-value
              className="min-w-[34px] text-center text-[10px] font-semibold text-[var(--color-text-secondary)]"
            >
              {Math.round(zoom * 100)}%
            </span>
            <button
              type="button"
              data-timeline-zoom-in
              disabled={zoom >= ZOOM_MAX}
              onClick={() => adjustZoom(ZOOM_STEP)}
              className="flex h-7 w-7 items-center justify-center rounded-[7px] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] disabled:opacity-30"
              aria-label={t("timeline.zoomIn")}
            >
              <ZoomIn className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>

      <TimelineTracks
        project={project}
        timeline={effectiveTimeline}
        authorityTimeline={timeline}
        durationTick={timelineDuration}
        playheadTick={playheadTick}
        zoom={zoom}
        snapEnabled={snapEnabled}
        collapsed={collapsed}
        previewOpen={previewOpen}
        editable
        selectedElementId={selectedElementId}
        playbackStates={playbackStates}
        agentWorking={agentWorking.working}
        onPlayheadChange={onPlayheadChange}
        onSelectElement={onSelectElement}
        onActiveElementIdsChange={onActiveElementIdsChange}
        onDragOverridesChange={setDragOverrides}
        onCommitSpans={commitSpans}
        onZoomChange={changeZoom}
      />
    </section>
  );
}
