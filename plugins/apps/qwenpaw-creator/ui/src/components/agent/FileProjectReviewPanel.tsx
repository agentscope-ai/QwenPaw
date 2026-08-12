import { useState } from "react";
import { message } from "antd";
import {
  Check,
  Eye,
  FileDiff,
  Image as ImageIcon,
  Undo2,
  Video,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type {
  FileProjectReviewDecision,
  FileProjectReviewOperation,
  FileProjectReviewOperationDecision,
  FileProjectReviewRejectionFeedback,
  FileProjectReviewRecord,
} from "@/contracts/creator";
import { getArtifactVersionMediaUrl } from "@/api/creator";
import { navigateToLocator } from "@/routing/locators";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import OnboardingHint from "@/components/onboarding/OnboardingHint";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { selectPrimaryTimeline } from "@/selectors/timelineElementSelectors";
import DiffView from "./DiffView";
import RejectionFeedbackModal from "./RejectionFeedbackModal";
import i18n from "@/i18n";

function decisionLabel(decision: FileProjectReviewOperationDecision): string {
  const map: Record<FileProjectReviewOperationDecision, string> = {
    PENDING: i18n.t("fileReview.pending"),
    ACCEPTED: i18n.t("fileReview.kept"),
    REJECTED: i18n.t("fileReview.undone"),
    REVISED: i18n.t("fileReview.revised"),
    SUPERSEDED_BY_USER_EDIT: i18n.t("fileReview.replacedByUser"),
  };
  return map[decision];
}

function kindLabel(kind: string): string {
  const map: Record<string, string> = {
    create: i18n.t("fileReview.added"),
    update: i18n.t("fileReview.modified"),
    delete: i18n.t("fileReview.deleted"),
    move: i18n.t("fileReview.moved"),
    reorder: i18n.t("fileReview.reordered"),
    select_asset: i18n.t("fileReview.selectAsset"),
  };
  return map[kind] ?? kind;
}

function fieldLabel(token: string): string {
  const map: Record<string, string> = {
    name: i18n.t("fileReview.name"),
    title: i18n.t("fileReview.titleField"),
    description: i18n.t("fileReview.description"),
    creative_brief: i18n.t("fileReview.creativeBrief"),
    creative_direction: i18n.t("fileReview.creativeDirection"),
    prompt: i18n.t("fileReview.prompt"),
    camera: i18n.t("fileReview.camera"),
    framing: i18n.t("fileReview.framing"),
    duration_seconds: i18n.t("fileReview.duration"),
    narration: i18n.t("fileReview.narration"),
    dialogue: i18n.t("fileReview.dialogue"),
  };
  return map[token] ?? token;
}

function artifactKindLabel(kind: string): string {
  const map: Record<string, string> = {
    r2v_storyboard_image: i18n.t("fileReview.storyboard"),
    visual_asset_image: i18n.t("fileReview.characterVisual"),
    r2v_video: i18n.t("fileReview.video"),
  };
  return map[kind] ?? "";
}

function operationLocation(operation: FileProjectReviewOperation): string {
  return (
    operation.json_pointer ??
    (operation.file_id ? `file:${operation.file_id}` : null) ??
    operation.target_ref ??
    "unknown"
  );
}

/** Readable change-location summary: real element/asset names and field labels
 * instead of a bare JSON pointer. */
function operationSummary(
  operation: FileProjectReviewOperation,
  elementNames: Record<string, string>,
): string {
  const locator = operation.ui_locator ?? {};
  const pointer = operation.json_pointer ?? "";
  const lastToken = pointer.split("/").filter(Boolean).pop() ?? "";
  const resolvedFieldLabel = fieldLabel(lastToken);
  const parts: string[] = [];
  if (locator.elementId)
    parts.push(
      elementNames[locator.elementId] ??
        `${i18n.t("fileReview.content")} ${locator.elementId}`,
    );
  else if (locator.assetId)
    parts.push(`${i18n.t("fileReview.asset")} ${locator.assetId}`);
  if (resolvedFieldLabel) parts.push(resolvedFieldLabel);
  return parts.length > 0 ? parts.join(" · ") : operationLocation(operation);
}

function previewText(value: unknown, limit = 26): string {
  if (value === null || value === undefined) return "—";
  const text = typeof value === "string" ? value : JSON.stringify(value) ?? "—";
  const normalized = text.replace(/\s+/g, " ").trim();
  return normalized.length > limit
    ? `${normalized.slice(0, limit)}…`
    : normalized || "—";
}

/** One-line change preview so users know what changed without navigating;
 * the full diff is shown in place at the original content. */
const CREATION_TYPE_LABEL_KEYS: Record<string, string> = {
  r2v: "fileReview.creationTypeR2v",
  t2v: "fileReview.creationTypeT2v",
  i2v: "fileReview.creationTypeI2v",
  s2v: "fileReview.creationTypeS2v",
  edit: "fileReview.creationTypeEdit",
  overlay: "fileReview.creationTypeOverlay",
  transition: "fileReview.creationTypeTransition",
  audio: "fileReview.creationTypeAudio",
};

function creationTypeLabel(type: string): string {
  const key = CREATION_TYPE_LABEL_KEYS[type];
  return key ? i18n.t(key) : type;
}

/** Structured summary for a whole Timeline Element value; null when the value
 * is not an element (falls back to the raw-text preview). */
function describeElementValue(
  value: unknown,
  ticksPerSecond: number,
): string | null {
  if (!value || typeof value !== "object") return null;
  const el = value as Record<string, any>;
  const creation = el.creation;
  if (!creation || typeof creation !== "object" || !creation.type) return null;
  const parts: string[] = [creationTypeLabel(String(creation.type))];
  if (el.label) parts.push(`「${el.label}」`);
  const span = el.span;
  if (
    span &&
    typeof span.start_tick === "number" &&
    typeof span.duration_tick === "number" &&
    ticksPerSecond > 0
  ) {
    const start = span.start_tick / ticksPerSecond;
    const end = (span.start_tick + span.duration_tick) / ticksPerSecond;
    parts.push(`${start.toFixed(0)}s–${end.toFixed(0)}s`);
  }
  if (creation.type === "audio") {
    parts.push(i18n.t("fileReview.audioGain", { gain: creation.gain_db ?? 0 }));
    if (creation.pan)
      parts.push(i18n.t("fileReview.audioPan", { pan: creation.pan }));
  }
  return parts.join(" · ");
}

function operationPreview(
  operation: FileProjectReviewOperation,
  ticksPerSecond = 1000,
): string {
  if (operation.kind === "create") {
    const described = describeElementValue(operation.after, ticksPerSecond);
    return `${i18n.t("fileReview.addedLabel")}${
      described ?? previewText(operation.after)
    }`;
  }
  if (operation.kind === "delete") {
    const described = describeElementValue(operation.before, ticksPerSecond);
    return `${i18n.t("fileReview.deletedLabel")}${
      described ?? previewText(operation.before)
    }`;
  }
  return `${previewText(operation.before)} → ${previewText(operation.after)}`;
}

export function reviewMediaLocator(
  review: FileProjectReviewRecord,
): Record<string, string> | null {
  for (const operation of review.operations) {
    const locator = operation.ui_locator;
    if (
      locator &&
      (locator.mediaType === "image" || locator.mediaType === "video")
    ) {
      return locator;
    }
  }
  return null;
}

/**
 * Number of pending "units": the internal operations of a media-generation
 * review (file/version/slot/bookkeeping fields) are one artifact to the user,
 * so they count as 1; text reviews count pending operations individually.
 */
export function reviewPendingUnits(review: FileProjectReviewRecord): number {
  const pending = review.operations.filter(
    (operation) => operation.decision === "PENDING",
  ).length;
  if (pending === 0) return 0;
  return reviewMediaLocator(review) ? 1 : pending;
}

function mediaLabel(locator: Record<string, string>): string {
  if (locator.artifactKind && artifactKindLabel(locator.artifactKind)) {
    return artifactKindLabel(locator.artifactKind);
  }
  return locator.mediaType === "video"
    ? i18n.t("fileReview.video")
    : i18n.t("fileReview.image");
}

/** Compact title used by the decision tray's stacked stubs / indicator dots. */
export function reviewTrayLabel(review: FileProjectReviewRecord): string {
  const locator = reviewMediaLocator(review);
  if (locator)
    return `${mediaLabel(locator)}${i18n.t("fileReview.reviewLabel")}`;
  const pending = review.operations.filter(
    (operation) => operation.decision === "PENDING",
  ).length;
  return `${i18n.t("fileReview.textReview")}${pending} ${i18n.t(
    "fileReview.places",
  )}`;
}

export default function FileProjectReviewPanel({
  projectId,
  review,
}: {
  projectId: string;
  review: FileProjectReviewRecord;
}) {
  const { t } = useTranslation();
  const decisionInFlight = useFileProjectReviewStore(
    (state) => state.decisionInFlight,
  );
  const syncError = useFileProjectReviewStore((state) => state.syncError);
  const decide = useFileProjectReviewStore((state) => state.decide);
  const project = useProjectSnapshotStore((state) => state.project);
  const [localBusy, setLocalBusy] = useState(false);
  const [rejectionOperations, setRejectionOperations] = useState<
    FileProjectReviewOperation[]
  >([]);

  const elementNames = (() => {
    const timeline = selectPrimaryTimeline(project);
    const names: Record<string, string> = {};
    if (timeline) {
      Object.values(timeline.elements_by_id).forEach((element) => {
        names[element.element_id] = element.label || element.element_id;
      });
    }
    return names;
  })();
  const ticksPerSecond =
    selectPrimaryTimeline(project)?.ticks_per_second ?? 1000;
  const assetName = (assetId: string): string =>
    project?.visual.entities.items[assetId]?.name || assetId;
  const mediaOwnerLine = (locator: Record<string, string>): string => {
    if (locator.elementId) {
      const name = elementNames[locator.elementId] ?? locator.elementId;
      return `「${name}」${i18n.t("fileReview.of")}${mediaLabel(locator)}`;
    }
    if (locator.assetId) {
      return `「${assetName(locator.assetId)}」${i18n.t("fileReview.imageOf")}`;
    }
    return mediaLabel(locator);
  };

  if (review.status !== "PENDING") return null;
  const pending = review.operations.filter(
    (operation) => operation.decision === "PENDING",
  );
  const busy = decisionInFlight || localBusy;
  const mediaLocator = reviewMediaLocator(review);
  const pendingUnits = mediaLocator
    ? Math.min(pending.length, 1)
    : pending.length;

  const submit = async (
    operations: FileProjectReviewOperation[],
    decision: FileProjectReviewDecision,
    rejectionFeedback?: FileProjectReviewRejectionFeedback,
  ): Promise<boolean> => {
    if (operations.length === 0) return false;
    const affectedUnits = mediaLocator ? 1 : operations.length;
    setLocalBusy(true);
    try {
      const decisionItems = operations.map((operation) => ({
        operation_id: operation.operation_id,
        decision,
      }));
      if (rejectionFeedback) {
        await decide(
          projectId,
          review.review_id,
          decisionItems,
          rejectionFeedback,
        );
      } else {
        await decide(projectId, review.review_id, decisionItems);
      }
      message.success(
        decision === "ACCEPT"
          ? t("fileReview.keptCount", { count: affectedUnits })
          : rejectionFeedback?.action === "UNDO_AND_REGENERATE"
          ? t("fileReview.undoneCount", { count: affectedUnits })
          : t("fileReview.undoneCountSimple", { count: affectedUnits }),
      );
      return true;
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
      return false;
    } finally {
      setLocalBusy(false);
    }
  };

  const openLocator = (
    locator: Record<string, string>,
    fallbackField?: string | null,
  ) => {
    const field = locator.field ?? fallbackField ?? undefined;
    navigateToLocator(projectId, locator, {
      review: true,
      field: field ?? undefined,
      description: t("fileReview.reviewOrViewChanges"),
    });
  };

  return (
    <section
      data-file-project-review={review.review_id}
      className="mb-3 rounded-xl border border-[var(--color-accent)]/35 bg-[var(--color-bg-primary)]/70 p-2.5"
    >
      <OnboardingHint hintKey="review" className="mb-2">
        {t("fileReview.firstTimeDesc")}
      </OnboardingHint>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-primary)]">
            {mediaLocator ? (
              mediaLocator.mediaType === "video" ? (
                <Video className="h-3.5 w-3.5 text-[var(--color-accent)]" />
              ) : (
                <ImageIcon className="h-3.5 w-3.5 text-[var(--color-accent)]" />
              )
            ) : (
              <FileDiff className="h-3.5 w-3.5 text-[var(--color-accent)]" />
            )}
            {mediaLocator
              ? `${mediaLabel(mediaLocator)}${t("fileReview.reviewLabel")}`
              : t("fileReview.fileProjectReview")}
            <span className="rounded-full bg-[var(--color-accent-soft)] px-1.5 py-0.5 text-[9px] text-[var(--color-accent)]">
              {pendingUnits} {t("fileReview.pendingReview")}
            </span>
          </h3>
          <p
            className="mt-0.5 truncate text-[9px] text-[var(--color-text-tertiary)]"
            title={`${review.round_id} · generation ${review.baseline_generation} → ${review.candidate_generation}`}
          >
            {mediaLocator
              ? mediaOwnerLine(mediaLocator)
              : `${pending.length} ${t("fileReview.textChangesPending")}`}
          </p>
        </div>
        <div className="flex shrink-0 gap-1">
          <button
            type="button"
            disabled={busy || pending.length === 0}
            onClick={() => void submit(pending, "ACCEPT")}
            className="rounded-md bg-[var(--color-accent)] px-2 py-1 text-[10px] font-medium text-white disabled:opacity-50"
          >
            {mediaLocator ? t("fileReview.keep") : t("fileReview.keepAll")}
          </button>
          <button
            type="button"
            disabled={busy || pending.length === 0}
            onClick={() => setRejectionOperations(pending)}
            className="rounded-md border border-[var(--color-border)] px-2 py-1 text-[10px] font-medium text-[var(--color-text-secondary)] disabled:opacity-50"
          >
            {mediaLocator ? t("fileReview.undo") : t("fileReview.undoAll")}
          </button>
        </div>
      </div>

      {syncError && (
        <p
          role="alert"
          className="mt-2 rounded-md bg-[var(--color-warning-soft)] px-2 py-1 text-[10px] text-[var(--color-warning)]"
        >
          {t("fileReview.syncError")}
          {syncError}
        </p>
      )}

      {mediaLocator ? (
        <MediaReviewBody
          locator={mediaLocator}
          ownerLine={mediaOwnerLine(mediaLocator)}
          onOpen={() => openLocator(mediaLocator)}
        />
      ) : (
        <ul className="mt-2 space-y-2">
          {review.operations.map((operation) => {
            const operationPending = operation.decision === "PENDING";
            const location = operationLocation(operation);
            const locator = operation.ui_locator ?? {};
            const canJump =
              operation.kind !== "delete" &&
              (Boolean(locator.field) || Boolean(operation.json_pointer));
            return (
              <li
                key={operation.operation_id}
                data-file-review-operation={operation.operation_id}
                className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] p-2"
              >
                {/* flex bases keep the summary readable on a very narrow
                    dock: the action cluster wraps below instead of squeezing
                    the break-all title into a one-character column. */}
                <div className="flex flex-wrap items-start justify-between gap-x-2 gap-y-1">
                  <div className="min-w-0 flex-[1_1_150px]">
                    <p
                      className="break-all text-[11px] font-semibold text-[var(--color-text-primary)]"
                      title={location}
                    >
                      {operationSummary(operation, elementNames)}
                    </p>
                    <p className="mt-0.5 text-[9px] text-[var(--color-text-tertiary)]">
                      {kindLabel(operation.kind)} ·{" "}
                      {decisionLabel(operation.decision)}
                      {canJump && ` · ${t("fileReview.clickViewToCompare")}`}
                    </p>
                    <p
                      className="mt-0.5 truncate text-[9px] text-[var(--color-text-secondary)]"
                      title={operationPreview(operation, ticksPerSecond)}
                    >
                      {operationPreview(operation, ticksPerSecond)}
                    </p>
                  </div>
                  <div className="ml-auto flex shrink-0 gap-1">
                    {canJump && (
                      <button
                        type="button"
                        aria-label={`${t("fileReview.view")} ${location}`}
                        onClick={() =>
                          openLocator(locator, operation.json_pointer)
                        }
                        className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-soft)] hover:text-[var(--color-accent)]"
                      >
                        <Eye className="h-3 w-3" />
                        {t("fileReview.view")}
                      </button>
                    )}
                    {operationPending && (
                      <>
                        <button
                          type="button"
                          aria-label={`${t("fileReview.keepItem")} ${location}`}
                          disabled={busy}
                          onClick={() => void submit([operation], "ACCEPT")}
                          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-accent)] hover:bg-[var(--color-accent-soft)] disabled:opacity-50"
                        >
                          <Check className="h-3 w-3" />
                          {t("fileReview.keepItem")}
                        </button>
                        <button
                          type="button"
                          aria-label={`${t("fileReview.undoItem")} ${location}`}
                          disabled={busy}
                          onClick={() => setRejectionOperations([operation])}
                          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-text-tertiary)] hover:text-[var(--color-danger)] disabled:opacity-50"
                        >
                          <Undo2 className="h-3 w-3" />
                          {t("fileReview.undoItem")}
                        </button>
                      </>
                    )}
                  </div>
                </div>
                {operation.kind === "delete" && (
                  <div className="mt-2">
                    {/* Deleted content has no original location left in the workspace
                        to jump to, so show what was removed right here. */}
                    <DiffView
                      before={operation.before}
                      after={operation.after}
                    />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <RejectionFeedbackModal
        open={rejectionOperations.length > 0}
        busy={busy}
        targetCount={mediaLocator ? 1 : rejectionOperations.length}
        onCancel={() => setRejectionOperations([])}
        onSubmit={(feedback) => {
          void (async () => {
            const submitted = await submit(
              rejectionOperations,
              "REJECT",
              feedback,
            );
            if (submitted) setRejectionOperations([]);
          })();
        }}
      />
    </section>
  );
}

