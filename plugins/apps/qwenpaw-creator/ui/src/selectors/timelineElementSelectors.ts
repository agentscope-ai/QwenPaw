import type {
  ArtifactSlotDocument,
  ArtifactVersionDocument,
  ElementCreationDocument,
  OverlayCreationDocument,
  ProjectDocument,
  TimelineDocument,
  TimelineElementDocument,
} from "@/contracts/creator";
import {
  splitTransitionsForDisplay,
  type TransitionJunction,
} from "@/lib/timelineEditing";
import i18n from "@/i18n";

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
  ai: {
    label: "timeline.trackTypes.ai",
    color: "#ff7f16",
    soft: "rgba(255,127,22,.12)",
  },
  clip: {
    label: "timeline.trackTypes.clip",
    color: "#3b82f6",
    soft: "rgba(59,130,246,.12)",
  },
  subtitle: {
    label: "timeline.trackTypes.subtitle",
    color: "#8b5cf6",
    soft: "rgba(139,92,246,.12)",
  },
  motion: {
    label: "timeline.trackTypes.motion",
    color: "#f59e0b",
    soft: "rgba(245,158,11,.12)",
  },
  transition: {
    label: "timeline.trackTypes.transition",
    color: "#0d9488",
    soft: "rgba(13,148,136,.12)",
  },
  audio: {
    label: "timeline.trackTypes.audio",
    color: "#12b76a",
    soft: "rgba(18,183,106,.12)",
  },
};

/**
 * Semantic overlay category tolerant of schema v3, where overlay_kind was
 * dropped: copy bubbles render deterministically, motion documents carry
 * inline HTML, media overlays reference generated footage.
 */
export function overlayContentKind(
  creation: OverlayCreationDocument,
): "copy" | "motion" | "media" {
  // Committed snapshots derive overlay roles from data; the legacy
  // overlay_kind tag is only honored for pre-migration payloads.
  const kind = creation.overlay_kind as string | undefined;
  if (kind === "pet_os" || kind === "interview_summary") return "copy";
  if (kind === "motion") return "motion";
  if (kind === "media") return "media";
  return creation.text?.trim() ? "copy" : "motion";
}

export function classifyElementTrack(
  element: TimelineElementDocument,
): TimelineTrackType | null {
  const { creation } = element;
  switch (creation.type) {
    case "r2v":
    case "t2v":
    case "i2v":
    case "s2v":
      return "ai";
    case "edit":
      return "clip";
    case "motion_clip":
      // Full-canvas motion documents carry the segment picture itself,
      // so they ride the main clip track alongside edit segments.
      return "clip";
    case "transition":
      return "transition";
    case "audio":
      return "audio";
    case "overlay":
      // Overlay roles derive from data (legacy tags stay recognized in
      // overlayContentKind): copy rides the subtitle track, decorations
      // and media stickers ride the motion track.
      return overlayContentKind(creation) === "copy" ? "subtitle" : "motion";
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
  if (trackType) {
    const meta = TRACK_TYPE_META[trackType];
    return { ...meta, label: i18n.t(meta.label) };
  }
  if (element.creation.type === "overlay") {
    const meta = element.creation.text.trim()
      ? TRACK_TYPE_META.subtitle
      : TRACK_TYPE_META.motion;
    return { ...meta, label: i18n.t(meta.label) };
  }
  const meta =
    ELEMENT_TYPE_META[
      element.creation.type as Exclude<
        ElementCreationDocument["type"],
        "overlay"
      >
    ];
  return { ...meta, label: i18n.t(meta.label) };
}

export function groupElementsByTracks(
  timeline: TimelineDocument | null | undefined,
  bridgedPairs?: Set<string>,
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
      lastElementId: string;
      elements: TimelineElementDocument[];
    }> = [];
    for (const element of elements) {
      // Clips joined by a transition overlap on purpose; like the reference
      // design they stay adjacent on one track row instead of being split
      // into stacked lanes.
      const lane = laneMap.find(
        (candidate) =>
          candidate.endTick <= element.span.start_tick ||
          bridgedPairs?.has(
            `${candidate.lastElementId}\u0000${element.element_id}`,
          ),
      );
      const endTick = element.span.start_tick + element.span.duration_tick;
      if (lane) {
        lane.elements.push(element);
        lane.endTick = Math.max(lane.endTick, endTick);
        lane.lastElementId = element.element_id;
      } else {
        laneMap.push({
          endTick,
          lastElementId: element.element_id,
          elements: [element],
        });
      }
    }
    return {
      type,
      label: i18n.t(meta.label),
      color: meta.color,
      soft: meta.soft,
      lanes: laneMap.map((lane, index) => ({
        id: `${type}-${index + 1}`,
        elements: lane.elements,
      })),
    };
  });
}

