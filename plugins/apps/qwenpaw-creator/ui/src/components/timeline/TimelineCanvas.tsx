import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import {
  ChevronDown,
  ChevronUp,
  Loader2,
  MessageSquarePlus,
  Pause,
  Play,
  Volume2,
  VolumeX,
} from "lucide-react";
import type {
  ProjectDocument,
  TaskView,
  TimelineDocument,
  TimelineElementDocument,
} from "@/contracts/creator";
import { getArtifactVersionMediaUrl } from "@/api/creator";
import {
  elementsAtTick,
  elementsOverlappingRange,
  groupElementsByTracks,
  resolveElementVisualMeta,
  resolveTimelineRender,
} from "@/selectors/timelineElementSelectors";
import type { ElementPlaybackStatus } from "@/selectors/elementPlaybackSelectors";
import {
  ELEMENT_PLAYBACK_STATUS_LABEL,
  resolveElementPlayback,
} from "@/selectors/elementPlaybackSelectors";
import TimelineLivePreview from "@/components/timeline/TimelineLivePreview";
import { projectJsonPointer } from "@/lib/projectJsonPointer";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useOnboardingStore } from "@/store/onboardingStore";
import { useAgentWorkingState } from "@/selectors/agentWorkingSelectors";

interface TimelineSelection {
  startTick: number;
  endTick: number;
  kind: "point" | "range";
}

interface TimelineCanvasProps {
  project: ProjectDocument;
  timeline: TimelineDocument;
  durationTick: number;
  playheadTick: number;
  selectedElementId: string | null;
  activeElementIds: string[];
  previewOpen: boolean;
  tasks: TaskView[];
  onPreviewOpenChange: (open: boolean) => void;
  onPlayheadChange: (tick: number) => void;
  onSelectElement: (elementId: string) => void;
  onActiveElementIdsChange: (ids: string[]) => void;
}

const LABEL_WIDTH = 68;
const CHART_PADDING = 12;
const SELECTION_TOOLBAR_GAP = 6;

function seconds(tick: number, ticksPerSecond: number, digits = 1): string {
  return (tick / ticksPerSecond).toFixed(digits).replace(/\.0$/, "");
}

function percent(tick: number, durationTick: number): number {
  return durationTick > 0
    ? Math.min(100, Math.max(0, (tick / durationTick) * 100))
    : 0;
}

function timelineRef(timeline: TimelineDocument): string {
  return `timeline:${timeline.timeline_id}`;
}

function niceScaleStep(secondsValue: number): number {
  if (!Number.isFinite(secondsValue) || secondsValue <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(secondsValue));
  const normalized = secondsValue / power;
  const nice =
    normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return nice * power;
}

