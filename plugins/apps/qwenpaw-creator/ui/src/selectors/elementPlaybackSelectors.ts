import type {
  ArtifactVersionDocument,
  ElementRenderSourceDocument,
  ProjectDocument,
  TaskView,
  TimelineDocument,
  TimelineElementDocument,
} from "@/contracts/creator";
import {
  getArtifactVersionMediaUrl,
  getAssetVersionMediaUrl,
} from "@/api/creator";
import {
  elementsAtTick,
  overlayContentKind,
} from "@/selectors/timelineElementSelectors";
import i18n from "@/i18n";

export type ElementPlaybackStatus =
  | "ready"
  | "generating"
  | "queued"
  | "failed"
  | "stale"
  | "pending";

export type ElementPlaybackMediaKind = "video" | "image" | "audio" | "other";

export interface ElementPlaybackMedia {
  url: string;
  mediaKind: ElementPlaybackMediaKind;
  /** Artifact/source-asset version ID; used as the layer's stable key. */
  versionId: string;
  sourceInSeconds: number;
  sourceOutSeconds: number | null;
  playbackRate: number;
  loop: boolean;
  durationSeconds: number | null;
  stale: boolean;
}

export interface ElementPlayback {
  element: TimelineElementDocument;
  status: ElementPlaybackStatus;
  media: ElementPlaybackMedia | null;
}

export const ELEMENT_PLAYBACK_STATUS_LABEL: Record<
  ElementPlaybackStatus,
  string
> = {
  ready: "playback.ready",
  generating: "playback.generating",
  queued: "playback.queued",
  failed: "playback.failed",
  stale: "playback.needRegen",
  pending: "playback.pending",
};

function mediaKindOfType(mediaType: string): ElementPlaybackMediaKind {
  if (mediaType.startsWith("video/")) return "video";
  if (mediaType.startsWith("image/")) return "image";
  if (mediaType.startsWith("audio/")) return "audio";
  return "other";
}

function artifactMediaKind(
  project: ProjectDocument,
  version: ArtifactVersionDocument,
): ElementPlaybackMediaKind {
  const file = project.assets.files_by_id[version.file_id];
  return mediaKindOfType(file?.media_type ?? "");
}

interface ResolvedMediaRef {
  url: string;
  mediaKind: ElementPlaybackMediaKind;
  versionId: string;
  durationSeconds: number | null;
  stale: boolean;
}

function resolveArtifactVersionRef(
  project: ProjectDocument,
  versionId: string,
): ResolvedMediaRef | null {
  const version = project.assets.artifact_versions_by_id[versionId];
  if (!version) return null;
  return {
    url: getArtifactVersionMediaUrl(versionId),
    mediaKind: artifactMediaKind(project, version),
    versionId,
    durationSeconds: version.duration_seconds,
    stale: version.stale,
  };
}

function resolveSourceVersionRef(
  project: ProjectDocument,
  versionId: string,
): ResolvedMediaRef | null {
  const version = project.assets.source_versions_by_id[versionId];
  if (!version) return null;
  const kind = version.media_kind;
  return {
    url: getAssetVersionMediaUrl(versionId),
    mediaKind:
      kind === "video" || kind === "image" || kind === "audio" ? kind : "other",
    versionId,
    durationSeconds: version.duration_seconds,
    stale: false,
  };
}

function resolveSelectedOutputRef(
  project: ProjectDocument,
  element: TimelineElementDocument,
  outputName?: string,
): ResolvedMediaRef | null {
  const names = outputName
    ? [outputName]
    : ["video", ...Object.keys(element.outputs)];
  for (const name of names) {
    const output = element.outputs[name];
    if (!output) continue;
    const slot = project.assets.artifact_slots_by_id[output.slot_id];
    if (!slot?.selected_version_id) continue;
    const resolved = resolveArtifactVersionRef(
      project,
      slot.selected_version_id,
    );
    if (resolved) return resolved;
  }
  return null;
}

