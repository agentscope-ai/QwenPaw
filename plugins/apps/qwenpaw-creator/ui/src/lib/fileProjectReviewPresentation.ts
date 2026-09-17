import type {
  FileProjectReviewOperation,
  ProjectDocument,
} from "@/contracts/creator";
import { creatorTargetLabel } from "@/lib/creatorPresentation";
import { publicAssistantText } from "@/lib/creatorMessagePresentation";
import i18n from "@/i18n";

const FIELD_KEYS: Record<string, string> = {
  label: "fileReview.name",
  name: "fileReview.name",
  title: "fileReview.titleField",
  description: "fileReview.description",
  synopsis: "fileReview.description",
  creative_brief: "fileReview.creativeBrief",
  creative_direction: "fileReview.creativeDirection",
  prompt: "fileReview.prompt",
  storyboard_prompt: "fileReview.prompt",
  video_prompt: "fileReview.prompt",
  camera: "fileReview.camera",
  framing: "fileReview.framing",
  narration: "fileReview.narration",
  dialogue: "fileReview.dialogue",
  text: "fileReview.public.text",
  script: "fileReview.public.text",
  intent: "fileReview.description",
  narrative: "fileReview.description",
  continuity: "fileReview.description",
  user_notes: "fileReview.description",
  duration_seconds: "fileReview.duration",
  target_duration_seconds: "fileReview.duration",
  planned_duration_seconds: "fileReview.duration",
};
const KIND_KEYS: Record<string, string> = {
  create: "fileReview.added",
  update: "fileReview.modified",
  delete: "fileReview.deleted",
  move: "fileReview.moved",
  reorder: "fileReview.reordered",
  select_asset: "fileReview.selectAsset",
};
const CREATION_KEYS: Record<string, string> = {
  edit: "fileReview.creationTypeEdit",
  r2v: "fileReview.video",
  t2v: "fileReview.video",
  i2v: "fileReview.video",
  s2v: "fileReview.creationTypeS2v",
  overlay: "fileReview.creationTypeOverlay",
  motion_clip: "fileReview.creationTypeOverlay",
  transition: "fileReview.creationTypeTransition",
  audio: "fileReview.creationTypeAudio",
};

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function tokensOf(pointer: string | null): string[] {
  return (pointer ?? "")
    .split("/")
    .slice(1)
    .map((token) => token.replace(/~1/gu, "/").replace(/~0/gu, "~"));
}

