import type {
  ArtifactSlotDocument,
  ArtifactVersionDocument,
  ProjectDocument,
  TimelineDocument,
  TimelineElementDocument,
  VisualEntityDocument,
} from "@/contracts/creator";
import {
  orderedTimelineElements,
  selectLiveTimelineIds,
  timelineEndTick,
} from "./timelineElementSelectors";

/** Slot + its currently selected version, resolved from the asset index. */
export interface ResolvedSlot {
  slot: ArtifactSlotDocument;
  selected: ArtifactVersionDocument | null;
}

function resolveSlot(
  project: ProjectDocument,
  slot: ArtifactSlotDocument | undefined | null,
): ResolvedSlot | null {
  if (!slot) return null;
  return {
    slot,
    selected: slot.selected_version_id
      ? project.assets.artifact_versions_by_id[slot.selected_version_id] ?? null
      : null,
  };
}

/**
 * The timeline_script slot of one narrative node. Convention slot id is
 * `script:<timelineId>`; owner_ref scan tolerates other id schemes.
 */
export function selectTimelineScriptSlot(
  project: ProjectDocument | null | undefined,
  timelineId: string | null | undefined,
): ResolvedSlot | null {
  if (!project || !timelineId) return null;
  const direct = project.assets.artifact_slots_by_id[`script:${timelineId}`];
  if (direct?.kind === "timeline_script") return resolveSlot(project, direct);
  const scanned = Object.values(project.assets.artifact_slots_by_id).find(
    (slot) =>
      slot.kind === "timeline_script" &&
      slot.owner_ref === `timeline:${timelineId}`,
  );
  return resolveSlot(project, scanned);
}

/** All research_report slots of the project (blueprint research tab). */
export function selectResearchSlots(
  project: ProjectDocument | null | undefined,
): ResolvedSlot[] {
  if (!project) return [];
  return Object.values(project.assets.artifact_slots_by_id)
    .filter((slot) => slot.kind === "research_report")
    .map((slot) => resolveSlot(project, slot)!)
    .sort((left, right) => left.slot.slot_id.localeCompare(right.slot.slot_id));
}

/** Final-cut slot of a timeline: timeline_render / final_video kinds. */
export function selectTimelineRenderSlot(
  project: ProjectDocument | null | undefined,
  timelineId: string | null | undefined,
): ResolvedSlot | null {
  if (!project || !timelineId) return null;
  const direct =
    project.assets.artifact_slots_by_id[`timeline:${timelineId}:render`];
  if (direct) return resolveSlot(project, direct);
  const scanned = Object.values(project.assets.artifact_slots_by_id).find(
    (slot) =>
      (slot.kind === "timeline_render" || slot.kind === "final_video") &&
      slot.owner_ref === `timeline:${timelineId}`,
  );
  return resolveSlot(project, scanned);
}

/**
 * The whole film the UI may promise as 整片/成片.
 *
 * Composes are per-timeline artifacts (`timeline:{id}:render`), so a whole
 * film only exists when the project has exactly ONE live timeline — and
 * only the version the user currently has selected on that slot, while it
 * is still fresh. Multi-episode projects return null: a single episode's
 * final render must never masquerade as the whole project, and a stale or
 * unselected newer version must never shadow the user's active choice.
 */
export function selectFinalFilmVersionId(
  project: ProjectDocument | null | undefined,
): string | null {
  if (!project) return null;
  const live = selectLiveTimelineIds(project);
  if (live.length !== 1) return null;
  const render = selectTimelineRenderSlot(project, live[0]);
  const selected = render?.selected;
  if (!selected || selected.stale || !selected.file_id) return null;
  const file = project.assets.files_by_id[selected.file_id];
  if (!file?.media_type?.startsWith("video/")) return null;
  return selected.version_id;
}

const VIDEO_CREATION_TYPES = new Set([
  "r2v",
  "t2v",
  "i2v",
  "s2v",
  "edit",
  "motion_clip",
]);

export function isVideoProductionElement(
  element: TimelineElementDocument,
): boolean {
  return VIDEO_CREATION_TYPES.has(element.creation.type);
}