function resolveRenderSourceRef(
  project: ProjectDocument,
  timeline: TimelineDocument,
  renderSource: ElementRenderSourceDocument,
): ResolvedMediaRef | null {
  if (renderSource.type === "artifact_version") {
    return resolveArtifactVersionRef(project, renderSource.version_id);
  }
  if (renderSource.type === "source_asset_version") {
    return resolveSourceVersionRef(project, renderSource.version_id);
  }
  const target = timeline.elements_by_id[renderSource.element_id];
  if (!target) return null;
  return resolveSelectedOutputRef(project, target, renderSource.output_name);
}

function elementTaskStatus(
  element: TimelineElementDocument,
  tasks: TaskView[],
): ElementPlaybackStatus | null {
  const task = tasks.find(
    (item) => item.targetRef === `element:${element.element_id}`,
  );
  if (task?.status === "RUNNING") return "generating";
  if (task?.status === "QUEUED") return "queued";
  if (task?.status === "FAILED" || task?.status === "QUARANTINED")
    return "failed";
  return null;
}

/**
 * Resolve an Element's playback info for the live-assembly preview. Matches the
 * backend local compositor: resolve media via render_source first, falling back
 * to the selected output in outputs. With no media, derive generating/queued/
 * failed from the associated Task status, defaulting to pending.
 */
export function resolveElementPlayback(
  project: ProjectDocument,
  timeline: TimelineDocument,
  element: TimelineElementDocument,
  tasks: TaskView[] = [],
): ElementPlayback {
  // Transitions are realized in live assembly as an opacity fade on the "to"
  // layer, not as an independent media layer, so they count as ready.
  if (element.creation.type === "transition") {
    return { element, status: "ready", media: null };
  }
  // Audio Elements reference their source version directly on the creation;
  // there is no render_source/output indirection to resolve.
  if (element.creation.type === "audio") {
    const resolvedAudio = resolveSourceVersionRef(
      project,
      element.creation.source_asset_version_id,
    );
    if (resolvedAudio) {
      return {
        element,
        status: "ready",
        media: {
          ...resolvedAudio,
          sourceInSeconds: 0,
          sourceOutSeconds: null,
          playbackRate: 1,
          loop: false,
        },
      };
    }
    return { element, status: "pending", media: null };
  }
  const ticksPerSecond = timeline.ticks_per_second || 1;
  const renderSource = element.render_source;
  const fromRender = renderSource
    ? resolveRenderSourceRef(project, timeline, renderSource)
    : null;
  const resolved = fromRender ?? resolveSelectedOutputRef(project, element);
  if (resolved) {
    const timing = fromRender && renderSource ? renderSource : null;
    const taskStatus = elementTaskStatus(element, tasks);
    const artifactStatus: ElementPlaybackStatus = resolved.stale
      ? "stale"
      : "ready";
    // Only regeneration tasks still queued/running may override a ready frame;
    // historical terminal tasks (failed/quarantined) must not misreport a fresh,
    // playable selected artifact as "failed" — otherwise scrubbing to that point
    // would show an already-rendered segment as awaiting re-render.
    const status: ElementPlaybackStatus =
      taskStatus === "generating" || taskStatus === "queued"
        ? taskStatus
        : artifactStatus === "ready"
        ? "ready"
        : taskStatus ?? artifactStatus;
    return {
      element,
      status,
      media: {
        ...resolved,
        sourceInSeconds: timing ? timing.source_in_tick / ticksPerSecond : 0,
        sourceOutSeconds:
          timing && timing.source_out_tick != null
            ? timing.source_out_tick / ticksPerSecond
            : null,
        playbackRate: timing ? timing.playback_rate : 1,
        loop: timing ? timing.loop : false,
      },
    };
  }
  // A motion overlay's HTML/CSS document is itself previewable content; no
  // separate media artifact is needed. The final cut is still rendered
  // frame-by-frame and composited by the backend; this only covers the
  // in-browser live preview.
  if (
    element.creation.type === "overlay" &&
    (element.creation.motion?.html || element.creation.motion?.html_file_id)
  ) {
    return { element, status: "ready", media: null };
  }
  // Caption overlays (non-empty text) have no standalone artifact: the
  // final cut draws the bubble with a deterministic renderer at composite
  // time, and the live preview draws the same spec directly, so they count
  // as ready.
  if (element.creation.type === "overlay" && element.creation.text.trim()) {
    return { element, status: "ready", media: null };
  }
  return {
    element,
    status: elementTaskStatus(element, tasks) ?? "pending",
    media: null,
  };
}

