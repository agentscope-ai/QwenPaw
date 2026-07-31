import type {
  ArtifactSlotDocument,
  ArtifactVersionDocument,
  ElementCreationDocument,
  ProjectDocument,
  TimelineDocument,
  TimelineElementDocument,
} from "@/contracts/creator";

export interface DisplayLane {
  id: string;
  elements: TimelineElementDocument[];
}

export interface ResolvedArtifactOutput {
  name: string;
  slot: ArtifactSlotDocument;
  selected: ArtifactVersionDocument | null;
}

export function selectPrimaryTimeline(
  project: ProjectDocument | null | undefined,
): TimelineDocument | null {
  if (!project) return null;
  const orderedId = project.timelines.order.find(
    (id) => project.timelines.items[id],
  );
  if (orderedId) return project.timelines.items[orderedId];
  return Object.values(project.timelines.items)[0] ?? null;
}

export function timelineEndTick(
  timeline: TimelineDocument | null | undefined,
): number {
  if (!timeline) return 0;
  return Object.values(timeline.elements_by_id).reduce(
    (end, element) =>
      element.enabled
        ? Math.max(end, element.span.start_tick + element.span.duration_tick)
        : end,
    0,
  );
}

export function orderedTimelineElements(
  timeline: TimelineDocument | null | undefined,
): TimelineElementDocument[] {
  if (!timeline) return [];
  return Object.values(timeline.elements_by_id).sort(
    (left, right) =>
      left.span.start_tick - right.span.start_tick ||
      right.z_index - left.z_index ||
      left.element_id.localeCompare(right.element_id),
  );
}

export function elementsAtTick(
  timeline: TimelineDocument | null | undefined,
  tick: number,
  includeDisabled = false,
): TimelineElementDocument[] {
  if (!timeline || !Number.isFinite(tick) || tick < 0) return [];
  return orderedTimelineElements(timeline).filter((element) => {
    const end = element.span.start_tick + element.span.duration_tick;
    return (
      (includeDisabled || element.enabled) &&
      element.span.start_tick <= tick &&
      tick < end
    );
  });
}

export function elementsOverlappingRange(
  timeline: TimelineDocument | null | undefined,
  startTick: number,
  endTick: number,
): TimelineElementDocument[] {
  if (!timeline || endTick <= startTick) return [];
  return orderedTimelineElements(timeline).filter(
    (element) =>
      element.enabled &&
      element.span.start_tick < endTick &&
      startTick < element.span.start_tick + element.span.duration_tick,
  );
}

/** Frontend-only lane packing. Lanes are not persisted Tracks. */
export function packDisplayLanes(
  timeline: TimelineDocument | null | undefined,
): DisplayLane[] {
  const lanes: Array<{ endTick: number; elements: TimelineElementDocument[] }> =
    [];
  orderedTimelineElements(timeline).forEach((element) => {
    const lane = lanes.find(
      (candidate) => candidate.endTick <= element.span.start_tick,
    );
    const endTick = element.span.start_tick + element.span.duration_tick;
    if (lane) {
      lane.elements.push(element);
      lane.endTick = endTick;
    } else {
      lanes.push({ endTick, elements: [element] });
    }
  });
  return lanes.map((lane, index) => ({
    id: `L${index + 1}`,
    elements: lane.elements,
  }));
}

export type TimelineTrackType =
  | "subtitle"
  | "motion"
  | "clip"
  | "ai"
  | "transition"
  | "audio";

export const TRACK_ORDER: TimelineTrackType[] = [
  "ai",
  "clip",
  "subtitle",
  "motion",
  "transition",
  "audio",
];

export const TRACK_TYPE_META: Record<
  TimelineTrackType,
  { label: string; color: string; soft: string }
> = {
  ai: { label: "AI 画面", color: "#ff7f16", soft: "rgba(255,127,22,.12)" },
  clip: { label: "素材剪辑", color: "#3b82f6", soft: "rgba(59,130,246,.12)" },
  subtitle: { label: "字幕", color: "#8b5cf6", soft: "rgba(139,92,246,.12)" },
  motion: { label: "动效", color: "#f59e0b", soft: "rgba(245,158,11,.12)" },
  transition: { label: "转场", color: "#0d9488", soft: "rgba(13,148,136,.12)" },
  audio: { label: "音频", color: "#12b76a", soft: "rgba(18,183,106,.12)" },
};

export function classifyElementTrack(
  element: TimelineElementDocument,
): TimelineTrackType | null {
  const { creation } = element;
  switch (creation.type) {
    case "r2v":
      return "ai";
    case "edit":
      return "clip";
    case "transition":
      return "transition";
    case "audio":
      return "audio";
    case "overlay":
      if (
        creation.overlay_kind === "pet_os" ||
        creation.overlay_kind === "interview_summary"
      ) {
        return "subtitle";
      }
      if (
        creation.overlay_kind === "motion" ||
        creation.overlay_kind === "media"
      ) {
        return "motion";
      }
      return null;
    default:
      return null;
  }
}

const trackRank = new Map(TRACK_ORDER.map((type, index) => [type, index]));

