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
import type {
  FileProjectReviewDecision,
  FileProjectReviewOperation,
  FileProjectReviewOperationDecision,
  FileProjectReviewRecord,
} from "@/contracts/creator";
import { getArtifactVersionMediaUrl } from "@/api/creator";
import { navigateToLocator } from "@/routing/locators";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import OnboardingHint from "@/components/onboarding/OnboardingHint";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { selectPrimaryTimeline } from "@/selectors/timelineElementSelectors";
import DiffView from "./DiffView";

const DECISION_LABELS: Record<FileProjectReviewOperationDecision, string> = {
  PENDING: "待审",
  ACCEPTED: "已保留",
  REJECTED: "已撤销",
  REVISED: "已修订",
  SUPERSEDED_BY_USER_EDIT: "已被用户编辑替代",
};

const KIND_LABELS: Record<string, string> = {
  create: "新增",
  update: "修改",
  delete: "删除",
  move: "移动",
  reorder: "重排",
  select_asset: "选择资产",
};

const FIELD_LABELS: Record<string, string> = {
  name: "名称",
  title: "标题",
  description: "描述",
  creative_brief: "创作总纲",
  creative_direction: "创作方向",
  prompt: "提示词",
  camera: "运镜",
  framing: "景别",
  duration_seconds: "时长",
  narration: "旁白",
  dialogue: "台词",
};

const ARTIFACT_KIND_LABELS: Record<string, string> = {
  r2v_storyboard_image: "分镜图",
  visual_asset_image: "角色 / 视觉资产图",
  r2v_video: "视频",
};

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
  const fieldLabel = FIELD_LABELS[lastToken] ?? lastToken;
  const parts: string[] = [];
  if (locator.elementId)
    parts.push(elementNames[locator.elementId] ?? `内容 ${locator.elementId}`);
  else if (locator.assetId) parts.push(`资产 ${locator.assetId}`);
  if (fieldLabel) parts.push(fieldLabel);
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
function operationPreview(operation: FileProjectReviewOperation): string {
  if (operation.kind === "create")
    return `新增：${previewText(operation.after)}`;
  if (operation.kind === "delete")
    return `删除：${previewText(operation.before)}`;
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
  if (locator.artifactKind && ARTIFACT_KIND_LABELS[locator.artifactKind]) {
    return ARTIFACT_KIND_LABELS[locator.artifactKind];
  }
  return locator.mediaType === "video" ? "视频" : "图片";
}

/** Compact title used by the decision tray's stacked stubs / indicator dots. */
export function reviewTrayLabel(review: FileProjectReviewRecord): string {
  const locator = reviewMediaLocator(review);
  if (locator) return `${mediaLabel(locator)}审阅`;
  const pending = review.operations.filter(
    (operation) => operation.decision === "PENDING",
  ).length;
  return `文本审阅 · ${pending} 处`;
}