function selectedEntityVersionId(
  entity: VisualEntityDocument | undefined,
): string | null {
  if (!entity) return null;
  if (entity.selected_artifact_version_id)
    return entity.selected_artifact_version_id;
  for (const variantId of entity.variants.order) {
    const versionId =
      entity.variants.items[variantId]?.selected_artifact_version_id;
    if (versionId) return versionId;
  }
  return null;
}

/**
 * Voice-only role: an enrolled voice with no visual variants required or
 * present (e.g. the video_edit narrator, 仅画外音). Such entities have no
 * portrait to design, so they must not read as pending visual work.
 */
export function isVoiceOnlyVisualEntity(
  entity: VisualEntityDocument | undefined | null,
): boolean {
  if (!entity) return false;
  return Boolean(
    entity.voice &&
      entity.required_variant_ids.length === 0 &&
      entity.variants.order.length === 0,
  );
}

export type RoughCutSource = "final" | "storyboard" | "design" | "none";

/** Media namespace of RoughCutFrame.versionId: generated artifact vs uploaded/recorded source asset. */
export type RoughCutVersionKind = "artifact" | "source";

export interface RoughCutFrame {
  key: string;
  timelineId: string;
  timelineIndex: number;
  elementId: string;
  label: string;
  /** Artifact/source-asset version rendering this frame, if any. */
  versionId: string | null;
  versionKind: RoughCutVersionKind | null;
  mediaKind: "image" | "video" | null;
  source: RoughCutSource;
}

/**
 * Rough-cut frame of one element, derived purely from existing artifacts
 * (plan §4.8): selected element_video ▸ render_source media (real clips of
 * the video_edit path / pinned artifact) ▸ motion_clip's carried motion
 * document ▸ r2v_storyboard_image ▸ the referenced entity's visual design
 * image ▸ empty placeholder.
 */
export function roughCutFrameForElement(
  project: ProjectDocument,
  element: TimelineElementDocument,
): {
  versionId: string | null;
  versionKind: RoughCutVersionKind | null;
  mediaKind: "image" | "video" | null;
  source: RoughCutSource;
} {
  // 1. Selected element_video output.
  for (const output of Object.values(element.outputs)) {
    const slot = project.assets.artifact_slots_by_id[output.slot_id];
    if (!slot || slot.kind !== "element_video" || !slot.selected_version_id)
      continue;
    return {
      versionId: slot.selected_version_id,
      versionKind: "artifact",
      mediaKind: "video",
      source: "final",
    };
  }
  // 2. The element's render_source — the durable media reference the final
  //    compositor plays. The video_edit path never produces element_video
  //    slots: edit elements consume real clips via a source_asset_version
  //    render_source, so that reference *is* the shot's finished picture.
  const renderSource = element.render_source;
  if (renderSource?.type === "source_asset_version") {
    const version =
      project.assets.source_versions_by_id[renderSource.version_id];
    if (
      version &&
      (version.media_kind === "video" || version.media_kind === "image")
    ) {
      return {
        versionId: version.version_id,
        versionKind: "source",
        mediaKind: version.media_kind,
        source: "final",
      };
    }
  } else if (renderSource?.type === "artifact_version") {
    const version =
      project.assets.artifact_versions_by_id[renderSource.version_id];
    if (version && !version.stale) {
      const file = project.assets.files_by_id[version.file_id];
      return {
        versionId: version.version_id,
        versionKind: "artifact",
        mediaKind: file?.media_type?.startsWith("image/") ? "image" : "video",
        source: "final",
      };
    }
  }
  // (render_source.type === "element_output" pointing at this element's own
  // slot is already covered by step 1.)
  // 3. Full-canvas motion clips carry their whole picture in creation.motion
  //    (rasterized by the backend at composite time): once the design
  //    pipeline wrote the document the segment is done, with no media
  //    artifact to point at — mirrors resolveElementPlayback's "ready".
  if (
    element.creation.type === "motion_clip" &&
    (element.creation.motion?.html || element.creation.motion?.html_file_id)
  ) {
    return {
      versionId: null,
      versionKind: null,
      mediaKind: null,
      source: "final",
    };
  }
  // 4. Storyboard image (the mandatory intermediate of generated elements).
  const storyboard = Object.values(project.assets.artifact_slots_by_id).find(
    (slot) =>
      slot.owner_ref === `element:${element.element_id}` &&
      (slot.kind === "r2v_storyboard_image" ||
        slot.slot_id.endsWith(":storyboard")) &&
      slot.selected_version_id,
  );
  if (storyboard?.selected_version_id) {
    return {
      versionId: storyboard.selected_version_id,
      versionKind: "artifact",
      mediaKind: "image",
      source: "storyboard",
    };
  }
  // 5. Referenced visual entity design image.
  const creation = element.creation;
  const entityRefs: string[] = [];
  if (creation.type === "r2v") {
    entityRefs.push(...creation.character_refs);
    if (creation.scene_ref) entityRefs.push(creation.scene_ref);
  } else if (creation.type === "s2v" && creation.character_ref) {
    entityRefs.push(creation.character_ref);
  }
  for (const ref of entityRefs) {
    const entity =
      project.visual.entities.items[ref.replace(/^visual-entity:/, "")];
    const versionId = selectedEntityVersionId(entity);
    if (versionId)
      return {
        versionId,
        versionKind: "artifact",
        mediaKind: "image",
        source: "design",
      };
  }
  return {
    versionId: null,
    versionKind: null,
    mediaKind: null,
    source: "none",
  };
}