/** Review copy is a whitelist of authored text, never a stringify fallback. */
function publicText(
  value: unknown,
  project?: ProjectDocument | null,
): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const text = value.trim();
  if (
    /^[\[{]/u.test(text) ||
    /\b(?:snapshot|run|task|file|version|ver):[\w.-]+/u.test(text) ||
    /^(?:\/|~\/|[A-Za-z]:\\|(?:file|https?):\/\/|(?:[\w.-]+\/)+[\w.-]+$)/u.test(
      text,
    ) ||
    /^[a-f\d]{8}-[a-f\d-]{27,}$/iu.test(text)
  )
    return null;
  return publicAssistantText(text, { streaming: false, project }) || null;
}

function objectName(
  value: unknown,
  project?: ProjectDocument | null,
): string | null {
  const object = record(value);
  if (!object) return null;
  return (
    publicText(object.title, project) ??
    publicText(object.label, project) ??
    publicText(object.name, project)
  );
}

export interface FileReviewPresentation {
  title: string;
  kindLabel: string;
  preview: string;
  /** These are safe authored strings, suitable for a text-only diff. */
  beforeText: string | null;
  afterText: string | null;
  hasTextDiff: boolean;
  /** A public destination exists; bookkeeping changes still keep decisions. */
  canInspect: boolean;
}

export function isReviewReferenceField(pointer: string | null): boolean {
  const tokens = tokensOf(pointer);
  return (
    tokens[0] === "timelines" &&
    tokens[1] === "items" &&
    tokens[3] === "elements_by_id" &&
    tokens[5] === "creation" &&
    tokens.length === 7 &&
    [
      "storyboard_reference_version_ids",
      "video_reference_version_ids",
    ].includes(tokens[6])
  );
}

/** Project an operation for display without changing its decision identity. */
export function fileReviewPresentation(
  operation: FileProjectReviewOperation,
  project?: ProjectDocument | null,
): FileReviewPresentation {
  const tokens = tokensOf(operation.json_pointer);
  const last = tokens.at(-1) ?? "";
  const locator = operation.ui_locator ?? {};
  const elementIndex = tokens.indexOf("elements_by_id");
  const elementId =
    locator.elementId ??
    (elementIndex >= 0 ? tokens[elementIndex + 1] : undefined);
  const timelineId =
    locator.timelineId ??
    (tokens[0] === "timelines" && tokens[1] === "items"
      ? tokens[2]
      : undefined);
  const visualIndex =
    tokens[0] === "visual" && tokens[1] === "entities" && tokens[2] === "items"
      ? 3
      : -1;
  const assetId =
    locator.assetId ?? (visualIndex >= 0 ? tokens[visualIndex] : undefined);
  const ref = elementId
    ? `element:${elementId}`
    : assetId
    ? `visual-entity:${assetId}`
    : timelineId
    ? `timeline:${timelineId}`
    : operation.target_ref ?? "project";
  const owner = creatorTargetLabel(ref, project);
  const kindLabel = i18n.t(KIND_KEYS[operation.kind] ?? "fileReview.modified");
  const field = FIELD_KEYS[last] ? i18n.t(FIELD_KEYS[last]) : "";
  const wholeTimeline =
    tokens.length === 3 && tokens[0] === "timelines" && tokens[1] === "items";
  const wholeElement = elementIndex >= 0 && elementIndex + 2 === tokens.length;
  const object = record(
    operation.kind === "delete" ? operation.before : operation.after,
  );
  const creation = record(object?.creation);
  const structuralKind = wholeTimeline
    ? i18n.t(
        timelineId?.startsWith("snapshot:")
          ? "fileReview.public.videoVersion"
          : "fileReview.public.editPlan",
      )
    : wholeElement || creation
    ? i18n.t(CREATION_KEYS[String(creation?.type)] ?? "fileReview.content")
    : i18n.t("fileReview.content");
  const namedObject = objectName(
    operation.kind === "delete" ? operation.before : operation.after,
    project,
  );
  const structuralTitle = namedObject
    ? `${structuralKind} · ${namedObject}`
    : structuralKind;
  const title =
    wholeTimeline || wholeElement || creation
      ? structuralTitle
      : field
      ? `${owner} · ${field}`
      : owner;
  const base: FileReviewPresentation = {
    title,
    kindLabel,
    preview: "",
    beforeText: null,
    afterText: null,
    hasTextDiff: false,
    canInspect:
      operation.kind !== "delete" &&
      Boolean(operation.json_pointer || locator.field),
  };

  if (timelineId?.startsWith("snapshot:")) {
    return {
      ...base,
      title: i18n.t("fileReview.public.versionRecord"),
      preview:
        operation.kind === "create"
          ? i18n.t("fileReview.public.snapshotSaved")
          : i18n.t(
              `fileReview.public.${
                operation.kind === "delete" ? "deleted" : "updated"
              }`,
              { kind: i18n.t("fileReview.public.versionRecord") },
            ),
      canInspect: false,
    };
  }
  if (
    tokens.length === 2 &&
    tokens[0] === "timelines" &&
    tokens[1] === "order"
  ) {
    const liveOrder = (value: unknown) =>
      Array.isArray(value) && value.every((id) => typeof id === "string")
        ? value.filter((id: string) => !id.startsWith("snapshot:"))
        : null;
    const before = liveOrder(operation.before);
    const after = liveOrder(operation.after);
    const historyOnly =
      before !== null &&
      after !== null &&
      JSON.stringify(before) === JSON.stringify(after);
    return {
      ...base,
      title: historyOnly
        ? i18n.t("fileReview.public.versionRecord")
        : `${owner} · ${i18n.t("fileReview.public.order")}`,
      preview: i18n.t(
        historyOnly
          ? "fileReview.public.versionHistoryUpdated"
          : "fileReview.public.orderAdjusted",
      ),
      canInspect: false,
    };
  }
  if (isReviewReferenceField(operation.json_pointer)) {
    return {
      ...base,
      title: `${owner} · ${i18n.t("fileReview.public.referenceImages")}`,
      preview: i18n.t("fileReview.public.referencesUpdated"),
    };
  }

  if (operation.kind === "reorder" || last === "order") {
    return {
      ...base,
      title: `${owner} · ${i18n.t("fileReview.public.order")}`,
      preview: i18n.t("fileReview.public.orderAdjusted"),
    };
  }
  if (
    operation.kind === "move" ||
    tokens.includes("span") ||
    tokens.includes("location")
  )
    return { ...base, preview: i18n.t("fileReview.public.arrangementUpdated") };
  if (
    operation.kind === "select_asset" ||
    last === "selected_version_id" ||
    last === "render_source"
  )
    return {
      ...base,
      title: `${owner} · ${i18n.t("fileReview.public.mediaSelection")}`,
      preview: i18n.t("fileReview.public.selectionUpdated"),
    };

  // Only explicitly public text fields may feed a diff. Object/array values,
  // unknown fields, ids and bookkeeping values stay as semantic summaries.
  if (field) {
    const fieldText = (value: unknown): string | null => {
      if (
        last.endsWith("duration_seconds") &&
        typeof value === "number" &&
        Number.isFinite(value) &&
        value >= 0
      )
        return i18n.t("executionAuth.duration", { duration: value });
      return publicText(value, project);
    };
    const beforeText = fieldText(operation.before);
    const afterText = fieldText(operation.after);
    if (beforeText !== null || afterText !== null) {
      const compact = (text: string | null) => {
        const value = text?.replace(/\s+/gu, " ") ?? "—";
        return value.length > 100 ? `${value.slice(0, 100)}…` : value;
      };
      return {
        ...base,
        beforeText,
        afterText,
        hasTextDiff: true,
        preview: `${compact(beforeText)} → ${compact(afterText)}`,
      };
    }
  }
  const summaryKey =
    operation.kind === "create"
      ? "added"
      : operation.kind === "delete"
      ? "deleted"
      : "updated";
  return {
    ...base,
    preview: i18n.t(`fileReview.public.${summaryKey}`, {
      kind: structuralKind,
    }),
  };
}