function MediaReviewBody({
  locator,
  ownerLine,
  onOpen,
}: {
  locator: Record<string, string>;
  ownerLine: string;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const versionId = locator.artifactVersionId;
  const mediaUrl = versionId ? getArtifactVersionMediaUrl(versionId) : null;
  const isVideo = locator.mediaType === "video";
  return (
    <div
      data-file-review-media={versionId ?? ""}
      className="mt-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] p-2"
    >
      <div className="overflow-hidden rounded-md bg-[var(--color-bg-secondary)]">
        {mediaUrl ? (
          isVideo ? (
            <video
              src={mediaUrl}
              controls
              className="max-h-48 w-full object-contain"
            />
          ) : (
            <img
              src={mediaUrl}
              alt={mediaLabel(locator)}
              className="max-h-48 w-full object-contain"
            />
          )
        ) : (
          <p className="p-4 text-center text-[10px] text-[var(--color-text-tertiary)]">
            {t("fileReview.previewUnavailable")}
          </p>
        )}
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <p
          className="min-w-0 truncate text-[10px] text-[var(--color-text-secondary)]"
          title={`${locator.elementId ?? locator.assetId ?? ""}`}
        >
          {ownerLine}
        </p>
        <button
          type="button"
          onClick={onOpen}
          className="flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-accent)] hover:bg-[var(--color-accent-soft)]"
        >
          <Eye className="h-3 w-3" />
          {t("fileReview.viewGenDetail")}
        </button>
      </div>
    </div>
  );
}