/** Browser approximation of the model's easing field; default linear. */
function easeProgress(progress: number, easing: string): number {
  const clamped = Math.min(1, Math.max(0, progress));
  switch (easing) {
    case "ease-in":
    case "ease_in":
      return clamped * clamped;
    case "ease-out":
    case "ease_out":
      return 1 - (1 - clamped) * (1 - clamped);
    case "ease-in-out":
    case "ease_in_out":
      return clamped < 0.5
        ? 2 * clamped * clamped
        : 1 - 2 * (1 - clamped) * (1 - clamped);
    default:
      return clamped;
  }
}

/**
 * Opacity multiplier for an Element in the live preview as dictated by
 * transitions. Same semantics as backend compositing: inside the transition
 * window the "to" layer fades in over the "from" layer by progress; during the
 * overlap before the window, the "to" layer stays hidden. Non-fade
 * transition_kind values degrade to crossfade in the browser preview, while
 * the final cut still composites the real type.
 */
export function transitionOpacityAtTick(
  timeline: TimelineDocument,
  element: TimelineElementDocument,
  tick: number,
): number {
  if (element.creation.type === "transition") return 1;
  for (const candidate of Object.values(timeline.elements_by_id)) {
    if (!candidate.enabled || candidate.creation.type !== "transition")
      continue;
    if (candidate.creation.to_element_id !== element.element_id) continue;
    if (candidate.creation.transition_kind === "cut") continue;
    const start = candidate.span.start_tick;
    const end = start + candidate.span.duration_tick;
    if (tick >= end) continue;
    if (tick < start) {
      // Overlap started but blend has not: frame still belongs to "from" side.
      if (tick >= element.span.start_tick) return 0;
      continue;
    }
    const progress = (tick - start) / Math.max(1, candidate.span.duration_tick);
    return easeProgress(progress, candidate.creation.easing);
  }
  return 1;
}

export function playbackLayersAtTick(
  project: ProjectDocument,
  timeline: TimelineDocument,
  tick: number,
  tasks: TaskView[] = [],
): ElementPlayback[] {
  return elementsAtTick(timeline, tick)
    .filter((element) => element.creation.type !== "transition")
    .sort(
      (left, right) =>
        left.z_index - right.z_index ||
        left.span.start_tick - right.span.start_tick ||
        left.element_id.localeCompare(right.element_id),
    )
    .map((element) =>
      resolveElementPlayback(project, timeline, element, tasks),
    );
}

/**
 * Layers inside the mount window (behindSeconds before / aheadSeconds after the
 * current tick), used to pre-mount media elements and reduce black frames on
 * switches; transitions are dropped as well.
 */
export function playbackLayersInWindow(
  project: ProjectDocument,
  timeline: TimelineDocument,
  tick: number,
  tasks: TaskView[] = [],
  behindSeconds = 2,
  aheadSeconds = 8,
): ElementPlayback[] {
  const ticksPerSecond = timeline.ticks_per_second || 1;
  const windowStart = tick - behindSeconds * ticksPerSecond;
  const windowEnd = tick + aheadSeconds * ticksPerSecond;
  return Object.values(timeline.elements_by_id)
    .filter(
      (element) =>
        element.enabled &&
        element.creation.type !== "transition" &&
        element.span.start_tick < windowEnd &&
        windowStart < element.span.start_tick + element.span.duration_tick,
    )
    .sort(
      (left, right) =>
        left.z_index - right.z_index ||
        left.span.start_tick - right.span.start_tick ||
        left.element_id.localeCompare(right.element_id),
    )
    .map((element) =>
      resolveElementPlayback(project, timeline, element, tasks),
    );
}