export default function FileProjectReviewPanel({
  projectId,
  review,
}: {
  projectId: string;
  review: FileProjectReviewRecord;
}) {
  const decisionInFlight = useFileProjectReviewStore(
    (state) => state.decisionInFlight,
  );
  const syncError = useFileProjectReviewStore((state) => state.syncError);
  const decide = useFileProjectReviewStore((state) => state.decide);
  const project = useProjectSnapshotStore((state) => state.project);
  const [localBusy, setLocalBusy] = useState(false);

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
  const assetName = (assetId: string): string =>
    project?.visual.entities.items[assetId]?.name || assetId;
  const mediaOwnerLine = (locator: Record<string, string>): string => {
    if (locator.elementId) {
      const name = elementNames[locator.elementId] ?? locator.elementId;
      return `「${name}」的${mediaLabel(locator)}`;
    }
    if (locator.assetId) {
      return `「${assetName(locator.assetId)}」的形象图`;
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
  ) => {
    if (operations.length === 0) return;
    setLocalBusy(true);
    try {
      await decide(
        projectId,
        review.review_id,
        operations.map((operation) => ({
          operation_id: operation.operation_id,
          decision,
        })),
      );
      message.success(
        decision === "ACCEPT"
          ? `已保留 ${operations.length} 处修改`
          : `已撤销 ${operations.length} 处修改`,
      );
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
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
      description: "审阅 / 查看修改",
    });
  };

  return (
    <section
      data-file-project-review={review.review_id}
      className="mb-3 rounded-xl border border-[var(--color-accent)]/35 bg-[var(--color-bg-primary)]/70 p-2.5"
    >
      <OnboardingHint hintKey="review" className="mb-2">
        首次说明：Agent
        对项目的每处修改都会在这里待你审阅：「保留」采纳修改，「撤销」回退到修改前；也可逐条处理。
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
            {mediaLocator ? `${mediaLabel(mediaLocator)}审阅` : "文件项目修改"}
            <span className="rounded-full bg-[var(--color-accent-soft)] px-1.5 py-0.5 text-[9px] text-[var(--color-accent)]">
              {pendingUnits} 待审
            </span>
          </h3>
          <p
            className="mt-0.5 truncate text-[9px] text-[var(--color-text-tertiary)]"
            title={`${review.round_id} · generation ${review.baseline_generation} → ${review.candidate_generation}`}
          >
            {mediaLocator
              ? mediaOwnerLine(mediaLocator)
              : `共 ${pending.length} 处待确认的文本修改`}
          </p>
        </div>
        <div className="flex shrink-0 gap-1">
          <button
            type="button"
            disabled={busy || pending.length === 0}
            onClick={() => void submit(pending, "ACCEPT")}
            className="rounded-md bg-[var(--color-accent)] px-2 py-1 text-[10px] font-medium text-white disabled:opacity-50"
          >
            {mediaLocator ? "保留" : "全部保留"}
          </button>
          <button
            type="button"
            disabled={busy || pending.length === 0}
            onClick={() => void submit(pending, "REJECT")}
            className="rounded-md border border-[var(--color-border)] px-2 py-1 text-[10px] font-medium text-[var(--color-text-secondary)] disabled:opacity-50"
          >
            {mediaLocator ? "撤销" : "全部撤销"}
          </button>
        </div>
      </div>

      {syncError && (
        <p
          role="alert"
          className="mt-2 rounded-md bg-[var(--color-warning-soft)] px-2 py-1 text-[10px] text-[var(--color-warning)]"
        >
          同步异常，当前显示上次成功结果：{syncError}
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
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p
                      className="break-all text-[11px] font-semibold text-[var(--color-text-primary)]"
                      title={location}
                    >
                      {operationSummary(operation, elementNames)}
                    </p>
                    <p className="mt-0.5 text-[9px] text-[var(--color-text-tertiary)]">
                      {KIND_LABELS[operation.kind] ?? operation.kind} ·{" "}
                      {DECISION_LABELS[operation.decision]}
                      {canJump && " · 点击“查看”在原文处对比修改"}
                    </p>
                    <p
                      className="mt-0.5 truncate text-[9px] text-[var(--color-text-secondary)]"
                      title={operationPreview(operation)}
                    >
                      {operationPreview(operation)}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    {canJump && (
                      <button
                        type="button"
                        aria-label={`查看 ${location}`}
                        onClick={() =>
                          openLocator(locator, operation.json_pointer)
                        }
                        className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-text-secondary)] hover:bg-[var(--color-accent-soft)] hover:text-[var(--color-accent)]"
                      >
                        <Eye className="h-3 w-3" />
                        查看
                      </button>
                    )}
                    {operationPending && (
                      <>
                        <button
                          type="button"
                          aria-label={`保留 ${location}`}
                          disabled={busy}
                          onClick={() => void submit([operation], "ACCEPT")}
                          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-accent)] hover:bg-[var(--color-accent-soft)] disabled:opacity-50"
                        >
                          <Check className="h-3 w-3" />
                          保留
                        </button>
                        <button
                          type="button"
                          aria-label={`撤销 ${location}`}
                          disabled={busy}
                          onClick={() => void submit([operation], "REJECT")}
                          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-text-tertiary)] hover:text-[var(--color-danger)] disabled:opacity-50"
                        >
                          <Undo2 className="h-3 w-3" />
                          撤销
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
            预览不可用
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
          查看生成详情
        </button>
      </div>
    </div>
  );
}