export default function TimelineCanvas({
  project,
  timeline,
  durationTick,
  playheadTick,
  selectedElementId,
  activeElementIds,
  previewOpen,
  tasks,
  onPreviewOpenChange,
  onPlayheadChange,
  onSelectElement,
  onActiveElementIdsChange,
}: TimelineCanvasProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [muted, setMuted] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [finalFrameReady, setFinalFrameReady] = useState(false);
  const [selection, setSelection] = useState<TimelineSelection | null>(null);

  const agentWorking = useAgentWorkingState();
  const [toolbarPos, setToolbarPos] = useState<{
    left: number;
    top: number;
  } | null>(null);
  const [pointCandidates, setPointCandidates] = useState<
    TimelineElementDocument[]
  >([]);
  const drag = useRef<{
    pointerId: number;
    startX: number;
    startTick: number;
    moved: boolean;
  } | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const previewScrubberRef = useRef<HTMLDivElement>(null);
  const previewScrub = useRef<{
    pointerId: number;
    resumeAfterScrub: boolean;
  } | null>(null);
  const tracks = useMemo(() => groupElementsByTracks(timeline), [timeline]);
  const totalLanes = tracks.reduce((sum, track) => sum + track.lanes.length, 0);
  const active = useMemo(
    () => elementsAtTick(timeline, playheadTick),
    [playheadTick, timeline],
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
  const staleFrameIsUnaffected =
    Boolean(renderedVersion?.stale) &&
    pendingAffectedElementIds.size > 0 &&
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
    Object.values(timeline.elements_by_id).forEach((element) => {
      states.set(
        element.element_id,
        resolveElementPlayback(project, timeline, element, tasks).status,
      );
    });
    return states;
  }, [project, tasks, timeline]);
  const scrollable = totalLanes > 4;
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

  const tickAt = (clientX: number): number => {
    const rect = chartRef.current?.getBoundingClientRect();
    if (!rect) return 0;
    const inner = Math.max(1, rect.width - LABEL_WIDTH - CHART_PADDING * 2);
    const x = Math.min(
      inner,
      Math.max(0, clientX - rect.left - CHART_PADDING - LABEL_WIDTH),
    );
    return Math.round((x / inner) * timelineDuration);
  };

  const clearSelection = () => {
    setSelection(null);
    setPointCandidates([]);
  };

  const beginSelection = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (
      (event.target as HTMLElement).closest(
        "[data-element-block], [data-timeline-selection-toolbar]",
      )
    )
      return;
    const tick = tickAt(event.clientX);
    drag.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startTick: tick,
      moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setSelection(null);
    setPointCandidates([]);
  };

  const moveSelection = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    if (Math.abs(event.clientX - current.startX) > 5) current.moved = true;
    if (!current.moved) return;
    const tick = tickAt(event.clientX);
    setSelection({
      kind: "range",
      startTick: Math.min(current.startTick, tick),
      endTick: Math.max(current.startTick, tick),
    });
  };

  const endSelection = (event: ReactPointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    drag.current = null;
    const tick = tickAt(event.clientX);
    if (current.moved) {
      const startTick = Math.min(current.startTick, tick);
      const endTick = Math.max(current.startTick, tick);
      setSelection(
        endTick > startTick
          ? { kind: "range", startTick, endTick }
          : { kind: "point", startTick, endTick: startTick },
      );
      setPointCandidates([]);
      const selectedElements =
        endTick > startTick
          ? elementsOverlappingRange(timeline, startTick, endTick)
          : elementsAtTick(timeline, startTick);
      const elementIds = selectedElements.map((element) => element.element_id);
      onActiveElementIdsChange(elementIds);
      return;
    }

    onPlayheadChange(tick);
    const candidates = elementsAtTick(timeline, tick);
    setSelection({ kind: "point", startTick: tick, endTick: tick });
    setPointCandidates(collapsed ? candidates : []);
    const elementIds = candidates.map((element) => element.element_id);
    onActiveElementIdsChange(elementIds);
  };

  const addSelectionToConversation = () => {
    if (!selection) return;
    const selectedElements =
      selection.kind === "point"
        ? elementsAtTick(timeline, selection.startTick)
        : elementsOverlappingRange(
            timeline,
            selection.startTick,
            selection.endTick,
          );
    const isPoint = selection.kind === "point";
    const startText = seconds(selection.startTick, timeline.ticks_per_second);
    const endText = seconds(selection.endTick, timeline.ticks_per_second);
    const attachment = {
      kind: isPoint ? ("timeline_point" as const) : ("timeline_range" as const),
      text: isPoint
        ? `${startText}s · ${selectedElements.length} 项同时出现的内容`
        : `${startText}s – ${endText}s · ${selectedElements.length} 项时间线内容`,
      ref: timelineRef(timeline),
      field: isPoint
        ? `${timelineRef(timeline)}@${selection.startTick}`
        : `${timelineRef(timeline)}@[${selection.startTick},${
            selection.endTick
          })`,
      path: projectJsonPointer("timelines", "items", timeline.timeline_id),
      start: selection.startTick,
      end: selection.endTick,
      label: isPoint ? "时间点" : "时间区间",
      timelineId: timeline.timeline_id,
      startTick: selection.startTick,
      endTick: selection.endTick,
      elementIds: selectedElements.map((element) => element.element_id),
    };
    useAgentDockUiStore.getState().setSelection(attachment);
    useCreatorInteractionStore.getState().setSelection(attachment);
    clearSelection();
  };

  useEffect(() => {
    const close = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      if (
        chartRef.current?.contains(target) ||
        target.closest("[data-timeline-selection-toolbar]") ||
        target.closest("[data-timeline-point-candidates]")
      )
        return;
      clearSelection();
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

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

  useLayoutEffect(() => {
    if (!selection) {
      setToolbarPos(null);
      return;
    }
    const update = () => {
      const rect = chartRef.current?.getBoundingClientRect();
      const bar = toolbarRef.current;
      if (!rect || !bar) return;
      const width = bar.offsetWidth || 116;
      const height = bar.offsetHeight || 32;
      const anchorTick =
        selection.kind === "point" ? selection.startTick : selection.endTick;
      const inner = Math.max(1, rect.width - LABEL_WIDTH - CHART_PADDING * 2);
      const anchorX =
        rect.left +
        CHART_PADDING +
        LABEL_WIDTH +
        (inner * percent(anchorTick, timelineDuration)) / 100;
      const rightSide = anchorX + 8;
      const left =
        rightSide + width <= window.innerWidth - 8
          ? rightSide
          : Math.max(8, anchorX - width - 8);
      const above = rect.top - height - SELECTION_TOOLBAR_GAP;
      const top =
        above >= 8
          ? above
          : Math.min(
              Math.max(8, rect.top + SELECTION_TOOLBAR_GAP),
              window.innerHeight - height - 8,
            );
      setToolbarPos({ left, top });
    };
    update();
    window.addEventListener("resize", update);
    document.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      document.removeEventListener("scroll", update, true);
    };
  }, [selection, timelineDuration]);

  const scale = useMemo(() => {
    const ticksPerSecond = Math.max(1, timeline.ticks_per_second);
    const durationSeconds = timelineDuration / ticksPerSecond;
    const majorStepSeconds = niceScaleStep(durationSeconds / 6);
    const majorStepTick = Math.max(
      1,
      Math.round(majorStepSeconds * ticksPerSecond),
    );
    const minorStepTick = Math.max(1, Math.round(majorStepTick / 5));
    const ticks: Array<{ tick: number; major: boolean }> = [];
    for (let tick = 0; tick <= timelineDuration; tick += minorStepTick) {
      ticks.push({
        tick,
        major: tick % majorStepTick === 0,
      });
    }
    if (ticks[ticks.length - 1]?.tick !== timelineDuration) {
      ticks.push({ tick: timelineDuration, major: true });
    }
    return {
      ticks,
      labelDigits: majorStepSeconds < 1 ? 1 : 0,
    };
  }, [timeline.ticks_per_second, timelineDuration]);

  return (
    <section
      data-timeline-panel
      className={`mx-4 mt-3 shrink-0 overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-primary)] shadow-sm ${
        previewOpen ? "flex max-h-[66vh] flex-col" : ""
      }`}
    >
      <div className="flex min-h-10 flex-wrap items-center justify-between gap-2 border-b border-[var(--color-border)] px-3 py-1.5 text-[11px] text-[var(--color-text-tertiary)]">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <b className="text-[var(--color-text-primary)]">时间轴</b>
          <span className="rounded-full bg-[var(--color-accent-soft)] px-2 py-0.5 font-semibold text-[var(--color-accent)]">
            {seconds(playheadTick, timeline.ticks_per_second)}s · 该时刻有
            {activeElementIds.length}项内容
          </span>
          <span
            className={`rounded-full bg-[var(--color-bg-secondary)] px-2 py-0.5 ${
              scrollable ? "ring-1 ring-[var(--color-border)]" : ""
            }`}
          >
            {tracks.length} 轨{scrollable ? " · 可上下滚动" : ""}
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 pr-3">
          <div className="hidden flex-wrap items-center gap-2 xl:flex">
            {tracks.map((track) => (
              <span key={track.type} className="whitespace-nowrap">
                <i
                  className="mr-1 inline-block h-2 w-2 rounded-sm"
                  style={{ background: track.color }}
                />
                {track.label}
              </span>
            ))}
          </div>
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
            {previewOpen ? "收起预览" : "视频预览"}
          </button>
          <button
            type="button"
            onClick={() => {
              setCollapsed((value) => !value);
              clearSelection();
            }}
            className="rounded-md border border-[var(--color-border)] px-2 py-1 font-semibold text-[var(--color-text-secondary)]"
          >
            {collapsed ? "展开时间轴" : "收起时间轴"}
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
              timeline={timeline}
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
              <span>暂无成片预览</span>
            </div>
          )}
          {previewMode === "final" && renderUrl && !finalPreviewReady && (
            <div
              data-final-preview-incomplete
              role="status"
              aria-live="polite"
              className="absolute inset-0 z-[5] flex flex-col items-center justify-center gap-2 bg-[radial-gradient(circle_at_center,#2b2521_0,#161210_62%,#0d0b0a_100%)] px-6 text-center"
            >
              <Loader2 className="h-7 w-7 animate-spin text-white/75" />
              <span className="text-sm font-semibold text-white/90">
                正在定位画面
              </span>
              <span className="text-xs leading-5 text-white/60">
                成片已渲染完成，正在加载该时间点的画面，无需重新渲染。
              </span>
            </div>
          )}
          <div
            data-preview-source-chip
            className="absolute left-3 top-3 z-10 flex items-center gap-1.5 rounded-full border border-white/20 bg-black/45 px-2.5 py-1 text-[11px] font-semibold text-white/85 backdrop-blur"
            title={
              previewMode === "final"
                ? renderedVersion?.stale
                  ? "当前时间点未受本次修改影响，显示上一版已完成成片"
                  : "正在播放已合成的成片"
                : "实时拼装与成片同口径渲染；成片合成后自动切换"
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
                ? "未受影响 · 已完成画面"
                : "成片"
              : renderedVersion?.stale
              ? "内容已更新 · 实时预览"
              : "实时预览"}
          </div>
          <div className="absolute inset-x-0 bottom-0 z-20 flex items-center gap-2 bg-gradient-to-b from-transparent to-black/80 px-4 pb-3 pt-12">
            <button
              type="button"
              disabled={
                previewMode === "final"
                  ? !videoRef.current && !renderUrl
                  : timelineDuration <= 1
              }
              onClick={() => {
                if (previewMode === "live") {
                  if (!playing && playheadTick >= timelineDuration)
                    onPlayheadChange(0);
                  setPlaying((value) => !value);
                  return;
                }
                const video = videoRef.current;
                if (!video) return;
                if (video.paused) void video.play();
                else video.pause();
              }}
              className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-accent)] text-white disabled:opacity-40"
              aria-label="播放或暂停预览"
            >
              {playing ? (
                <Pause className="h-3.5 w-3.5" />
              ) : (
                <Play className="h-3.5 w-3.5 fill-current" />
              )}
            </button>
            <button
              type="button"
              onClick={() => setMuted((value) => !value)}
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/25 bg-black/30 text-white"
              aria-label={muted ? "取消静音" : "静音"}
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
              aria-label="拖动预览时间轴"
              aria-valuemin={0}
              aria-valuemax={timelineDuration}
              aria-valuenow={Math.min(playheadTick, timelineDuration)}
              aria-valuetext={`${seconds(
                playheadTick,
                timeline.ticks_per_second,
              )} 秒`}
              onPointerDown={beginPreviewScrub}
              onPointerMove={movePreviewScrub}
              onPointerUp={(event) => finishPreviewScrub(event, true)}
              onPointerCancel={(event) => finishPreviewScrub(event, false)}
              onKeyDown={movePreviewScrubberByKeyboard}
              className="relative h-7 flex-1 cursor-pointer touch-none rounded-full focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent)]"
            >
              <span className="pointer-events-none absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 overflow-hidden rounded-full bg-white/30">
                <i
                  className="block h-full rounded-full bg-[var(--color-accent)]"
                  style={{
                    width: `${percent(playheadTick, timelineDuration)}%`,
                  }}
                />
              </span>
              <i
                aria-hidden
                className="pointer-events-none absolute top-1/2 block h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-[var(--color-accent)] shadow-sm"
                style={{
                  left: `${percent(playheadTick, timelineDuration)}%`,
                }}
              />
            </div>
            <span className="font-mono text-[11px] text-white">
              {seconds(playheadTick, timeline.ticks_per_second)} /{" "}
              {seconds(timelineDuration, timeline.ticks_per_second)}s
            </span>
          </div>
        </div>
      )}

      <div
        ref={chartRef}
        data-timeline-chart
        className={`relative shrink-0 cursor-crosshair select-none px-3 pb-2 ${
          previewOpen ? "max-h-[280px] overflow-hidden" : ""
        }`}
        onPointerDown={beginSelection}
        onPointerMove={moveSelection}
        onPointerUp={endSelection}
        onPointerCancel={() => {
          drag.current = null;
        }}
      >
        <div
          data-timeline-scale
          className="relative ml-[68px] h-7 border-b border-[var(--color-border)]"
        >
          {scale.ticks.map(({ tick, major }) => (
            <span
              key={tick}
              data-timeline-scale-tick
              data-major={major ? "true" : "false"}
              aria-hidden={!major}
              className="absolute inset-y-0 -translate-x-1/2"
              style={{ left: `${percent(tick, timelineDuration)}%` }}
            >
              <i
                className={`absolute bottom-0 left-1/2 w-px -translate-x-1/2 ${
                  major
                    ? "h-2.5 bg-[var(--color-border-strong)]"
                    : "h-1.5 bg-[var(--color-border)]"
                }`}
              />
              {major && (
                <b className="absolute left-1/2 top-0 -translate-x-1/2 whitespace-nowrap text-[9px] font-medium text-[var(--color-text-tertiary)]">
                  {seconds(tick, timeline.ticks_per_second, scale.labelDigits)}s
                </b>
              )}
            </span>
          ))}
        </div>
        <div
          aria-hidden
          data-timeline-grid
          className="pointer-events-none absolute bottom-2 top-7 z-0"
          style={{
            left: CHART_PADDING + LABEL_WIDTH,
            right: CHART_PADDING,
          }}
        >
          {scale.ticks
            .filter(
              ({ major, tick }) => major && tick > 0 && tick < timelineDuration,
            )
            .map(({ tick }) => (
              <i
                key={tick}
                className="absolute inset-y-0 w-px bg-[var(--color-border)]/45"
                style={{ left: `${percent(tick, timelineDuration)}%` }}
              />
            ))}
        </div>
        {collapsed ? (
          <div className="relative flex h-8 border-b border-[var(--color-border)]/65">
            <div className="flex w-[68px] shrink-0 items-center justify-center text-[10px] font-semibold text-[var(--color-text-tertiary)]">
              概览
            </div>
            <div
              className="relative min-w-0 flex-1"
              aria-label="紧凑时间轴概览；点击任意时刻查看同时出现的内容"
            >
              {Object.values(timeline.elements_by_id).map((element) => {
                const meta = resolveElementVisualMeta(element);
                const left = percent(element.span.start_tick, timelineDuration);
                const width = Math.max(
                  0.7,
                  (element.span.duration_tick / timelineDuration) * 100,
                );
                return (
                  <i
                    key={element.element_id}
                    aria-hidden
                    className={`pointer-events-none absolute inset-y-2 rounded-sm ${
                      element.enabled ? "opacity-55" : "opacity-20"
                    }`}
                    style={{
                      left: `${left}%`,
                      width: `${Math.min(100 - left, width)}%`,
                      background: meta.color,
                    }}
                  />
                );
              })}
            </div>
          </div>
        ) : (
          <div
            className={
              scrollable
                ? `${
                    previewOpen ? "max-h-[180px]" : "max-h-[320px]"
                  } overflow-y-auto overscroll-contain [scrollbar-gutter:stable]`
                : ""
            }
          >
            {tracks.length === 0 ? (
              agentWorking.working ? (
                <div
                  data-timeline-working
                  className="flex h-14 flex-col items-center justify-center gap-2 text-xs text-[var(--color-text-secondary)]"
                >
                  <span className="flex items-center gap-1.5">
                    <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-[var(--color-warning)]" />
                    Agent 正在编排时间轴，内容生成后会自动出现
                  </span>
                  <div className="agent-working-shimmer h-1.5 w-3/5 rounded-full bg-[var(--color-bg-secondary)]" />
                </div>
              ) : (
                <div className="flex h-14 items-center justify-center text-xs text-[var(--color-text-tertiary)]">
                  时间轴中还没有内容
                </div>
              )
            ) : (
              tracks.map((track) => (
                <div key={track.type} data-track={track.type}>
                  {track.lanes.map((lane, laneIndex) => (
                    <div
                      key={lane.id}
                      className="relative flex h-[35px] border-b border-[var(--color-border)]/65 last:border-b-0"
                    >
                      <div
                        title={`选取整行 ${track.label}`}
                        onPointerDown={(event) => event.stopPropagation()}
                        onClick={() => {
                          const laneElementIds = lane.elements.map(
                            (element) => element.element_id,
                          );
                          onActiveElementIdsChange(laneElementIds);
                          onPlayheadChange(0);
                        }}
                        className="flex w-[68px] shrink-0 items-center justify-center text-[10px] font-semibold hover:text-[12px] hover:font-bold"
                        style={{ color: track.color }}
                      >
                        {track.label}-{laneIndex + 1}
                      </div>
                      <div className="relative min-w-0 flex-1">
                        {lane.elements.map((element) => {
                          const meta = resolveElementVisualMeta(element);
                          const playbackState =
                            playbackStates.get(element.element_id) ?? "pending";
                          const left = percent(
                            element.span.start_tick,
                            timelineDuration,
                          );
                          const width = Math.max(
                            0.7,
                            (element.span.duration_tick / timelineDuration) *
                              100,
                          );
                          const selected =
                            element.element_id === selectedElementId;
                          // Transition blocks are usually under 2% wide, so two lines
                          // of text get clipped into a solid color block; use a centered
                          // crossed-triangle transition glyph instead — hover still shows
                          // the full title tooltip.
                          const isTransition =
                            element.creation.type === "transition";
                          return (
                            <button
                              key={element.element_id}
                              type="button"
                              data-element-block={element.element_id}
                              data-element-block-state={playbackState}
                              title={`${
                                element.label || "时间线内容"
                              } · ${seconds(
                                element.span.start_tick,
                                timeline.ticks_per_second,
                              )}s – ${seconds(
                                element.span.start_tick +
                                  element.span.duration_tick,
                                timeline.ticks_per_second,
                              )}s${
                                playbackState === "ready"
                                  ? ""
                                  : ` · ${ELEMENT_PLAYBACK_STATUS_LABEL[playbackState]}`
                              }`}
                              onPointerDown={(event) => event.stopPropagation()}
                              onClick={(event) => {
                                event.stopPropagation();
                                // Element selection reuses the single playhead; the old
                                // point/range selection no longer leaves a separate marker line.
                                clearSelection();
                                onSelectElement(element.element_id);
                                onActiveElementIdsChange([element.element_id]);
                              }}
                              className={`absolute top-0.5 flex h-[30px] min-w-3 overflow-hidden rounded-[7px] border text-[10px] font-semibold shadow-sm transition ${
                                isTransition
                                  ? "items-center justify-center px-0"
                                  : "flex-col justify-center px-2 text-left"
                              } ${
                                selected
                                  ? "z-20 border-[var(--color-accent)] ring-2 ring-[var(--color-accent)]/20"
                                  : "z-10"
                              } ${element.enabled ? "" : "opacity-45"} ${
                                playbackState === "queued"
                                  ? "border-dashed"
                                  : ""
                              }`}
                              style={{
                                left: `${left}%`,
                                width: `${Math.min(100 - left, width)}%`,
                                color: meta.color,
                                borderColor: selected
                                  ? undefined
                                  : playbackState === "failed"
                                  ? "var(--color-danger)"
                                  : `${meta.color}80`,
                                background: meta.soft,
                              }}
                            >
                              {playbackState === "generating" && (
                                <i
                                  aria-hidden
                                  className="element-generating-stripes pointer-events-none absolute inset-0"
                                  style={{ color: meta.color }}
                                />
                              )}
                              {isTransition ? (
                                <svg
                                  aria-hidden
                                  data-transition-glyph
                                  viewBox="0 0 20 12"
                                  className="h-3 w-5 shrink-0"
                                  fill="currentColor"
                                >
                                  <path d="M1 1 L9 6 L1 11 Z" opacity="0.9" />
                                  <path
                                    d="M19 1 L11 6 L19 11 Z"
                                    opacity="0.45"
                                  />
                                </svg>
                              ) : (
                                <>
                                  <span className="min-w-0 truncate">
                                    {(playbackState === "generating" ||
                                      playbackState === "queued") && (
                                      <span
                                        aria-hidden
                                        className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--color-warning)] align-middle"
                                      />
                                    )}
                                    {playbackState === "failed" && (
                                      <span
                                        aria-hidden
                                        className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-[var(--color-danger)] align-middle"
                                      />
                                    )}
                                    {element.label || "时间线内容"}
                                  </span>
                                  <span className="truncate whitespace-nowrap text-[9px] font-medium opacity-75">
                                    {seconds(
                                      element.span.start_tick,
                                      timeline.ticks_per_second,
                                    )}
                                    s –{" "}
                                    {seconds(
                                      element.span.start_tick +
                                        element.span.duration_tick,
                                      timeline.ticks_per_second,
                                    )}
                                    s
                                  </span>
                                </>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              ))
            )}
          </div>
        )}
        <div
          aria-hidden
          data-timeline-playhead
          className="pointer-events-none absolute bottom-2 top-7 z-[22] w-0 -translate-x-1/2 border-l-2 border-[var(--color-accent)] drop-shadow-[0_0_3px_var(--color-accent)]"
          style={{
            left: `calc(${CHART_PADDING + LABEL_WIDTH}px + (100% - ${
              LABEL_WIDTH + CHART_PADDING * 2
            }px) * ${percent(playheadTick, timelineDuration) / 100})`,
          }}
        />
        {selection && (
          <>
            {selection.kind === "range" && (
              <div
                aria-hidden
                data-timeline-selection-range
                className="pointer-events-none absolute bottom-2 top-7 z-[21] border border-[var(--color-accent)] bg-[var(--color-accent)]/15"
                style={{
                  left: `calc(${CHART_PADDING + LABEL_WIDTH}px + (100% - ${
                    LABEL_WIDTH + CHART_PADDING * 2
                  }px) * ${
                    percent(selection.startTick, timelineDuration) / 100
                  })`,
                  width: `calc((100% - ${
                    LABEL_WIDTH + CHART_PADDING * 2
                  }px) * ${
                    (selection.endTick - selection.startTick) / timelineDuration
                  })`,
                }}
              />
            )}
            {createPortal(
              <div
                ref={toolbarRef}
                data-timeline-selection-toolbar
                className="flex flex-col rounded-lg border border-[var(--color-border)] bg-white p-0.5 shadow-lg"
                style={{
                  position: "fixed",
                  top: toolbarPos?.top ?? -9999,
                  left: toolbarPos?.left ?? -9999,
                  visibility: toolbarPos ? "visible" : "hidden",
                  // Above the tour mask (antd Tour defaults to 1001) so the bar is
                  // visible when box-selecting a time range during the tour.
                  zIndex: 1100,
                }}
              >
                <button
                  type="button"
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={(event) => {
                    event.stopPropagation();
                    useOnboardingStore
                      .getState()
                      .markHintSeen("addToConversation");
                    addSelectionToConversation();
                  }}
                  className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium hover:bg-[var(--color-accent-soft)] hover:text-[var(--color-accent)]"
                >
                  <MessageSquarePlus className="h-3.5 w-3.5" />
                  添加到对话
                </button>
              </div>,
              document.body,
            )}
          </>
        )}
      </div>

      {collapsed && pointCandidates.length > 0 && (
        <div
          data-timeline-point-candidates
          className="flex flex-nowrap items-center gap-1.5 overflow-x-auto border-t border-[var(--color-border)] bg-[var(--color-bg-secondary)]/70 px-3 py-2 text-[11px]"
        >
          <span className="mr-1 shrink-0 text-[var(--color-text-tertiary)]">
            该时刻有 {pointCandidates.length} 项内容：
          </span>
          {pointCandidates.map((element) => {
            const meta = resolveElementVisualMeta(element);
            return (
              <button
                key={element.element_id}
                type="button"
                onClick={() => onSelectElement(element.element_id)}
                className={`max-w-48 shrink-0 truncate rounded-full border px-2 py-0.5 font-medium ${
                  selectedElementId === element.element_id
                    ? "border-[var(--color-accent)] text-[var(--color-accent)]"
                    : "border-[var(--color-border)] text-[var(--color-text-secondary)]"
                }`}
                style={{ background: meta.soft }}
              >
                {element.label || element.element_id}
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