export function trackOrderedTimelineElements(
  timeline: TimelineDocument | null | undefined,
): TimelineElementDocument[] {
  if (!timeline) return [];
  return Object.values(timeline.elements_by_id).sort((left, right) => {
    const leftTrack = classifyElementTrack(left);
    const rightTrack = classifyElementTrack(right);
    const leftRank =
      leftTrack !== null
        ? trackRank.get(leftTrack) ?? TRACK_ORDER.length
        : TRACK_ORDER.length;
    const rightRank =
      rightTrack !== null
        ? trackRank.get(rightTrack) ?? TRACK_ORDER.length
        : TRACK_ORDER.length;
    return (
      leftRank - rightRank ||
      left.span.start_tick - right.span.start_tick ||
      right.z_index - left.z_index ||
      left.element_id.localeCompare(right.element_id)
    );
  });
}

export interface TimelineTrack {
  type: TimelineTrackType;
  label: string;
  color: string;
  soft: string;
  lanes: DisplayLane[];
}

export function resolveElementVisualMeta(element: TimelineElementDocument): {
  label: string;
  color: string;
  soft: string;
} {
  const trackType = classifyElementTrack(element);
  if (trackType) return TRACK_TYPE_META[trackType];
  if (element.creation.type === "overlay") {
    const kind = element.creation.overlay_kind;
    if (kind === "pet_os" || kind === "interview_summary") {
      return TRACK_TYPE_META.subtitle;
    }
    if (kind === "motion" || kind === "media") {
      return TRACK_TYPE_META.motion;
    }
  }
  return ELEMENT_TYPE_META[
    element.creation.type as Exclude<ElementCreationDocument["type"], "overlay">
  ];
}

export function groupElementsByTracks(
  timeline: TimelineDocument | null | undefined,
): TimelineTrack[] {
  if (!timeline) return [];
  const grouped = new Map<TimelineTrackType, TimelineElementDocument[]>();
  for (const element of orderedTimelineElements(timeline)) {
    const trackType = classifyElementTrack(element);
    if (!trackType) continue;
    const list = grouped.get(trackType);
    if (list) list.push(element);
    else grouped.set(trackType, [element]);
  }
  return TRACK_ORDER.filter((type) => grouped.has(type)).map((type) => {
    const elements = grouped.get(type)!;
    const meta = TRACK_TYPE_META[type];
    const laneMap: Array<{
      endTick: number;
      elements: TimelineElementDocument[];
    }> = [];
    for (const element of elements) {
      const lane = laneMap.find(
        (candidate) => candidate.endTick <= element.span.start_tick,
      );
      const endTick = element.span.start_tick + element.span.duration_tick;
      if (lane) {
        lane.elements.push(element);
        lane.endTick = endTick;
      } else {
        laneMap.push({ endTick, elements: [element] });
      }
    }
    return {
      type,
      label: meta.label,
      color: meta.color,
      soft: meta.soft,
      lanes: laneMap.map((lane, index) => ({
        id: `${type}-${index + 1}`,
        elements: lane.elements,
      })),
    };
  });
}

export function selectedSlotVersion(
  project: ProjectDocument,
  slotId: string,
): ResolvedArtifactOutput | null {
  const slot = project.assets.artifact_slots_by_id[slotId];
  if (!slot) return null;
  return {
    name: slot.kind,
    slot,
    selected: slot.selected_version_id
      ? project.assets.artifact_versions_by_id[slot.selected_version_id] ?? null
      : null,
  };
}

export function resolveElementOutputs(
  project: ProjectDocument,
  element: TimelineElementDocument,
): ResolvedArtifactOutput[] {
  return Object.entries(element.outputs).map(([name, output]) => {
    const resolved = selectedSlotVersion(project, output.slot_id);
    return resolved
      ? { ...resolved, name }
      : {
          name,
          slot: {
            slot_id: output.slot_id,
            kind: name,
            owner_ref: `element:${element.element_id}`,
            version_ids: [],
            selected_version_id: null,
            metadata: {},
          },
          selected: null,
        };
  });
}

export function resolveTimelineRender(
  project: ProjectDocument,
  timeline: TimelineDocument,
): ResolvedArtifactOutput | null {
  return selectedSlotVersion(
    project,
    `timeline:${timeline.timeline_id}:render`,
  );
}

/**
 * Transition kinds supported by the local compositor with display copy;
 * "fade" is a synonym of crossfade.
 */
export const TRANSITION_KIND_LABEL: Record<string, string> = {
  crossfade: "交叉溶解",
  fade: "交叉溶解",
  fadeblack: "经黑场",
  fadewhite: "经白场",
  dissolve: "颗粒溶解",
  wipeleft: "左划",
  cut: "硬切",
};

export function elementCreationSummary(
  creation: ElementCreationDocument,
): string {
  switch (creation.type) {
    case "r2v":
      return creation.narrative || creation.intent || creation.video_prompt;
    case "edit":
      return creation.intent || creation.reason;
    case "overlay":
      return creation.text || creation.prompt || creation.overlay_kind;
    case "transition":
      return `${
        TRANSITION_KIND_LABEL[creation.transition_kind] ??
        creation.transition_kind
      } 转场`;
    case "audio":
      return "时间线音频";
  }
}

export const ELEMENT_TYPE_META: Record<
  Exclude<ElementCreationDocument["type"], "overlay">,
  {
    label: string;
    color: string;
    soft: string;
  }
> = {
  r2v: { label: "AI 生成画面", color: "#ff7f16", soft: "rgba(255,127,22,.12)" },
  edit: { label: "素材剪辑", color: "#3b82f6", soft: "rgba(59,130,246,.12)" },
  transition: {
    label: "转场",
    color: "#0d9488",
    soft: "rgba(13,148,136,.12)",
  },
  audio: { label: "音频", color: "#12b76a", soft: "rgba(18,183,106,.12)" },
};
