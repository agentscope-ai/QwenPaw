import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ComponentType, PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import { message } from "antd";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
import {
  AudioWaveform,
  Blend,
  Captions,
  Film,
  MessageSquarePlus,
  Sparkles,
  Wand2,
} from "lucide-react";
import type {
  ProjectDocument,
  TimelineDocument,
  TimelineElementDocument,
  TimelineSpanDocument,
} from "@/contracts/creator";
import {
  classifyElementTrack,
  elementsAtTick,
  elementsOverlappingRange,
  groupDisplayTracks,
  resolveElementVisualMeta,
  TRANSITION_KIND_LABEL,
  type TimelineTrackType,
} from "@/selectors/timelineElementSelectors";
import type { ElementPlaybackStatus } from "@/selectors/elementPlaybackSelectors";
import { ELEMENT_PLAYBACK_STATUS_LABEL } from "@/selectors/elementPlaybackSelectors";
import {
  collectSnapTicks,
  resolveSpanDrag,
  transitionFollowChanges,
  type SpanChange,
  type SpanDragMode,
} from "@/lib/timelineEditing";
import { formatSeconds } from "@/lib/timecode";
import { projectJsonPointer } from "@/lib/projectJsonPointer";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useOnboardingStore } from "@/store/onboardingStore";

interface TimelineSelection {
  startTick: number;
  endTick: number;
  kind: "point" | "range";
}

interface TimelineTracksProps {
  project: ProjectDocument;
  /** Effective timeline for rendering (drag overrides already applied). */
  timeline: TimelineDocument;
  /** Authoritative timeline used for validation and CAS before-values. */
  authorityTimeline: TimelineDocument;
  durationTick: number;
  playheadTick: number;
  zoom: number;
  snapEnabled: boolean;
  collapsed: boolean;
  previewOpen: boolean;
  editable: boolean;
  selectedElementId: string | null;
  playbackStates: Map<string, ElementPlaybackStatus>;
  agentWorking: boolean;
  onPlayheadChange: (tick: number) => void;
  onSelectElement: (elementId: string) => void;
  /**
   * null asks the page to derive "content at the playhead" from
   * timeline + playheadTick instead of pinning a stale explicit list.
   */
  onActiveElementIdsChange: (ids: string[] | null) => void;
  onDragOverridesChange: (
    overrides: Map<string, TimelineSpanDocument> | null,
  ) => void;
  onCommitSpans: (changes: SpanChange[]) => void;
  onZoomChange: (zoom: number) => void;
}

const LABEL_WIDTH = 68;
const CHART_PADDING = 12;
const SELECTION_TOOLBAR_GAP = 6;
const SNAP_THRESHOLD_PX = 8;
const DRAG_START_PX = 3;

/** Reference-design decor per track type: icon + short track code (V1/A1/CC…). */
const TRACK_DECOR: Record<
  TimelineTrackType,
  { code: string; Icon: ComponentType<{ className?: string }> }
> = {
  ai: { code: "AI", Icon: Sparkles },
  clip: { code: "V", Icon: Film },
  subtitle: { code: "CC", Icon: Captions },
  motion: { code: "FX", Icon: Wand2 },
  transition: { code: "XF", Icon: Blend },
  audio: { code: "A", Icon: AudioWaveform },
};

/** Diagonal-stripe overlays mark copy/motion overlays like the design mock. */
const STRIPED_TRACKS = new Set<TimelineTrackType>(["subtitle", "motion"]);