export interface DisplayTrackGroups {
  tracks: TimelineTrack[];
  junctions: TransitionJunction[];
}

/**
 * Track grouping for the editing surface: transitions whose from/to elements
 * both exist are lifted out of the track rows and rendered as junction badges
 * between the two clips; only orphan transitions keep an ordinary row. Clips
 * bridged by a transition share one lane despite their overlap.
 */
export function groupDisplayTracks(
  timeline: TimelineDocument | null | undefined,
): DisplayTrackGroups {
  if (!timeline) return { tracks: [], junctions: [] };
  const { junctions } = splitTransitionsForDisplay(timeline);
  if (!junctions.length)
    return { tracks: groupElementsByTracks(timeline), junctions };
  const junctionIds = new Set(
    junctions.map((junction) => junction.transition.element_id),
  );
  const bridgedPairs = new Set(
    junctions.map((junction) => `${junction.fromId}\u0000${junction.toId}`),
  );
  const filtered: TimelineDocument = {
    ...timeline,
    elements_by_id: Object.fromEntries(
      Object.entries(timeline.elements_by_id).filter(
        ([elementId]) => !junctionIds.has(elementId),
      ),
    ),
  };
  return {
    tracks: groupElementsByTracks(filtered, bridgedPairs),
    junctions,
  };
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
  crossfade: "timeline.transitionKinds.crossfade",
  fade: "timeline.transitionKinds.fade",
  fadeblack: "timeline.transitionKinds.fadeblack",
  fadewhite: "timeline.transitionKinds.fadewhite",
  dissolve: "timeline.transitionKinds.dissolve",
  wipeleft: "timeline.transitionKinds.wipeleft",
  cut: "timeline.transitionKinds.cut",
};

export function elementCreationSummary(
  creation: ElementCreationDocument,
): string {
  switch (creation.type) {
    case "r2v":
    case "t2v":
    case "i2v":
      return creation.narrative || creation.intent || creation.video_prompt;
    case "s2v":
      return creation.script || creation.intent;
    case "edit":
      return creation.intent || creation.reason;
    case "overlay":
      return (
        creation.text || creation.prompt || i18n.t("timeline.trackTypes.motion")
      );
    case "transition": {
      const key = TRANSITION_KIND_LABEL[creation.transition_kind];
      const label = key ? i18n.t(key) : creation.transition_kind ?? "";
      return `${label} ${i18n.t("timeline.elementSummary.transition")}`;
    }
    case "audio":
      return i18n.t("timeline.elementSummary.audio");
    case "motion_clip":
      return (
        creation.prompt ||
        creation.intent ||
        i18n.t("timeline.trackTypes.motion")
      );
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
  r2v: {
    label: "timeline.elementTypes.r2v",
    color: "#ff7f16",
    soft: "rgba(255,127,22,.12)",
  },
  t2v: {
    label: "timeline.elementTypes.t2v",
    color: "#ff7f16",
    soft: "rgba(255,127,22,.12)",
  },
  i2v: {
    label: "timeline.elementTypes.i2v",
    color: "#ff7f16",
    soft: "rgba(255,127,22,.12)",
  },
  s2v: {
    label: "timeline.elementTypes.s2v",
    color: "#ff7f16",
    soft: "rgba(255,127,22,.12)",
  },
  edit: {
    label: "timeline.elementTypes.edit",
    color: "#3b82f6",
    soft: "rgba(59,130,246,.12)",
  },
  motion_clip: {
    label: "timeline.trackTypes.motion",
    color: "#8b5cf6",
    soft: "rgba(139,92,246,.12)",
  },
  transition: {
    label: "timeline.elementTypes.transition",
    color: "#0d9488",
    soft: "rgba(13,148,136,.12)",
  },
  audio: {
    label: "timeline.elementTypes.audio",
    color: "#12b76a",
    soft: "rgba(18,183,106,.12)",
  },
};