/** All frames of the live timelines (history snapshots excluded). */
export function selectRoughCutFrames(
  project: ProjectDocument | null | undefined,
): RoughCutFrame[] {
  if (!project) return [];
  return selectLiveTimelineIds(project).flatMap((timelineId, timelineIndex) => {
    const timeline = project.timelines.items[timelineId];
    if (!timeline) return [];
    return orderedTimelineElements(timeline)
      .filter(
        (element) =>
          element.enabled &&
          // Only picture-carrying scene elements; overlays / motion clips /
          // transitions / audio / interaction points never have storyboards
          // or base frames to wait for.
          ["r2v", "t2v", "i2v", "s2v", "edit"].includes(element.creation.type),
      )
      .map((element) => ({
        key: `${timelineId}:${element.element_id}`,
        timelineId,
        timelineIndex,
        elementId: element.element_id,
        label: element.label || element.element_id,
        ...roughCutFrameForElement(project, element),
      }));
  });
}

export interface TimelineSummary {
  timeline: TimelineDocument;
  timelineId: string;
  index: number;
  /** timeline.title fallback handled by callers (i18n 第N集). */
  title: string;
  synopsis: string;
  elementCount: number;
  videoTotal: number;
  videoReady: number;
  hasScript: boolean;
  scriptStale: boolean;
  renderReady: boolean;
  durationSeconds: number;
}

export function summarizeTimeline(
  project: ProjectDocument,
  timelineId: string,
  index: number,
): TimelineSummary | null {
  const timeline = project.timelines.items[timelineId];
  if (!timeline) return null;
  const elements = orderedTimelineElements(timeline).filter(
    (element) => element.enabled,
  );
  const videoElements = elements.filter(isVideoProductionElement);
  const videoReady = videoElements.filter(
    (element) => roughCutFrameForElement(project, element).source === "final",
  ).length;
  const script = selectTimelineScriptSlot(project, timelineId);
  const render = selectTimelineRenderSlot(project, timelineId);
  const duration =
    timeline.planned_duration_seconds ??
    (timeline.ticks_per_second
      ? timelineEndTick(timeline) / timeline.ticks_per_second
      : 0);
  return {
    timeline,
    timelineId,
    index,
    title: timeline.title ?? "",
    synopsis: timeline.synopsis ?? "",
    elementCount: elements.length,
    videoTotal: videoElements.length,
    videoReady,
    hasScript: Boolean(script?.selected),
    scriptStale: Boolean(script?.selected?.stale),
    renderReady: Boolean(render?.selected && !render.selected.stale),
    durationSeconds: duration,
  };
}

export function selectTimelineSummaries(
  project: ProjectDocument | null | undefined,
): TimelineSummary[] {
  if (!project) return [];
  return selectLiveTimelineIds(project)
    .map((timelineId, index) => summarizeTimeline(project, timelineId, index))
    .filter((summary): summary is TimelineSummary => Boolean(summary));
}