function seconds(tick: number, ticksPerSecond: number): string {
  return formatSeconds(tick, ticksPerSecond);
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

interface BlockDragState {
  pointerId: number;
  elementId: string;
  mode: SpanDragMode;
  startX: number;
  originSpan: TimelineSpanDocument;
  ticksPerPixel: number;
  snapTicks: number[];
  snapThresholdTick: number;
  moved: boolean;
  lastChanges: SpanChange[];
  valid: boolean;
}

export default function TimelineTracks({
  project,
  timeline,
  authorityTimeline,
  durationTick,
  playheadTick,
  zoom,
  snapEnabled,
  collapsed,
  previewOpen,
  editable,
  selectedElementId,
  playbackStates,
  agentWorking,
  onPlayheadChange,
  onSelectElement,
  onActiveElementIdsChange,
  onDragOverridesChange,
  onCommitSpans,
  onZoomChange,
}: TimelineTracksProps) {
  const { t } = useTranslation();
  const [selection, setSelection] = useState<TimelineSelection | null>(null);
  const [toolbarPos, setToolbarPos] = useState<{
    left: number;
    top: number;
  } | null>(null);
  const [pointCandidates, setPointCandidates] = useState<
    TimelineElementDocument[]
  >([]);
  const [snapGuideTick, setSnapGuideTick] = useState<number | null>(null);
  const [dragTip, setDragTip] = useState<{
    startTick: number;
    endTick: number;
  } | null>(null);
  const selectDrag = useRef<{
    pointerId: number;
    startX: number;
    startTick: number;
    moved: boolean;
  } | null>(null);
  const blockDrag = useRef<BlockDragState | null>(null);
  const rulerScrub = useRef<{
    pointerId: number;
    startX: number;
    moved: boolean;
  } | null>(null);
  const zoomAnchor = useRef<{ frac: number; offsetPx: number } | null>(null);
  const suppressClick = useRef<string | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);

  const timelineDuration = Math.max(1, durationTick);
  // Lane/junction skeleton comes from the authoritative document: it cannot
  // change mid-drag, so blocks never remount and lose pointer capture while
  // crossing another clip. Fresh spans (drag overrides) are looked up from the
  // effective timeline at render time.
  const { tracks, junctions } = useMemo(
    () => groupDisplayTracks(authorityTimeline),
    [authorityTimeline],
  );
  const liveElement = (element: TimelineElementDocument) =>
    timeline.elements_by_id[element.element_id] ?? element;
  const junctionCenterTick = (junction: (typeof junctions)[number]) => {
    const current = timeline.elements_by_id[junction.transition.element_id];
    return current
      ? current.span.start_tick + current.span.duration_tick / 2
      : junction.centerTick;
  };
  const totalLanes = tracks.reduce((sum, track) => sum + track.lanes.length, 0);
  const scrollable = totalLanes > 4;

  const laneByElementId = useMemo(() => {
    const map = new Map<string, string>();
    tracks.forEach((track) =>
      track.lanes.forEach((lane) =>
        lane.elements.forEach((element) =>
          map.set(element.element_id, lane.id),
        ),
      ),
    );
    return map;
  }, [tracks]);
  // Global row index per lane in render order; junction badges are positioned
  // vertically between the rows of their from/to elements so the transition
  // visually connects the two clips instead of sitting inside one lane.
  const rowIndexByLaneId = useMemo(() => {
    const map = new Map<string, number>();
    let row = 0;
    tracks.forEach((track) =>
      track.lanes.forEach((lane) => {
        map.set(lane.id, row);
        row += 1;
      }),
    );
    return map;
  }, [tracks]);
  const ROW_HEIGHT = 44;
  const positionedJunctions = useMemo(
    () =>
      junctions.flatMap((junction) => {
        const fromLane = laneByElementId.get(junction.fromId);
        const toLane = laneByElementId.get(junction.toId);
        if (fromLane === undefined || toLane === undefined) return [];
        const fromRow = rowIndexByLaneId.get(fromLane);
        const toRow = rowIndexByLaneId.get(toLane);
        if (fromRow === undefined || toRow === undefined) return [];
        const fromCenter = fromRow * ROW_HEIGHT + ROW_HEIGHT / 2;
        const toCenter = toRow * ROW_HEIGHT + ROW_HEIGHT / 2;
        return [
          {
            junction,
            centerTop: (fromCenter + toCenter) / 2,
            linkTop: Math.min(fromCenter, toCenter),
            linkHeight: Math.abs(toCenter - fromCenter),
          },
        ];
      }),
    [junctions, laneByElementId, rowIndexByLaneId],
  );
  // NLE-style butt-joined display (Premiere/FCP/CapCut): bridged clips overlap
  // in the data (the transition handle), but on screen the outgoing clip is
  // drawn up to the cut point and the incoming clip from it — blocks never
  // stack. Only the drawn box shrinks; spans, labels and drags stay real.
  const displaySpanByElementId = useMemo(() => {
    const map = new Map<string, { startTick: number; endTick: number }>();
    const boxOf = (elementId: string) => {
      const existing = map.get(elementId);
      if (existing) return existing;
      const element = timeline.elements_by_id[elementId];
      if (!element) return null;
      const box = {
        startTick: element.span.start_tick,
        endTick: element.span.start_tick + element.span.duration_tick,
      };
      map.set(elementId, box);
      return box;
    };
    junctions.forEach((junction) => {
      const fromLane = laneByElementId.get(junction.fromId);
      const toLane = laneByElementId.get(junction.toId);
      // Cross-row transitions cannot visually collide; keep their real boxes.
      if (fromLane === undefined || fromLane !== toLane) return;
      const cut = Math.round(junctionCenterTick(junction));
      const from = boxOf(junction.fromId);
      const to = boxOf(junction.toId);
      if (!from || !to) return;
      from.endTick = Math.min(from.endTick, cut);
      to.startTick = Math.max(to.startTick, cut);
    });
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [junctions, laneByElementId, timeline]);

  const laneWidthPx = (): number => {
    const rect = chartRef.current?.getBoundingClientRect();
    if (!rect) return 1;
    return Math.max(
      1,
      (rect.width - LABEL_WIDTH - CHART_PADDING * 2) * Math.max(1, zoom),
    );
  };

  const tickAt = (clientX: number): number => {
    const rect = chartRef.current?.getBoundingClientRect();
    if (!rect) return 0;
    const inner = laneWidthPx();
    const scrollLeft = scrollRef.current?.scrollLeft ?? 0;
    const x = Math.min(
      inner,
      Math.max(
        0,
        clientX - rect.left - CHART_PADDING - LABEL_WIDTH + scrollLeft,
      ),
    );
    return Math.round((x / inner) * timelineDuration);
  };

  const clearSelection = () => {
    setSelection(null);
    setPointCandidates([]);
  };

  // ------------------------------------------------------------------
  // Time-range selection for "add to conversation": drag on empty track
  // area, or Shift+drag anywhere — tracks packed full of clips (the normal
  // single-lane cut) would otherwise leave no blank spot to start from.
  // ------------------------------------------------------------------
  const beginSelection = (event: ReactPointerEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.closest("[data-timeline-selection-toolbar]")) return;
    if (
      !event.shiftKey &&
      target.closest("[data-element-block], [data-transition-junction]")
    )
      return;
    const tick = tickAt(event.clientX);
    selectDrag.current = {
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
    const current = selectDrag.current;
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
    const current = selectDrag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    selectDrag.current = null;
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
      if (endTick > startTick) {
        onActiveElementIdsChange(
          elementsOverlappingRange(timeline, startTick, endTick).map(
            (element) => element.element_id,
          ),
        );
      } else {
        onActiveElementIdsChange(null);
      }
      return;
    }

    onPlayheadChange(tick);
    const candidates = elementsAtTick(timeline, tick);
    setSelection({ kind: "point", startTick: tick, endTick: tick });
    setPointCandidates(collapsed ? candidates : []);
    onActiveElementIdsChange(null);
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
        ? `${startText}s · ${selectedElements.length} ${t(
            "timeline.itemsAtSameTime",
          )}`
        : `${startText}s – ${endText}s · ${selectedElements.length} ${t(
            "timeline.timelineItems",
          )}`,
      ref: timelineRef(timeline),
      field: isPoint
        ? `${timelineRef(timeline)}@${selection.startTick}`
        : `${timelineRef(timeline)}@[${selection.startTick},${
            selection.endTick
          })`,
      path: projectJsonPointer("timelines", "items", timeline.timeline_id),
      start: selection.startTick,
      end: selection.endTick,
      label: isPoint ? t("timeline.timePoint") : t("timeline.timeRange"),
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

  useEffect(() => {
    clearSelection();
  }, [collapsed]);

  // ------------------------------------------------------------------
  // Direct manipulation: dragging a block moves it, dragging its edges trims
  // it. Every change is validated and committed to project.json immediately.
  // ------------------------------------------------------------------
  const beginBlockDrag = (
    event: ReactPointerEvent<HTMLButtonElement>,
    element: TimelineElementDocument,
    mode: SpanDragMode,
  ) => {
    // Shift+drag anywhere starts a time-range selection instead; let the
    // pointer event bubble up to the chart container.
    if (event.shiftKey) return;
    event.stopPropagation();
    if (!editable || event.button !== 0) return;
    const authority = authorityTimeline.elements_by_id[element.element_id];
    if (!authority) return;
    const ticksPerPixel = timelineDuration / laneWidthPx();
    blockDrag.current = {
      pointerId: event.pointerId,
      elementId: element.element_id,
      mode,
      startX: event.clientX,
      originSpan: { ...authority.span },
      ticksPerPixel,
      snapTicks: collectSnapTicks(
        authorityTimeline,
        new Set([element.element_id]),
        [0, playheadTick, timelineDuration],
      ),
      snapThresholdTick: Math.max(
        1,
        Math.round(SNAP_THRESHOLD_PX * ticksPerPixel),
      ),
      moved: false,
      lastChanges: [],
      valid: true,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const moveBlockDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = blockDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (!drag.moved && Math.abs(event.clientX - drag.startX) <= DRAG_START_PX)
      return;
    drag.moved = true;
    const element = authorityTimeline.elements_by_id[drag.elementId];
    if (!element) return;
    const deltaTick = (event.clientX - drag.startX) * drag.ticksPerPixel;
    const result = resolveSpanDrag({
      timeline: authorityTimeline,
      element,
      mode: drag.mode,
      originSpan: drag.originSpan,
      deltaTick,
      snapEnabled,
      snapTicks: drag.snapTicks,
      snapThresholdTick: drag.snapThresholdTick,
    });
    const primary: SpanChange[] = [
      { elementId: drag.elementId, span: result.span },
    ];
    const follow = transitionFollowChanges(authorityTimeline, primary);
    drag.valid = follow.ok;
    drag.lastChanges = follow.ok ? [...primary, ...follow.changes] : primary;
    const overrides = new Map<string, TimelineSpanDocument>();
    drag.lastChanges.forEach((change) =>
      overrides.set(change.elementId, change.span),
    );
    onDragOverridesChange(overrides);
    setSnapGuideTick(result.snapTick);
    setDragTip({
      startTick: result.span.start_tick,
      endTick: result.span.start_tick + result.span.duration_tick,
    });
  };

  const endBlockDrag = (
    event: ReactPointerEvent<HTMLButtonElement>,
    cancelled: boolean,
  ) => {
    const drag = blockDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    blockDrag.current = null;
    setSnapGuideTick(null);
    setDragTip(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (!drag.moved) return;
    suppressClick.current = drag.elementId;
    if (cancelled) {
      onDragOverridesChange(null);
      return;
    }
    if (!drag.valid) {
      const follow = transitionFollowChanges(
        authorityTimeline,
        drag.lastChanges.slice(0, 1),
      );
      message.warning(
        follow.ok === false ? follow.reason : t("timeline.adjustmentFailed"),
      );
      onDragOverridesChange(null);
      return;
    }
    onCommitSpans(drag.lastChanges);
  };

  // ------------------------------------------------------------------
  // Ruler scrubbing (NLE standard): press-drag on the scale row moves the
  // playhead continuously instead of starting a range selection.
  // ------------------------------------------------------------------
  const beginRulerScrub = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    // Shift+drag on the ruler falls through to the range selection.
    if (event.shiftKey) return;
    event.stopPropagation();
    rulerScrub.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    clearSelection();
    onPlayheadChange(tickAt(event.clientX));
  };
  const moveRulerScrub = (event: ReactPointerEvent<HTMLDivElement>) => {
    const scrub = rulerScrub.current;
    if (scrub?.pointerId !== event.pointerId) return;
    if (Math.abs(event.clientX - scrub.startX) > 3) scrub.moved = true;
    onPlayheadChange(tickAt(event.clientX));
  };
  const endRulerScrub = (event: ReactPointerEvent<HTMLDivElement>) => {
    const scrub = rulerScrub.current;
    if (scrub?.pointerId !== event.pointerId) return;
    rulerScrub.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    // A plain click (no scrub) keeps the classic point selection so the
    // "add to conversation" toolbar stays one click away.
    if (scrub.moved) return;
    const tick = tickAt(event.clientX);
    setSelection({ kind: "point", startTick: tick, endTick: tick });
    setPointCandidates(collapsed ? elementsAtTick(timeline, tick) : []);
    onActiveElementIdsChange(null);
  };

  // Ctrl/⌘ + wheel zooms around the pointer (NLE standard). Native listener:
  // React marks wheel events passive, so preventDefault must go through here.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const rect = chart.getBoundingClientRect();
      const scrollLeft = scrollRef.current?.scrollLeft ?? 0;
      const offsetPx = event.clientX - rect.left - CHART_PADDING - LABEL_WIDTH;
      const innerBefore = Math.max(
        1,
        (rect.width - LABEL_WIDTH - CHART_PADDING * 2) * Math.max(1, zoom),
      );
      zoomAnchor.current = {
        frac: Math.min(1, Math.max(0, (offsetPx + scrollLeft) / innerBefore)),
        offsetPx,
      };
      const step = event.deltaY < 0 ? 0.25 : -0.25;
      onZoomChange(Number((zoom + step).toFixed(2)));
    };
    chart.addEventListener("wheel", onWheel, { passive: false });
    return () => chart.removeEventListener("wheel", onWheel);
  }, [zoom, onZoomChange]);

  // After a pointer-anchored zoom, shift the viewport so the tick under the
  // cursor stays put.
  useLayoutEffect(() => {
    const anchor = zoomAnchor.current;
    if (!anchor) return;
    zoomAnchor.current = null;
    const scroll = scrollRef.current;
    if (!scroll) return;
    const innerAfter = laneWidthPx();
    scroll.scrollLeft = Math.max(0, anchor.frac * innerAfter - anchor.offsetPx);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoom]);

  // Keep the playhead visible inside the zoomed viewport.
  useEffect(() => {
    if (zoom <= 1) return;
    const scroll = scrollRef.current;
    if (!scroll) return;
    const inner = laneWidthPx();
    const playheadPx =
      LABEL_WIDTH + (inner * percent(playheadTick, timelineDuration)) / 100;
    const viewStart = scroll.scrollLeft + LABEL_WIDTH + 12;
    const viewEnd = scroll.scrollLeft + scroll.clientWidth - 12;
    if (playheadPx < viewStart || playheadPx > viewEnd) {
      scroll.scrollLeft = Math.max(0, playheadPx - scroll.clientWidth / 2);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playheadTick, zoom, timelineDuration]);

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
      const inner = laneWidthPx();
      const scrollLeft = scrollRef.current?.scrollLeft ?? 0;
      const anchorX =
        rect.left +
        CHART_PADDING +
        LABEL_WIDTH -
        scrollLeft +
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection, timelineDuration, zoom]);

  const scale = useMemo(() => {
    const ticksPerSecond = Math.max(1, timeline.ticks_per_second);
    const durationSeconds = timelineDuration / ticksPerSecond;
    const majorStepSeconds = niceScaleStep(
      durationSeconds / (6 * Math.max(1, zoom)),
    );
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
    };
  }, [timeline.ticks_per_second, timelineDuration, zoom]);

  const playheadFraction = percent(playheadTick, timelineDuration) / 100;

  const renderBlock = (laneElement: TimelineElementDocument) => {
    // Skeleton element comes from the authoritative lanes; spans render from
    // the effective timeline so in-flight drags stay visually live.
    const element = liveElement(laneElement);
    const meta = resolveElementVisualMeta(element);
    const trackType = classifyElementTrack(element);
    const playbackState = playbackStates.get(element.element_id) ?? "pending";
    const displayBox = displaySpanByElementId.get(element.element_id) ?? {
      startTick: element.span.start_tick,
      endTick: element.span.start_tick + element.span.duration_tick,
    };
    const left = percent(displayBox.startTick, timelineDuration);
    const width = Math.max(
      0.7,
      ((displayBox.endTick - displayBox.startTick) / timelineDuration) * 100,
    );
    const selected = element.element_id === selectedElementId;
    // Orphan transitions (dangling from/to) still render as narrow blocks; a
    // crossed-triangle glyph replaces the clipped two-line text.
    const isTransition = element.creation.type === "transition";
    const dragging = blockDrag.current?.elementId === element.element_id;
    const striped = trackType !== null && STRIPED_TRACKS.has(trackType);
    const blockBackground = isTransition
      ? meta.soft
      : striped
      ? `repeating-linear-gradient(135deg, ${meta.color}17 0 6px, transparent 6px 12px), ${meta.soft}`
      : `linear-gradient(135deg, ${meta.color}1f, transparent 44%), ${meta.soft}`;
    return (
      <button
        key={element.element_id}
        type="button"
        data-element-block={element.element_id}
        data-element-block-state={playbackState}
        title={`${element.label || t("timeline.timelineContent")} · ${seconds(
          element.span.start_tick,
          timeline.ticks_per_second,
        )}s – ${seconds(
          element.span.start_tick + element.span.duration_tick,
          timeline.ticks_per_second,
        )}s${
          playbackState === "ready"
            ? ""
            : ` · ${i18n.t(ELEMENT_PLAYBACK_STATUS_LABEL[playbackState])}`
        }${editable ? t("timeline.draggableHint") : ""}`}
        onPointerDown={(event) => {
          const trim = (event.target as HTMLElement)
            .closest("[data-element-trim]")
            ?.getAttribute("data-element-trim");
          beginBlockDrag(
            event,
            element,
            trim === "start"
              ? "trim-start"
              : trim === "end"
              ? "trim-end"
              : "move",
          );
        }}
        onPointerMove={moveBlockDrag}
        onPointerUp={(event) => endBlockDrag(event, false)}
        onPointerCancel={(event) => endBlockDrag(event, true)}
        onClick={(event) => {
          event.stopPropagation();
          if (event.shiftKey) return;
          if (suppressClick.current === element.element_id) {
            suppressClick.current = null;
            return;
          }
          clearSelection();
          onSelectElement(element.element_id);
          onActiveElementIdsChange([element.element_id]);
        }}
        className={`absolute top-[5px] flex h-[34px] min-w-3 touch-none overflow-hidden rounded-md border text-[10px] font-semibold shadow-sm transition ${
          isTransition
            ? "items-center justify-center px-0"
            : "flex-col justify-center px-2 text-left"
        } ${
          selected
            ? "z-[35] border-[var(--color-accent)] ring-2 ring-[var(--color-accent)]/20"
            : "z-10"
        } ${element.enabled ? "" : "opacity-45"} ${
          playbackState === "queued" ? "border-dashed" : ""
        } ${dragging ? "cursor-grabbing" : editable ? "cursor-grab" : ""}`}
        style={{
          left: `${left}%`,
          width: `${Math.min(100 - left, width)}%`,
          color: meta.color,
          borderColor: selected
            ? undefined
            : playbackState === "failed"
            ? "var(--color-danger)"
            : `${meta.color}85`,
          background: blockBackground,
        }}
      >
        {playbackState === "generating" && (
          <i
            aria-hidden
            className="element-generating-stripes pointer-events-none absolute inset-0"
            style={{ color: meta.color }}
          />
        )}
        {trackType === "audio" && (
          <i
            aria-hidden
            data-element-waveform
            className="pointer-events-none absolute inset-x-1.5 bottom-[5px] top-[15px] opacity-50"
            style={{
              color: meta.color,
              background:
                "linear-gradient(135deg, transparent 0 42%, currentColor 43% 49%, transparent 50% 56%, currentColor 57% 63%, transparent 64%) 0 0 / 34px 10px repeat-x",
            }}
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
            <path d="M19 1 L11 6 L19 11 Z" opacity="0.45" />
          </svg>
        ) : (
          <>
            <span className="pointer-events-none min-w-0 truncate">
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
              {element.label || t("timeline.timelineContent")}
            </span>
            <span className="pointer-events-none truncate whitespace-nowrap text-[9px] font-medium opacity-75">
              {seconds(element.span.start_tick, timeline.ticks_per_second)}s –{" "}
              {seconds(
                element.span.start_tick + element.span.duration_tick,
                timeline.ticks_per_second,
              )}
              s
            </span>
          </>
        )}
        {editable && selected && (
          <>
            <i
              data-element-trim="start"
              aria-hidden
              className="absolute inset-y-0 left-0 z-20 w-[7px] cursor-ew-resize rounded-l-[6px] bg-[var(--color-accent)]/85"
            />
            <i
              data-element-trim="end"
              aria-hidden
              className="absolute inset-y-0 right-0 z-20 w-[7px] cursor-ew-resize rounded-r-[6px] bg-[var(--color-accent)]/85"
            />
          </>
        )}
      </button>
    );
  };

  return (
    <>
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
          selectDrag.current = null;
        }}
      >
        <div
          ref={scrollRef}
          data-timeline-zoom-viewport
          className={zoom > 1 ? "overflow-x-auto overscroll-x-contain" : ""}
        >
          <div
            data-timeline-zoom-content
            className="relative"
            style={{ width: `${Math.max(1, zoom) * 100}%` }}
          >
            <div className="relative flex h-7 border-b border-[var(--color-border)]">
              <div className="sticky left-0 z-30 flex w-[68px] shrink-0 items-center border-r border-[var(--color-border)] bg-[var(--color-bg-primary)] pl-2.5 text-[10px] text-[var(--color-text-tertiary)]">
                {t("timeline.trackLabel")}
              </div>
              <div
                data-timeline-scale
                title={t("timeline.rulerScrub")}
                onPointerDown={beginRulerScrub}
                onPointerMove={moveRulerScrub}
                onPointerUp={endRulerScrub}
                onPointerCancel={endRulerScrub}
                className="relative min-w-0 flex-1 cursor-ew-resize touch-none bg-[var(--color-bg-primary)]"
              >
                {scale.ticks.map(({ tick, major }) => (
                  <span
                    key={tick}
                    data-timeline-scale-tick
                    data-major={major ? "true" : "false"}
                    aria-hidden={!major}
                    className="absolute inset-y-0"
                    style={{ left: `${percent(tick, timelineDuration)}%` }}
                  >
                    <i
                      className={`absolute bottom-0 left-0 w-px ${
                        major
                          ? "top-0 bg-[var(--color-border)]"
                          : "h-1.5 bg-[var(--color-border)]/80"
                      }`}
                    />
                    {major && (
                      <b
                        className="absolute top-[3px] whitespace-nowrap text-[9px] font-medium text-[var(--color-text-tertiary)]"
                        style={
                          tick >= timelineDuration ? { right: 4 } : { left: 4 }
                        }
                      >
                        {seconds(tick, timeline.ticks_per_second)}s
                      </b>
                    )}
                  </span>
                ))}
              </div>
            </div>
            <div
              aria-hidden
              data-timeline-grid
              className="pointer-events-none absolute inset-y-0 left-[68px] right-0 top-7 z-0"
            >
              {scale.ticks
                .filter(
                  ({ major, tick }) =>
                    major && tick > 0 && tick < timelineDuration,
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
                <div className="sticky left-0 z-30 flex w-[68px] shrink-0 items-center border-r border-[var(--color-border)] bg-[var(--color-bg-primary)] pl-2.5 text-[10px] font-semibold text-[var(--color-text-tertiary)]">
                  {t("timeline.overview")}
                </div>
                <div
                  className="relative min-w-0 flex-1"
                  aria-label={t("timeline.compactOverviewAriaLabel")}
                >
                  {Object.values(timeline.elements_by_id).map((element) => {
                    const meta = resolveElementVisualMeta(element);
                    const left = percent(
                      element.span.start_tick,
                      timelineDuration,
                    );
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
                  agentWorking ? (
                    <div
                      data-timeline-working
                      className="flex h-14 flex-col items-center justify-center gap-2 text-xs text-[var(--color-text-secondary)]"
                    >
                      <span className="flex items-center gap-1.5">
                        <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-[var(--color-warning)]" />
                        {t("timeline.agentArranging")}
                      </span>
                      <div className="agent-working-shimmer h-1.5 w-3/5 rounded-full bg-[var(--color-bg-secondary)]" />
                    </div>
                  ) : (
                    <div className="flex h-14 items-center justify-center text-xs text-[var(--color-text-tertiary)]">
                      {t("timeline.timelineEmpty")}
                    </div>
                  )
                ) : (
                  <div className="relative">
                    {tracks.map((track) => {
                      const decor = TRACK_DECOR[track.type];
                      return (
                        <div key={track.type} data-track={track.type}>
                          {track.lanes.map((lane, laneIndex) => (
                            <div
                              key={lane.id}
                              className="relative flex h-11 border-b border-[var(--color-border)]/65 last:border-b-0"
                            >
                              <div
                                title={`${track.label}${t(
                                  "timeline.clickSelectRow",
                                )}`}
                                onPointerDown={(event) =>
                                  event.stopPropagation()
                                }
                                onClick={() => {
                                  // Seek first: playhead motion resets the
                                  // page to follow mode, then the explicit
                                  // whole-lane selection pins on top of it.
                                  onPlayheadChange(0);
                                  onActiveElementIdsChange(
                                    lane.elements.map(
                                      (element) => element.element_id,
                                    ),
                                  );
                                }}
                                className="sticky left-0 z-40 flex w-[68px] shrink-0 cursor-pointer items-center gap-1.5 border-r border-[var(--color-border)] bg-[var(--color-bg-primary)] pl-2.5 pr-1 text-[10px] hover:bg-[var(--color-bg-secondary)]"
                              >
                                <decor.Icon
                                  className="h-3 w-3 shrink-0"
                                  aria-hidden
                                />
                                <b
                                  className="font-semibold"
                                  style={{ color: track.color }}
                                >
                                  {decor.code}
                                  {track.lanes.length > 1
                                    ? laneIndex + 1
                                    : track.type === "clip" ||
                                      track.type === "audio"
                                    ? 1
                                    : ""}
                                </b>
                              </div>
                              <div className="relative min-w-0 flex-1">
                                {lane.elements.map(renderBlock)}
                              </div>
                            </div>
                          ))}
                        </div>
                      );
                    })}
                    {/* Junction overlay: each transition bridges its from/to
                        clips — a dashed connector spans both rows, and the
                        badge sits midway between them at the junction tick. */}
                    <div
                      aria-hidden={positionedJunctions.length === 0}
                      className="pointer-events-none absolute inset-y-0 left-[68px] right-0 z-30"
                    >
                      {positionedJunctions.map(
                        ({ junction, centerTop, linkTop, linkHeight }) => {
                          const transition = junction.transition;
                          const kind =
                            transition.creation.type === "transition"
                              ? transition.creation.transition_kind
                              : "";
                          const kindKey = TRANSITION_KIND_LABEL[kind];
                          const kindLabel = kindKey ? i18n.t(kindKey) : kind;
                          const junctionSelected =
                            selectedElementId === transition.element_id;
                          const leftStyle = `${percent(
                            junctionCenterTick(junction),
                            timelineDuration,
                          )}%`;
                          return (
                            <div key={transition.element_id}>
                              {linkHeight > 0 && (
                                <i
                                  data-transition-junction-link={
                                    transition.element_id
                                  }
                                  className={`absolute w-0 -translate-x-1/2 border-l border-dashed ${
                                    junctionSelected
                                      ? "border-[var(--color-accent)]"
                                      : "border-[#6844bd]/55"
                                  }`}
                                  style={{
                                    left: leftStyle,
                                    top: linkTop,
                                    height: linkHeight,
                                  }}
                                />
                              )}
                              <button
                                type="button"
                                data-transition-junction={transition.element_id}
                                title={`${
                                  transition.label || t("timeline.transition")
                                } · ${kindLabel} · ${seconds(
                                  transition.span.duration_tick,
                                  timeline.ticks_per_second,
                                )}s${
                                  editable ? t("timeline.clickEditHint") : ""
                                }`}
                                onPointerDown={(event) =>
                                  beginBlockDrag(event, transition, "move")
                                }
                                onPointerMove={moveBlockDrag}
                                onPointerUp={(event) =>
                                  endBlockDrag(event, false)
                                }
                                onPointerCancel={(event) =>
                                  endBlockDrag(event, true)
                                }
                                onClick={(event) => {
                                  event.stopPropagation();
                                  if (event.shiftKey) return;
                                  if (
                                    suppressClick.current ===
                                    transition.element_id
                                  ) {
                                    suppressClick.current = null;
                                    return;
                                  }
                                  clearSelection();
                                  onSelectElement(transition.element_id);
                                  onActiveElementIdsChange([
                                    transition.element_id,
                                  ]);
                                }}
                                className={`pointer-events-auto absolute flex h-6 w-6 -translate-x-1/2 -translate-y-1/2 touch-none items-center justify-center rounded-[7px] border bg-white transition ${
                                  junctionSelected
                                    ? "border-[var(--color-accent)] text-[var(--color-accent)] shadow-[0_0_0_2px_rgba(255,127,22,0.18)]"
                                    : "border-[#6844bd] text-[#6844bd] shadow-[0_2px_7px_rgba(36,31,26,0.16)] hover:border-[var(--color-accent)] hover:bg-[var(--color-accent-soft)] hover:text-[var(--color-accent)]"
                                } ${!transition.enabled ? "opacity-45" : ""}`}
                                style={{
                                  left: leftStyle,
                                  top: centerTop,
                                }}
                              >
                                <Blend className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          );
                        },
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
            {dragTip && (
              <div
                aria-hidden
                data-timeline-drag-tip
                className="pointer-events-none absolute top-[30px] z-40 -translate-x-1/2 whitespace-nowrap rounded-md bg-black/80 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-white shadow-md"
                style={{
                  left: `calc(68px + (100% - 68px) * ${
                    percent(
                      (dragTip.startTick + dragTip.endTick) / 2,
                      timelineDuration,
                    ) / 100
                  })`,
                }}
              >
                {seconds(dragTip.startTick, timeline.ticks_per_second)}s –{" "}
                {seconds(dragTip.endTick, timeline.ticks_per_second)}s ·{" "}
                {seconds(
                  dragTip.endTick - dragTip.startTick,
                  timeline.ticks_per_second,
                )}
                s
              </div>
            )}
            {snapGuideTick !== null && (
              <div
                aria-hidden
                data-timeline-snap-guide
                className="pointer-events-none absolute bottom-0 top-7 z-[21] w-0 border-l border-dashed border-[var(--color-accent)]"
                style={{
                  left: `calc(68px + (100% - 68px) * ${
                    percent(snapGuideTick, timelineDuration) / 100
                  })`,
                }}
              />
            )}
            <div
              aria-hidden
              data-timeline-playhead
              className="pointer-events-none absolute bottom-0 top-0 z-[22] w-0 -translate-x-1/2 border-l-2 border-[var(--color-accent)] drop-shadow-[0_0_3px_var(--color-accent)]"
              style={{
                left: `calc(68px + (100% - 68px) * ${playheadFraction})`,
              }}
            >
              {/* -1px keeps the cap centered on the 2px border line. */}
              <i className="absolute -left-px top-0 h-2 w-[11px] -translate-x-1/2 rounded-b-[5px] rounded-t-[3px] bg-[var(--color-accent)]" />
            </div>
            {selection?.kind === "range" && (
              <div
                aria-hidden
                data-timeline-selection-range
                className="pointer-events-none absolute bottom-0 top-7 z-[21] border border-[var(--color-accent)] bg-[var(--color-accent)]/15"
                style={{
                  left: `calc(68px + (100% - 68px) * ${
                    percent(selection.startTick, timelineDuration) / 100
                  })`,
                  width: `calc((100% - 68px) * ${
                    (selection.endTick - selection.startTick) / timelineDuration
                  })`,
                }}
              />
            )}
          </div>
        </div>
        {selection &&
          createPortal(
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
                {t("timeline.addToConversation")}
              </button>
            </div>,
            document.body,
          )}
      </div>

      {collapsed && pointCandidates.length > 0 && (
        <div
          data-timeline-point-candidates
          className="flex flex-nowrap items-center gap-1.5 overflow-x-auto border-t border-[var(--color-border)] bg-[var(--color-bg-secondary)]/70 px-3 py-2 text-[11px]"
        >
          <span className="mr-1 shrink-0 text-[var(--color-text-tertiary)]">
            {t("timeline.itemsAtMoment", { count: pointCandidates.length })}
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
    </>
  );
}
