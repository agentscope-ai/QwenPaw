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
import DiffView from "./DiffView";
import { creatorTargetLabel } from "@/lib/creatorPresentation";
import { fileReviewPresentation } from "@/lib/fileProjectReviewPresentation";
import {
  isSystemVersionReviewOperation,
  pendingUserReviewOperations,
  userReviewOperations,
} from "@/lib/fileProjectReviewDecisions";
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

function artifactKindLabel(kind: string): string {
  const map: Record<string, string> = {
    r2v_storyboard_image: i18n.t("fileReview.storyboard"),
    visual_asset_image: i18n.t("fileReview.characterVisual"),
    r2v_video: i18n.t("fileReview.video"),
  };
  return map[kind] ?? "";
}

export function reviewMediaLocator(
  review: FileProjectReviewRecord,
): Record<string, string> | null {
  for (const operation of userReviewOperations(review)) {
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
  const pending = pendingUserReviewOperations(review).length;
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
  const pending = pendingUserReviewOperations(review).length;
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

  const mediaOwnerLine = (locator: Record<string, string>): string => {
    if (locator.elementId) {
      const name = creatorTargetLabel(`element:${locator.elementId}`, project);
      return `「${name}」${i18n.t("fileReview.of")}${mediaLabel(locator)}`;
    }
    if (locator.assetId) {
      return `「${creatorTargetLabel(
        `visual-entity:${locator.assetId}`,
        project,
      )}」${i18n.t("fileReview.imageOf")}`;
    }
    return mediaLabel(locator);
  };

  if (review.status !== "PENDING") return null;
  const operations = userReviewOperations(review);
  const pending = pendingUserReviewOperations(review);
  if (pending.length === 0) return null;
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
    operations = operations.filter(
      (operation) => !isSystemVersionReviewOperation(operation),
    );
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
    } catch {
      message.error(t("fileReview.public.decisionFailed"));
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
            <span className="rounded-full bg-[var(--color-accent-soft)] px-1.5 py-0.5 text-[11px] text-[var(--color-accent)]">
              {pendingUnits} {t("fileReview.pendingReview")}
            </span>
          </h3>
          <p className="mt-0.5 truncate text-[11px] text-[var(--color-text-tertiary)]">
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
            className="rounded-md bg-[var(--color-text-primary)] px-2 py-1 text-[11px] font-medium text-[var(--color-bg-primary)] disabled:opacity-50"
          >
            {mediaLocator ? t("fileReview.keep") : t("fileReview.keepAll")}
          </button>
          <button
            type="button"
            disabled={busy || pending.length === 0}
            onClick={() => setRejectionOperations(pending)}
            className="rounded-md border border-[var(--color-border)] px-2 py-1 text-[11px] font-medium text-[var(--color-text-secondary)] disabled:opacity-50"
          >
            {mediaLocator ? t("fileReview.undo") : t("fileReview.undoAll")}
          </button>
        </div>
      </div>

      {syncError && (
        <p
          role="alert"
          className="mt-2 rounded-md bg-[var(--color-warning-soft)] px-2 py-1 text-[11px] text-[var(--color-warning)]"
        >
          {t("fileReview.public.syncUnavailable")}
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
          {operations.map((operation) => {
            const operationPending = operation.decision === "PENDING";
            const presentation = fileReviewPresentation(operation, project);
            const locator = operation.ui_locator ?? {};
            const canJump =
              presentation.canInspect &&
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
                      className="break-words text-[12px] leading-5 font-semibold text-[var(--color-text-primary)]"
                      title={presentation.title}
                    >
                      {presentation.title}
                    </p>
                    <p className="mt-0.5 text-[11px] text-[var(--color-text-tertiary)]">
                      {presentation.kindLabel} ·{" "}
                      {decisionLabel(operation.decision)}
                      {canJump && ` · ${t("fileReview.clickViewToCompare")}`}
                    </p>
                    <p
                      className="mt-1 line-clamp-2 break-words text-[12px] leading-5 text-[var(--color-text-secondary)]"
                      title={presentation.preview}
                    >
                      {presentation.preview}
                    </p>
                  </div>
                  <div className="ml-auto flex shrink-0 gap-1">
                    {canJump && (
                      <button
                        type="button"
                        aria-label={`${t("fileReview.view")} ${
                          presentation.title
                        }`}
                        onClick={() =>
                          openLocator(locator, operation.json_pointer)
                        }
                        className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-soft)] hover:text-[var(--color-accent)]"
                      >
                        <Eye className="h-3 w-3" />
                        {t("fileReview.view")}
                      </button>
                    )}
                    {operationPending && (
                      <>
                        <button
                          type="button"
                          aria-label={`${t("fileReview.keepItem")} ${
                            presentation.title
                          }`}
                          disabled={busy}
                          onClick={() => void submit([operation], "ACCEPT")}
                          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-[var(--color-accent)] hover:bg-[var(--color-accent-soft)] disabled:opacity-50"
                        >
                          <Check className="h-3 w-3" />
                          {t("fileReview.keepItem")}
                        </button>
                        <button
                          type="button"
                          aria-label={`${t("fileReview.undoItem")} ${
                            presentation.title
                          }`}
                          disabled={busy}
                          onClick={() => setRejectionOperations([operation])}
                          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-[var(--color-text-tertiary)] hover:text-[var(--color-danger)] disabled:opacity-50"
                        >
                          <Undo2 className="h-3 w-3" />
                          {t("fileReview.undoItem")}
                        </button>
                      </>
                    )}
                  </div>
                </div>
                {operation.kind === "delete" && presentation.hasTextDiff && (
                  <div className="mt-2 [&_[data-review-diff]]:font-sans [&_[data-review-diff]]:text-[12px] [&_[data-review-diff]]:leading-5">
                    {/* Deleted content has no original location left in the workspace
                        to jump to, so show what was removed right here. */}
                    <DiffView
                      before={presentation.beforeText}
                      after={presentation.afterText}
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
          <p className="p-4 text-center text-[11px] text-[var(--color-text-tertiary)]">
            {t("fileReview.previewUnavailable")}
          </p>
        )}
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <p
          className="min-w-0 truncate text-[11px] text-[var(--color-text-secondary)]"
          title={ownerLine}
        >
          {ownerLine}
        </p>
        <button
          type="button"
          onClick={onOpen}
          className="flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-[var(--color-accent)] hover:bg-[var(--color-accent-soft)]"
        >
          <Eye className="h-3 w-3" />
          {t("fileReview.viewGenDetail")}
        </button>
      </div>
    </div>
  );
}
