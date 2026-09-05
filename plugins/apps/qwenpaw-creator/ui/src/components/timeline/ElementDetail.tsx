import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Input, InputNumber, Select, message } from "antd";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
import {
  ArrowUpRight,
  Box,
  Clock3,
  Film,
  Layers3,
  Music2,
  Sparkles,
  WandSparkles,
  X,
} from "lucide-react";
import type {
  ProjectDocument,
  R2VReferenceOrderResponse,
  TaskView,
  TimelineDocument,
  TimelineElementDocument,
} from "@/contracts/creator";
import {
  getArtifactVersionMediaUrl,
  getAssetVersionMediaUrl,
  getR2VReferenceOrder,
} from "@/api/creator";
import { regenerateNarration } from "@/api/creator/voice";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import {
  TRANSITION_KIND_LABEL,
  classifyElementTrack,
  resolveElementOutputs,
  resolveElementVisualMeta,
} from "@/selectors/timelineElementSelectors";
import { outputLabel } from "@/lib/creatorPresentation";
import { projectJsonPointer } from "@/lib/projectJsonPointer";
import { storyboardOfOwner } from "@/components/workbench/referenceThumbs";
import InlineReviewDiff from "@/components/agent/InlineReviewDiff";

interface ElementDetailProps {
  project: ProjectDocument;
  timeline: TimelineDocument;
  element: TimelineElementDocument | null;
  tasks: TaskView[];
  applying: boolean;
  dirtyCount: number;
  conflictPaths: string[];
  /** Rail-hosted overview drops the card border/radius (design 83:13383). */
  frameless?: boolean;
  onClose: () => void;
  onChange: (mutator: (element: TimelineElementDocument) => void) => void;
  onApply: () => void;
  onDiscard: () => void;
  onAcceptConflicts: () => void;
  onOpenWorkbench: (element: TimelineElementDocument) => void;
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-tertiary)]">
      {children}
    </span>
  );
}

function TextField({
  label,
  value,
  multiline = false,
  path,
  field,
  disabled = false,
  onChange,
}: {
  label: string;
  value: string;
  multiline?: boolean;
  path: string;
  field: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label
      data-creator-field={field}
      data-creator-path={path}
      data-creator-field-label={label}
      className="block"
    >
      <FieldLabel>{label}</FieldLabel>
      {multiline ? (
        <Input.TextArea
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          autoSize={{ minRows: 3, maxRows: 8 }}
        />
      ) : (
        <Input
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      <InlineReviewDiff pointer={path} />
    </label>
  );
}

function getTransitionKindOptions() {
  return [
    "crossfade",
    "fadeblack",
    "fadewhite",
    "dissolve",
    "wipeleft",
    "cut",
  ].map((kind) => ({
    value: kind,
    label: `${i18n.t(TRANSITION_KIND_LABEL[kind] ?? "")}（${kind}）`,
  }));
}

function getTransitionEasingOptions(t: (key: string) => string) {
  return [
    { value: "linear", label: t("elementDetail.easingOptions.linear") },
    { value: "ease-in", label: t("elementDetail.easingOptions.easeIn") },
    { value: "ease-out", label: t("elementDetail.easingOptions.easeOut") },
    { value: "ease-in-out", label: t("elementDetail.easingOptions.easeInOut") },
  ];
}

function taskStatus(
  element: TimelineElementDocument,
  tasks: TaskView[],
  t: (key: string) => string,
) {
  const task = tasks.find(
    (item) => item.targetRef === `element:${element.element_id}`,
  );
  if (task?.status === "RUNNING" || task?.status === "QUEUED")
    return {
      label:
        task.status === "RUNNING"
          ? t("elementDetail.generating")
          : t("elementDetail.waiting"),
      tone: "text-[var(--color-warning)] bg-[var(--color-warning-soft)]",
      running: true,
    };
  if (task?.status === "FAILED" || task?.status === "QUARANTINED")
    return {
      label: t("elementDetail.genFailed"),
      tone: "text-[var(--color-danger)] bg-[var(--color-danger-soft)]",
      running: false,
    };
  if (Object.keys(element.outputs).length)
    return {
      label: t("elementDetail.hasProduct"),
      tone: "text-[var(--color-success)] bg-[var(--color-success-soft)]",
      running: false,
    };
  return {
    label: t("elementDetail.editable"),
    tone: "text-[var(--color-text-secondary)] bg-[var(--color-bg-secondary)]",
    running: false,
  };
}

function sec(tick: number, ticksPerSecond: number): number {
  return Number((tick / ticksPerSecond).toFixed(3));
}

function getLocationFields(t: (key: string) => string) {
  return {
    x: t("elementDetail.xPosition"),
    y: t("elementDetail.yPosition"),
    width: t("elementDetail.width"),
    height: t("elementDetail.height"),
    rotation_degrees: t("elementDetail.rotation"),
    opacity: t("elementDetail.opacity"),
  } as const;
}

// ── 总览层积木（排版驱动：pill / 小节标签 / 主句 / 缩略图） ──

function TypeGlyph({ element }: { element: TimelineElementDocument }) {
  const track = classifyElementTrack(element);
  if (element.creation.type === "audio" || track === null)
    return <Music2 className="h-3.5 w-3.5" />;
  if (track === "subtitle") return <Layers3 className="h-3.5 w-3.5" />;
  if (track === "motion") return <Sparkles className="h-3.5 w-3.5" />;
  if (track === "transition") return <WandSparkles className="h-3.5 w-3.5" />;
  if (track === "ai") return <Sparkles className="h-3.5 w-3.5" />;
  return <Film className="h-3.5 w-3.5" />;
}

function Pill({
  tone,
  children,
}: {
  tone?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-[var(--color-bg-secondary)] px-2.5 py-[3px] text-[10.5px] font-medium text-[var(--color-text-secondary)]"
      style={
        tone
          ? {
              background: `color-mix(in srgb, ${tone} 10%, transparent)`,
              color: `color-mix(in srgb, ${tone} 85%, #000)`,
            }
          : undefined
      }
    >
      {children}
    </span>
  );
}

function LeadText({
  intent,
  continuity,
}: {
  intent?: string;
  continuity?: string;
}) {
  if (!intent && !continuity) return null;
  return (
    <p
      data-element-overview-lead
      className="text-[13.5px] font-medium leading-[1.75] text-[var(--color-text-primary)]"
    >
      {intent}
      {continuity ? (
        <span className="mt-1 block text-xs font-normal text-[var(--color-text-secondary)]">
          ↳ {continuity}
        </span>
      ) : null}
    </p>
  );
}

function RefThumb({
  url,
  name,
  index,
}: {
  url: string | null;
  name: string;
  index?: number;
}) {
  return (
    <span className="relative inline-block" title={name}>
      {url ? (
        <img
          src={url}
          alt={name}
          className="h-10 w-[54px] rounded-[10px] border border-[var(--color-border)] object-cover"
        />
      ) : (
        <span className="flex h-10 w-[54px] items-center justify-center rounded-[10px] border border-dashed border-[var(--color-border)] px-1 text-center text-[9px] leading-tight text-[var(--color-text-tertiary)]">
          {name.slice(0, 6)}
        </span>
      )}
      {index != null && (
        <i className="absolute left-1 top-1 flex h-3.5 min-w-3.5 items-center justify-center rounded-[5px] bg-black/55 px-0.5 font-mono text-[8px] font-bold not-italic text-white">
          {index}
        </i>
      )}
    </span>
  );
}

/** 版本 → 图片缩略 URL（生成产物或上传素材；非图片返回 null）。 */
function referenceThumbUrl(
  project: ProjectDocument,
  versionId: string,
): string | null {
  const artifact = project.assets.artifact_versions_by_id[versionId];
  if (artifact) {
    const mediaType =
      (artifact.file_id &&
        project.assets.files_by_id[artifact.file_id]?.media_type) ||
      "";
    return mediaType.startsWith("image/")
      ? getArtifactVersionMediaUrl(versionId)
      : null;
  }
  const source = project.assets.source_versions_by_id[versionId];
  return source?.media_kind === "image"
    ? getAssetVersionMediaUrl(versionId)
    : null;
}

/** 视觉实体 → 选中 Variant 产物缩略（与工作台取图逻辑一致的轻量版）。 */
function entityThumb(
  project: ProjectDocument,
  entityRef: string,
  variantRefs: Record<string, string>,
): { name: string; url: string | null } {
  const entityId = entityRef.replace(/^visual-entity:/, "");
  const entity = project.visual.entities.items[entityId];
  if (!entity) return { name: entityRef, url: null };
  const variantId =
    variantRefs[entityRef] ??
    variantRefs[entityId] ??
    (entity.variants.order.length === 1 ? entity.variants.order[0] : null);
  const versionId = variantId
    ? entity.variants.items[variantId]?.selected_artifact_version_id ?? null
    : entity.variants.order.length === 0
    ? entity.selected_artifact_version_id
    : null;
  return {
    name: entity.name || entityId,
    url: versionId ? getArtifactVersionMediaUrl(versionId) : null,
  };
}

export default function ElementDetail({
  project,
  timeline,
  element,
  tasks,
  applying,
  dirtyCount,
  conflictPaths,
  frameless = false,
  onClose,
  onChange,
  onApply,
  onDiscard,
  onAcceptConflicts,
  onOpenWorkbench,
}: ElementDetailProps) {
  const { t } = useTranslation();
  const [narrationBusy, setNarrationBusy] = useState(false);
  const refreshNarrationTasks = useCreatorTaskViewStore(
    (state) => state.refresh,
  );
  const pollProjectOnce = useProjectSnapshotStore((state) => state.pollOnce);
  const regenerateNarrationNow = async () => {
    if (!element) return;
    setNarrationBusy(true);
    try {
      const result = await regenerateNarration(
        project.project_id,
        timeline.timeline_id,
        element.element_id,
      );
      message.success(
        result.rebound
          ? t("elementDetail.narrationRegenerated")
          : t("elementDetail.narrationUpToDate"),
      );
      void pollProjectOnce(project.project_id);
      void refreshNarrationTasks(project.project_id);
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setNarrationBusy(false);
    }
  };
  const outputs = useMemo(
    () => (element ? resolveElementOutputs(project, element) : []),
    [element, project],
  );
  const storyboardVersionId = useMemo(
    () =>
      element && element.creation.type === "r2v"
        ? storyboardOfOwner(project, `element:${element.element_id}`)
        : null,
    [element, project],
  );
  // r2v 总览引用缩略的权威 [Image N] 序号；失败/非 r2v 时回退客户端聚合。
  const [referenceOrder, setReferenceOrder] =
    useState<R2VReferenceOrderResponse | null>(null);
  const overviewElementId = element?.element_id ?? null;
  const overviewIsR2v = element?.creation.type === "r2v";
  useEffect(() => {
    if (!overviewElementId || !overviewIsR2v) {
      setReferenceOrder(null);
      return;
    }
    let cancelled = false;
    setReferenceOrder(null);
    getR2VReferenceOrder(project.project_id, overviewElementId)
      .then((order) => {
        if (!cancelled)
          setReferenceOrder(Array.isArray(order?.references) ? order : null);
      })
      .catch(() => {
        if (!cancelled) setReferenceOrder(null);
      });
    return () => {
      cancelled = true;
    };
  }, [project.project_id, overviewElementId, overviewIsR2v]);

  if (!element) {
    return (
      <section
        data-onboarding-id="element-detail"
        className="flex min-h-0 items-center justify-center overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-primary)] shadow-sm"
      >
        <div className="max-w-sm px-8 text-center">
          <Layers3 className="mx-auto mb-3 h-8 w-8 text-[var(--color-text-tertiary)]" />
          <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">
            {t("elementDetail.selectElement")}
          </h3>
          <p className="mt-2 text-xs leading-5 text-[var(--color-text-secondary)]">
            {t("elementDetail.selectElementDesc")}
          </p>
        </div>
      </section>
    );
  }

  const meta = resolveElementVisualMeta(element);
  const status = taskStatus(element, tasks, t);
  const baseSegments = [
    "timelines",
    "items",
    timeline.timeline_id,
    "elements_by_id",
    element.element_id,
  ] as const;
  const pointer = (...segments: Array<string | number>) =>
    projectJsonPointer(...baseSegments, ...segments);
  const creation = element.creation;
  const isVideoMode =
    creation.type === "r2v" ||
    creation.type === "t2v" ||
    creation.type === "i2v" ||
    creation.type === "s2v";
  const spanStart = sec(element.span.start_tick, timeline.ticks_per_second);
  const spanEnd = sec(
    element.span.start_tick + element.span.duration_tick,
    timeline.ticks_per_second,
  );
  // ── 总览关键信息（按类型组装；只呈现有信息量的内容） ──
  const lead: { intent?: string; continuity?: string } | null = (() => {
    if (
      creation.type === "r2v" ||
      creation.type === "t2v" ||
      creation.type === "i2v"
    )
      return { intent: creation.intent, continuity: creation.continuity };
    if (creation.type === "s2v") return { intent: creation.intent };
    if (creation.type === "edit")
      return { intent: creation.intent, continuity: creation.reason };
    if (creation.type === "motion_clip") return { intent: creation.intent };
    if (creation.type === "overlay")
      return creation.vibe ? { intent: creation.vibe } : null;
    return null;
  })();
  const r2vShots =
    creation.type === "r2v"
      ? creation.shots.order
          .map((shotId) => creation.shots.items[shotId])
          .filter((shot): shot is NonNullable<typeof shot> => Boolean(shot))
      : [];
  const r2vShotsTotal = r2vShots.reduce(
    (total, shot) => total + (shot.duration_seconds ?? 0),
    0,
  );
  const r2vRefThumbs = (() => {
    if (creation.type !== "r2v") return [];
    if (referenceOrder?.references.length) {
      return referenceOrder.references.map((item) => ({
        key: `${item.kind}:${item.versionId}`,
        index: item.index,
        name: item.name,
        url: referenceThumbUrl(project, item.versionId),
      }));
    }
    const entities = [
      ...(creation.scene_ref ? [creation.scene_ref] : []),
      ...creation.character_refs,
      ...creation.prop_refs,
    ].map((ref) => {
      const info = entityThumb(project, ref, creation.visual_variant_refs);
      return {
        key: ref,
        index: undefined as number | undefined,
        name: info.name,
        url: info.url,
      };
    });
    const materials = [
      ...new Set([
        ...creation.storyboard_reference_version_ids,
        ...creation.video_reference_version_ids,
      ]),
    ].map((versionId) => ({
      key: versionId,
      index: undefined as number | undefined,
      name:
        project.assets.artifact_versions_by_id[versionId]?.name ??
        project.assets.source_versions_by_id[versionId]?.name ??
        versionId,
      url: referenceThumbUrl(project, versionId),
    }));
    return [...entities, ...materials];
  })();
  const i2vFrameUrl =
    creation.type === "i2v" && creation.first_frame_version_id
      ? referenceThumbUrl(project, creation.first_frame_version_id)
      : null;
  const s2vPortraitUrl =
    creation.type === "s2v" && creation.portrait_version_id
      ? referenceThumbUrl(project, creation.portrait_version_id)
      : null;

  return (
    <section
      data-element-detail={element.element_id}
      data-onboarding-id="element-detail"
      className={`flex min-h-0 flex-col overflow-hidden bg-[var(--color-bg-primary)] ${
        frameless
          ? ""
          : "rounded-xl border border-[var(--color-border)] shadow-sm"
      }`}
    >
      <style>{`@keyframes elementOverviewRunbar { from { transform: translateX(-120%); } to { transform: translateX(400%); } }`}</style>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3 [scrollbar-gutter:stable]">
        {/* 信息卡 (design 83:13383): title + status, tags, description. */}
        <div
          data-element-overview-card
          className="space-y-1.5 rounded-lg bg-[var(--color-bg-secondary)] p-3"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex min-w-0 items-baseline gap-2">
              <h3 className="truncate text-sm font-medium text-[var(--color-text-primary)]">
                {element.label || element.element_id}
              </h3>
              <span
                data-element-detail-status
                className={`inline-flex shrink-0 items-center gap-1.5 text-[11px] font-medium ${status.tone
                  .split(" ")
                  .filter((token) => token.startsWith("text-"))
                  .join(" ")}`}
              >
                <i
                  className={`h-1.5 w-1.5 rounded-full bg-current not-italic ${
                    status.running ? "animate-pulse" : ""
                  }`}
                />
                {status.label}
              </span>
            </div>
            <div
              data-element-detail-header-actions
              className="flex shrink-0 flex-wrap items-center justify-end gap-1.5"
            >
              {dirtyCount > 0 && (
                <>
                  <Button
                    size="small"
                    disabled={applying}
                    onClick={onDiscard}
                    className="!h-[22px] !px-2 !font-[inherit] !text-[11px] !font-semibold !leading-[20px]"
                  >
                    {t("elementDetail.discardChanges")}
                  </Button>
                  <Button
                    size="small"
                    type="primary"
                    loading={applying}
                    disabled={conflictPaths.length > 0}
                    onClick={onApply}
                    className="!h-[22px] !px-2 !font-[inherit] !text-[11px] !font-semibold !leading-[20px]"
                  >
                    {t("elementDetail.applyChangesCount", {
                      count: dirtyCount,
                    })}
                  </Button>
                </>
              )}
              {!element.enabled && (
                <span className="rounded-full bg-[var(--color-bg-secondary)] px-2 py-0.5 text-[10px] text-[var(--color-text-tertiary)]">
                  {t("elementDetail.disabled")}
                </span>
              )}
              <button
                type="button"
                onClick={onClose}
                className="icon-button !h-6 !w-6"
                aria-label={t("elementDetail.closeDetail")}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Pill tone={meta.color}>{meta.label}</Pill>
            {isVideoMode && <Pill>{t(`r2v.modeLabel.${creation.type}`)}</Pill>}
            <Pill>
              {spanStart}s – {spanEnd}s
            </Pill>
            <Pill>
              {element.location
                ? `z ${element.z_index}`
                : t("elementDetail.fullFrameZ", { z: element.z_index })}
            </Pill>
            {creation.type === "r2v" && r2vShots.length > 0 && (
              <Pill>
                {r2vShots.length} Shot · {r2vShotsTotal}s
              </Pill>
            )}
            {creation.type === "r2v" && r2vRefThumbs.length > 0 && (
              <Pill>
                {t("elementDetail.refsPill", { count: r2vRefThumbs.length })}
              </Pill>
            )}
          </div>
          {(lead?.intent || lead?.continuity) && (
            <div data-element-overview-lead className="space-y-0.5 pt-0.5">
              {lead?.intent && (
                <p className="text-xs leading-[1.7] text-[var(--color-text-primary)]">
                  {lead.intent}
                </p>
              )}
              {lead?.continuity && (
                <p
                  title={lead.continuity}
                  className="truncate text-xs leading-[1.7] text-[var(--color-text-tertiary)]"
                >
                  ↳ {lead.continuity}
                </p>
              )}
            </div>
          )}
          {/* 生成中：类型色流光进度带（产物在时间轴实时预览） */}
          {status.running && (
            <div className="relative h-[2px] overflow-hidden rounded-full bg-[var(--color-border)]">
              <i
                className="absolute bottom-0 top-0 w-[36%] rounded-full not-italic"
                style={{
                  background: `linear-gradient(90deg, transparent, ${meta.color}, transparent)`,
                  animation: "elementOverviewRunbar 1.8s linear infinite",
                }}
              />
            </div>
          )}
        </div>

        {conflictPaths.length > 0 && (
          <Alert
            type="warning"
            showIcon
            message={t("elementDetail.conflictTitle")}
            description={
              <div className="space-y-2">
                <p>{t("elementDetail.conflictDesc")}</p>
                <Button size="small" onClick={onAcceptConflicts}>
                  {t("elementDetail.useMyChanges")}
                </Button>
              </div>
            }
          />
        )}

        {/* 分镜图 (design 83:13383): thumb + status; edits live in the
            制作台 / the rail's 分镜图预览 tab. */}
        {creation.type === "r2v" && (
          <div
            data-element-overview-storyboard
            data-creator-path={pointer("creation", "storyboard_prompt")}
            className="space-y-1.5"
          >
            <div className="flex items-baseline gap-1.5">
              <span className="text-sm text-[var(--color-text-primary)]">
                {t("elementDetail.storyboardLabel")}
              </span>
            </div>
            <div className="flex items-center gap-2.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/50 p-1.5">
              <span className="h-[42px] w-[71px] shrink-0 overflow-hidden rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)]">
                {storyboardVersionId && (
                  <img
                    src={getArtifactVersionMediaUrl(storyboardVersionId)}
                    alt=""
                    loading="lazy"
                    className="h-full w-full object-cover"
                  />
                )}
              </span>
              <span className="min-w-0 leading-tight">
                <span className="block truncate text-xs text-[var(--color-text-primary)]">
                  {storyboardVersionId
                    ? t("elementDetail.storyboardReady")
                    : t("elementDetail.storyboardPending")}
                </span>
                <span className="block truncate text-xs text-[var(--color-text-tertiary)]">
                  {t("elementDetail.storyboardHint")}
                </span>
              </span>
            </div>
          </div>
        )}

        {creation.type === "r2v" && r2vShots.length > 0 && (
          <div
            data-element-overview-shots
            data-creator-path={pointer("creation", "shots")}
            className="space-y-1.5"
          >
            <div className="flex items-baseline gap-1.5">
              <span className="text-sm text-[var(--color-text-primary)]">
                {t("elementDetail.shotsLabel")}
              </span>
              <span className="text-xs text-[var(--color-text-tertiary)]">
                {t("elementDetail.shotsCount", {
                  count: r2vShots.length,
                  seconds: r2vShotsTotal,
                })}
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {r2vShots.map((shot, index) => (
                <span
                  key={shot.shot_id}
                  title={shot.description}
                  className="flex w-[84px] flex-col gap-0.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/50 px-2.5 py-2"
                >
                  <b className="truncate text-xs font-normal text-[var(--color-text-primary)]">
                    {index + 1}.{shot.framing || t("r2v.shotFraming")}
                  </b>
                  <span className="truncate text-xs text-[var(--color-text-tertiary)]">
                    {shot.camera || t("r2v.shotCamera")}{" "}
                    {shot.duration_seconds ?? "-"}s
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}
        {creation.type === "r2v" && creation.video_prompt && (
          <div
            data-element-overview-prompt
            data-creator-path={pointer("creation", "video_prompt")}
            className="space-y-1.5"
          >
            <span className="block text-sm text-[var(--color-text-primary)]">
              {t("r2v.videoPrompt")}
            </span>
            <div className="max-h-[135px] overflow-y-auto rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/50 p-3 text-xs leading-[1.6] text-[var(--color-text-primary)]">
              {creation.video_prompt}
            </div>
          </div>
        )}
        {creation.type === "r2v" && r2vRefThumbs.length > 0 && (
          <div
            data-element-overview-refs
            data-creator-path={pointer(
              "creation",
              "video_reference_version_ids",
            )}
            className="space-y-1.5"
          >
            <div className="flex items-baseline gap-1.5">
              <span className="text-sm text-[var(--color-text-primary)]">
                {t("elementDetail.refsLabel")}
              </span>
              <span className="text-xs text-[var(--color-text-tertiary)]">
                {t("elementDetail.refsCount", { count: r2vRefThumbs.length })}
                {referenceOrder?.references.length
                  ? ` · ${t("r2v.refOrderNote")}`
                  : ""}
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {r2vRefThumbs.map((item) => (
                <RefThumb
                  key={item.key}
                  url={item.url}
                  name={item.name}
                  index={item.index}
                />
              ))}
            </div>
          </div>
        )}
        {(creation.type === "t2v" || creation.type === "i2v") &&
          creation.video_prompt && (
            <div
              data-element-overview-prompt
              data-creator-path={pointer("creation", "video_prompt")}
              className="space-y-1.5"
            >
              <span className="block text-sm text-[var(--color-text-primary)]">
                {t("r2v.videoPrompt")}
              </span>
              <div className="max-h-[135px] overflow-y-auto rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/50 p-3 text-xs leading-[1.6] text-[var(--color-text-primary)]">
                {creation.video_prompt}
              </div>
            </div>
          )}
        {creation.type === "i2v" && (
          <div
            data-creator-path={pointer("creation", "first_frame_version_id")}
            className="space-y-1.5"
          >
            <span className="block text-sm text-[var(--color-text-primary)]">
              {t("elementDetail.firstFrame")}
            </span>
            {i2vFrameUrl ? (
              <img
                src={i2vFrameUrl}
                alt={t("elementDetail.firstFrame")}
                className="h-[88px] w-auto max-w-full rounded-[10px] border border-[var(--color-border)] object-cover"
              />
            ) : (
              <p className="rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/50 p-3 text-xs text-[var(--color-text-tertiary)]">
                {t("elementDetail.firstFrameEmpty")}
              </p>
            )}
          </div>
        )}
        {creation.type === "s2v" && (
          <div className="space-y-4">
            {creation.script && (
              <div
                data-creator-path={pointer("creation", "script")}
                className="space-y-1.5"
              >
                <span className="block text-sm text-[var(--color-text-primary)]">
                  {t("r2v.s2vScript")}
                </span>
                <div className="max-h-[135px] overflow-y-auto rounded-[10px] border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/50 p-3 text-xs leading-[1.6] text-[var(--color-text-primary)]">
                  {creation.script}
                </div>
              </div>
            )}
            {s2vPortraitUrl && (
              <div
                data-creator-path={pointer("creation", "portrait_version_id")}
                className="space-y-1.5"
              >
                <span className="block text-sm text-[var(--color-text-primary)]">
                  {t("elementDetail.portrait")}
                </span>
                <img
                  src={s2vPortraitUrl}
                  alt={t("elementDetail.portrait")}
                  className="h-[84px] w-auto max-w-full rounded-[10px] border border-[var(--color-border)] object-cover"
                />
              </div>
            )}
          </div>
        )}

        {/* 编辑表单不属于设计稿的概览层，折叠在「更多设置」中。 */}
        <details data-element-detail-advanced className="group">
          <summary className="flex cursor-pointer list-none items-center gap-1 text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] [&::-webkit-details-marker]:hidden">
            <span className="transition-transform group-open:rotate-90">›</span>
            {t("elementDetail.advancedSettings")}
          </summary>
          <div className="space-y-4 pt-3">
            <section className="rounded-xl border border-[var(--color-border)] p-3">
              <div className="mb-3">
                <h4 className="flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-primary)]">
                  <Clock3 className="h-3.5 w-3.5 text-[var(--color-accent)]" />
                  {t("elementDetail.timeAndLayer")}
                </h4>
              </div>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
                <label>
                  <FieldLabel>{t("elementDetail.startTime")}</FieldLabel>
                  <InputNumber
                    className="w-full"
                    min={0}
                    step={0.1}
                    disabled={applying}
                    value={sec(
                      element.span.start_tick,
                      timeline.ticks_per_second,
                    )}
                    onChange={(value) => {
                      if (value == null) return;
                      onChange((draft) => {
                        draft.span.start_tick = Math.round(
                          Number(value) * timeline.ticks_per_second,
                        );
                      });
                    }}
                  />
                </label>
                <label>
                  <FieldLabel>{t("elementDetail.durationLabel")}</FieldLabel>
                  <InputNumber
                    className="w-full"
                    min={1 / timeline.ticks_per_second}
                    step={0.1}
                    disabled={applying}
                    value={sec(
                      element.span.duration_tick,
                      timeline.ticks_per_second,
                    )}
                    onChange={(value) => {
                      if (value == null) return;
                      onChange((draft) => {
                        draft.span.duration_tick = Math.max(
                          1,
                          Math.round(Number(value) * timeline.ticks_per_second),
                        );
                      });
                    }}
                  />
                </label>
                <label>
                  <FieldLabel>{t("elementDetail.zIndex")}</FieldLabel>
                  <InputNumber
                    className="w-full"
                    disabled={applying}
                    value={element.z_index}
                    onChange={(value) =>
                      value != null &&
                      onChange((draft) => {
                        draft.z_index = Number(value);
                      })
                    }
                  />
                </label>
              </div>
              <div className="mt-3">
                <TextField
                  label={t("elementDetail.nameLabel")}
                  value={element.label}
                  path={pointer("label")}
                  field={`element:${element.element_id}/label`}
                  disabled={applying}
                  onChange={(value) =>
                    onChange((draft) => {
                      draft.label = value;
                    })
                  }
                />
              </div>
            </section>

            {element.location && (
              <section className="rounded-xl border border-[var(--color-border)] p-3">
                <h4 className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-primary)]">
                  <Box className="h-3.5 w-3.5 text-[var(--color-accent)]" />
                  {t("elementDetail.positionInFrame")}
                </h4>
                <div className="space-y-3">
                  <div className="flex min-h-40 items-center justify-center rounded-lg bg-[#191613] p-3">
                    <div
                      className="relative max-h-36 w-full max-w-[240px] overflow-hidden rounded border border-white/15 bg-[#312b26]"
                      style={{
                        aspectRatio: project.settings.aspect_ratio.replace(
                          ":",
                          " / ",
                        ),
                      }}
                    >
                      <div
                        data-element-location-box
                        className="absolute flex items-center justify-center overflow-hidden rounded border border-white/80 bg-[var(--color-accent)]/35 text-[9px] font-semibold text-white"
                        style={{
                          left: `${
                            (element.location.x -
                              element.location.width *
                                element.location.anchor_x) *
                            100
                          }%`,
                          top: `${
                            (element.location.y -
                              element.location.height *
                                element.location.anchor_y) *
                            100
                          }%`,
                          width: `${element.location.width * 100}%`,
                          height: `${element.location.height * 100}%`,
                          opacity: element.location.opacity,
                          transform: `rotate(${element.location.rotation_degrees}deg)`,
                          transformOrigin: `${
                            element.location.anchor_x * 100
                          }% ${element.location.anchor_y * 100}%`,
                        }}
                      >
                        {element.label || element.element_id}
                      </div>
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-x-3 gap-y-2">
                    {(
                      [
                        "x",
                        "y",
                        "width",
                        "height",
                        "rotation_degrees",
                        "opacity",
                      ] as const
                    ).map((key) => (
                      <label key={key}>
                        <FieldLabel>{getLocationFields(t)[key]}</FieldLabel>
                        <InputNumber
                          className="w-full"
                          step={1}
                          disabled={applying}
                          min={
                            key === "width" || key === "height"
                              ? 0.1
                              : key === "opacity"
                              ? 0
                              : undefined
                          }
                          max={key === "opacity" ? 100 : undefined}
                          value={
                            key === "rotation_degrees"
                              ? element.location![key]
                              : Number(
                                  (element.location![key] * 100).toFixed(1),
                                )
                          }
                          onChange={(value) => {
                            if (value == null) return;
                            const next =
                              key === "rotation_degrees"
                                ? Number(value)
                                : Number(value) / 100;
                            onChange((draft) => {
                              if (draft.location) draft.location[key] = next;
                            });
                          }}
                        />
                      </label>
                    ))}
                  </div>
                </div>
              </section>
            )}

            <section className="rounded-xl border border-[var(--color-border)] p-3">
              <h4 className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-primary)]">
                <Sparkles className="h-3.5 w-3.5 text-[var(--color-accent)]" />
                {t("elementDetail.creationContent")}
              </h4>
              {creation.type === "r2v" && (
                <div className="space-y-3">
                  <TextField
                    label={t("elementDetail.intent")}
                    value={creation.intent}
                    multiline
                    path={pointer("creation", "intent")}
                    field={`element:${element.element_id}/creation/intent`}
                    disabled={applying}
                    onChange={(value) =>
                      onChange((draft) => {
                        if (draft.creation.type === "r2v")
                          draft.creation.intent = value;
                      })
                    }
                  />
                  <TextField
                    label={t("elementDetail.narrative")}
                    value={creation.narrative}
                    multiline
                    path={pointer("creation", "narrative")}
                    field={`element:${element.element_id}/creation/narrative`}
                    disabled={applying}
                    onChange={(value) =>
                      onChange((draft) => {
                        if (draft.creation.type === "r2v")
                          draft.creation.narrative = value;
                      })
                    }
                  />
                  <p className="text-[10px] leading-4 text-[var(--color-text-tertiary)]">
                    {t("elementDetail.workbenchFullEditHint", {
                      action: t("elementDetail.enterWorkbench", {
                        mode: t("r2v.modeLabel.r2v"),
                      }),
                    })}
                  </p>
                </div>
              )}
              {creation.type === "edit" && (
                <div className="space-y-3">
                  <TextField
                    label={t("elementDetail.editIntent")}
                    value={creation.intent}
                    multiline
                    path={pointer("creation", "intent")}
                    field={`element:${element.element_id}/creation/intent`}
                    disabled={applying}
                    onChange={(value) =>
                      onChange((draft) => {
                        if (draft.creation.type === "edit")
                          draft.creation.intent = value;
                      })
                    }
                  />
                  <TextField
                    label={t("elementDetail.reason")}
                    value={creation.reason}
                    multiline
                    path={pointer("creation", "reason")}
                    field={`element:${element.element_id}/creation/reason`}
                    disabled={applying}
                    onChange={(value) =>
                      onChange((draft) => {
                        if (draft.creation.type === "edit")
                          draft.creation.reason = value;
                      })
                    }
                  />
                  {element.render_source?.type === "source_asset_version" && (
                    <div className="rounded-lg bg-[var(--color-bg-secondary)] p-3 text-[11px] leading-5 text-[var(--color-text-secondary)]">
                      <b
                        className="block truncate text-[var(--color-text-primary)]"
                        title={decodeURIComponent(
                          project.assets.source_versions_by_id[
                            element.render_source.version_id
                          ]?.name || t("elementDetail.currentSource"),
                        )}
                      >
                        {decodeURIComponent(
                          project.assets.source_versions_by_id[
                            element.render_source.version_id
                          ]?.name || t("elementDetail.currentSource"),
                        )}
                      </b>
                      <br />
                      {t("elementDetail.using")}{" "}
                      {sec(
                        element.render_source.source_in_tick,
                        timeline.ticks_per_second,
                      )}
                      s –{" "}
                      {element.render_source.source_out_tick == null
                        ? t("elementDetail.end")
                        : `${sec(
                            element.render_source.source_out_tick,
                            timeline.ticks_per_second,
                          )}s`}
                      {" · "}
                      {element.render_source.playback_rate}{" "}
                      {t("elementDetail.speed")}
                    </div>
                  )}
                </div>
              )}
              {creation.type === "overlay" && (
                <div className="space-y-3">
                  <TextField
                    label={t("elementDetail.textLabel")}
                    value={creation.text}
                    multiline
                    path={pointer("creation", "text")}
                    field={`element:${element.element_id}/creation/text`}
                    disabled={applying}
                    onChange={(value) =>
                      onChange((draft) => {
                        if (draft.creation.type === "overlay")
                          draft.creation.text = value;
                      })
                    }
                  />
                  <TextField
                    label={t("elementDetail.effectDesc")}
                    value={creation.prompt}
                    multiline
                    path={pointer("creation", "prompt")}
                    field={`element:${element.element_id}/creation/prompt`}
                    disabled={applying}
                    onChange={(value) =>
                      onChange((draft) => {
                        if (draft.creation.type === "overlay")
                          draft.creation.prompt = value;
                      })
                    }
                  />
                </div>
              )}
              {creation.type === "transition" && (
                <div className="space-y-3">
                  <div className="rounded-lg bg-[var(--color-bg-secondary)] p-3 text-xs text-[var(--color-text-secondary)]">
                    {timeline.elements_by_id[creation.from_element_id]?.label ||
                      t("elementDetail.previousFrame")}{" "}
                    →{" "}
                    {timeline.elements_by_id[creation.to_element_id]?.label ||
                      t("elementDetail.nextFrame")}
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <label
                      data-creator-field={`element:${element.element_id}/creation/transition_kind`}
                      data-creator-path={pointer("creation", "transition_kind")}
                      className="block"
                    >
                      <FieldLabel>
                        {t("elementDetail.transitionType")}
                      </FieldLabel>
                      <Select
                        className="w-full"
                        disabled={applying}
                        value={creation.transition_kind}
                        options={(() => {
                          const opts = getTransitionKindOptions();
                          return opts.some(
                            (option) =>
                              option.value === creation.transition_kind,
                          )
                            ? opts
                            : [
                                {
                                  value: creation.transition_kind,
                                  label: creation.transition_kind,
                                },
                                ...opts,
                              ];
                        })()}
                        onChange={(value) =>
                          onChange((draft) => {
                            if (draft.creation.type === "transition")
                              draft.creation.transition_kind = value;
                          })
                        }
                      />
                    </label>
                    <label
                      data-creator-field={`element:${element.element_id}/creation/easing`}
                      data-creator-path={pointer("creation", "easing")}
                      className="block"
                    >
                      <FieldLabel>{t("elementDetail.easing")}</FieldLabel>
                      <Select
                        className="w-full"
                        disabled={applying}
                        value={creation.easing}
                        options={
                          getTransitionEasingOptions(t).some(
                            (option) => option.value === creation.easing,
                          )
                            ? getTransitionEasingOptions(t)
                            : [
                                {
                                  value: creation.easing,
                                  label: creation.easing,
                                },
                                ...getTransitionEasingOptions(t),
                              ]
                        }
                        onChange={(value) =>
                          onChange((draft) => {
                            if (draft.creation.type === "transition")
                              draft.creation.easing = value;
                          })
                        }
                      />
                    </label>
                  </div>
                  <p className="text-[10px] leading-4 text-[var(--color-text-tertiary)]">
                    {t("elementDetail.transitionNote")}
                  </p>
                </div>
              )}
              {creation.type === "audio" &&
                (() => {
                  const audioVersion =
                    project.assets.source_versions_by_id[
                      creation.source_asset_version_id
                    ];
                  const audioMeta = (audioVersion?.metadata ?? {}) as Record<
                    string,
                    unknown
                  >;
                  const textPreview = String(audioMeta.textPreview ?? "");
                  const voiceName = String(audioMeta.voice ?? "");
                  const ttsModel = String(audioMeta.model ?? "");
                  const characterEntityId = String(
                    audioMeta.characterEntityId ?? "",
                  );
                  const characterVoiceEntity = characterEntityId
                    ? project.visual.entities.items[characterEntityId] ?? null
                    : null;
                  const voiceSampleUrl = characterVoiceEntity?.voice
                    ?.sample_source_version_id
                    ? getAssetVersionMediaUrl(
                        characterVoiceEntity.voice.sample_source_version_id,
                      )
                    : null;
                  // Streaming WAV headers can claim absurd durations (hours); hide
                  // anything implausible instead of showing a broken number.
                  const plausibleDuration =
                    audioVersion?.duration_seconds != null &&
                    audioVersion.duration_seconds > 0 &&
                    audioVersion.duration_seconds < 4 * 3600
                      ? audioVersion.duration_seconds
                      : null;
                  const spanSec = sec(
                    element.span.duration_tick,
                    timeline.ticks_per_second,
                  );
                  // Synthesized narration has no explicit duration knob on the
                  // provider: length follows the script, so the editable script
                  // shows its time budget and overruns are flagged here.
                  const overBudget =
                    plausibleDuration != null &&
                    plausibleDuration > spanSec + 0.05;
                  const scriptText = creation.script || textPreview;
                  // Only the CosyVoice family exposes a numeric speed knob;
                  // qwen-tts length is controlled through the script alone.
                  const supportsSpeechRate =
                    ttsModel.startsWith("cosyvoice") ||
                    ttsModel.includes("qwen-audio");
                  return (
                    <div className="space-y-3">
                      <div className="rounded-lg bg-[var(--color-bg-secondary)] p-3 text-xs text-[var(--color-text-secondary)]">
                        <div className="flex items-center justify-between gap-2">
                          <b className="text-[var(--color-text-primary)]">
                            {audioVersion?.name ||
                              t("elementDetail.audioFallbackName")}
                          </b>
                          <span
                            className={`text-[10px] ${
                              overBudget
                                ? "font-semibold text-[var(--color-warning)]"
                                : "text-[var(--color-text-tertiary)]"
                            }`}
                          >
                            {plausibleDuration != null
                              ? t("elementDetail.audioBudget", {
                                  actual: plausibleDuration.toFixed(1),
                                  budget: spanSec,
                                })
                              : t("elementDetail.durationByPreview")}
                          </span>
                        </div>
                        {overBudget && (
                          <p className="mt-1 text-[10px] text-[var(--color-warning)]">
                            {t("elementDetail.audioOverBudget")}
                          </p>
                        )}
                        {scriptText && (
                          <div
                            data-creator-field={`element:${element.element_id}/creation/script`}
                            data-creator-path={pointer("creation", "script")}
                            className="mt-1.5 space-y-1"
                          >
                            <Input.TextArea
                              value={scriptText}
                              autoSize={{ minRows: 2, maxRows: 6 }}
                              disabled={applying}
                              onChange={(event) =>
                                onChange((draft) => {
                                  if (draft.creation.type === "audio")
                                    draft.creation.script = event.target.value;
                                })
                              }
                              className="!text-xs"
                            />
                            <InlineReviewDiff
                              pointer={pointer("creation", "script")}
                            />
                            {supportsSpeechRate && (
                              <label
                                data-creator-field={`element:${element.element_id}/creation/speech_rate`}
                                data-creator-path={pointer(
                                  "creation",
                                  "speech_rate",
                                )}
                                className="flex items-center gap-2"
                              >
                                <span className="text-[10px] text-[var(--color-text-tertiary)]">
                                  {t("elementDetail.speechRate")}
                                </span>
                                <InputNumber
                                  size="small"
                                  value={creation.speech_rate ?? 1.0}
                                  min={0.5}
                                  max={2}
                                  step={0.1}
                                  disabled={applying}
                                  className="!w-20"
                                  onChange={(value) =>
                                    onChange((draft) => {
                                      if (draft.creation.type === "audio")
                                        draft.creation.speech_rate =
                                          typeof value === "number"
                                            ? value
                                            : 1.0;
                                    })
                                  }
                                />
                                <InlineReviewDiff
                                  pointer={pointer("creation", "speech_rate")}
                                />
                              </label>
                            )}
                            <p className="text-[10px] text-[var(--color-text-tertiary)]">
                              {t("elementDetail.ttsScriptHint")}
                            </p>
                          </div>
                        )}
                        {(voiceName || ttsModel || characterVoiceEntity) && (
                          <div
                            data-element-narration-voice
                            className="mt-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-primary)] p-2"
                          >
                            <p className="text-[10px] font-semibold text-[var(--color-text-secondary)]">
                              {t("elementDetail.referencedVoice")}
                            </p>
                            <p className="mt-0.5 text-[10px] text-[var(--color-text-tertiary)]">
                              {voiceName &&
                                t("elementDetail.voiceLine", {
                                  name: voiceName,
                                })}
                              {voiceName && ttsModel && " · "}
                              {ttsModel &&
                                t("elementDetail.ttsModelLine", {
                                  name: ttsModel,
                                })}
                            </p>
                            {voiceSampleUrl && (
                              <audio
                                src={voiceSampleUrl}
                                controls
                                preload="none"
                                className="mt-1.5 h-7 w-full"
                              />
                            )}
                          </div>
                        )}
                        {audioVersion && (
                          <audio
                            src={getAssetVersionMediaUrl(
                              audioVersion.version_id,
                            )}
                            controls
                            preload="metadata"
                            className="mt-2 h-8 w-full"
                          />
                        )}
                        {scriptText.trim() !== "" && (
                          <div className="mt-2 flex justify-end">
                            <button
                              type="button"
                              data-narration-regenerate={element.element_id}
                              disabled={narrationBusy}
                              onClick={() => void regenerateNarrationNow()}
                              className="inline-flex h-8 items-center gap-1 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-3 text-xs font-medium text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-border-strong)] disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              {narrationBusy
                                ? t("elementDetail.narrationRegenerating")
                                : t("elementDetail.narrationRegenerate")}
                            </button>
                          </div>
                        )}
                      </div>
                      <label
                        data-creator-field={`element:${element.element_id}/creation/role`}
                        data-creator-path={pointer("creation", "role")}
                        className="block"
                      >
                        <FieldLabel>{t("elementDetail.audioRole")}</FieldLabel>
                        <Select
                          value={creation.role ?? "narration"}
                          disabled={applying}
                          className="w-full"
                          options={[
                            {
                              value: "narration",
                              label: t("elementDetail.audioRoleNarration"),
                            },
                            {
                              value: "bgm",
                              label: t("elementDetail.audioRoleBgm"),
                            },
                            {
                              value: "sfx",
                              label: t("elementDetail.audioRoleSfx"),
                            },
                          ]}
                          onChange={(value) =>
                            onChange((draft) => {
                              if (draft.creation.type === "audio")
                                draft.creation.role = value as
                                  | "bgm"
                                  | "narration"
                                  | "sfx";
                            })
                          }
                        />
                        <InlineReviewDiff
                          pointer={pointer("creation", "role")}
                        />
                      </label>
                      <div className="grid grid-cols-2 gap-3">
                        <label
                          data-creator-field={`element:${element.element_id}/creation/fade_in_seconds`}
                          data-creator-path={pointer(
                            "creation",
                            "fade_in_seconds",
                          )}
                          className="block"
                        >
                          <FieldLabel>
                            {t("elementDetail.audioFadeIn")}
                          </FieldLabel>
                          <InputNumber
                            value={creation.fade_in_seconds ?? undefined}
                            placeholder={t("elementDetail.audioFadeAdaptive")}
                            step={0.5}
                            min={0}
                            max={10}
                            disabled={applying}
                            className="w-full"
                            onChange={(value) =>
                              onChange((draft) => {
                                if (draft.creation.type === "audio")
                                  draft.creation.fade_in_seconds =
                                    value === null || value === undefined
                                      ? null
                                      : Number(value);
                              })
                            }
                          />
                          <InlineReviewDiff
                            pointer={pointer("creation", "fade_in_seconds")}
                          />
                        </label>
                        <label
                          data-creator-field={`element:${element.element_id}/creation/fade_out_seconds`}
                          data-creator-path={pointer(
                            "creation",
                            "fade_out_seconds",
                          )}
                          className="block"
                        >
                          <FieldLabel>
                            {t("elementDetail.audioFadeOut")}
                          </FieldLabel>
                          <InputNumber
                            value={creation.fade_out_seconds ?? undefined}
                            placeholder={t("elementDetail.audioFadeAdaptive")}
                            step={0.5}
                            min={0}
                            max={10}
                            disabled={applying}
                            className="w-full"
                            onChange={(value) =>
                              onChange((draft) => {
                                if (draft.creation.type === "audio")
                                  draft.creation.fade_out_seconds =
                                    value === null || value === undefined
                                      ? null
                                      : Number(value);
                              })
                            }
                          />
                          <InlineReviewDiff
                            pointer={pointer("creation", "fade_out_seconds")}
                          />
                        </label>
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <label
                          data-creator-field={`element:${element.element_id}/creation/gain_db`}
                          data-creator-path={pointer("creation", "gain_db")}
                          className="block"
                        >
                          <FieldLabel>{t("elementDetail.gainDb")}</FieldLabel>
                          <InputNumber
                            value={creation.gain_db}
                            step={1}
                            min={-30}
                            max={12}
                            disabled={applying}
                            className="w-full"
                            onChange={(value) =>
                              onChange((draft) => {
                                if (draft.creation.type === "audio")
                                  draft.creation.gain_db = Number(value ?? 0);
                              })
                            }
                          />
                          <InlineReviewDiff
                            pointer={pointer("creation", "gain_db")}
                          />
                        </label>
                        <label
                          data-creator-field={`element:${element.element_id}/creation/pan`}
                          data-creator-path={pointer("creation", "pan")}
                          className="block"
                        >
                          <FieldLabel>{t("elementDetail.panRange")}</FieldLabel>
                          <InputNumber
                            value={creation.pan}
                            step={0.1}
                            min={-1}
                            max={1}
                            disabled={applying}
                            className="w-full"
                            onChange={(value) =>
                              onChange((draft) => {
                                if (draft.creation.type === "audio")
                                  draft.creation.pan = Number(value ?? 0);
                              })
                            }
                          />
                          <InlineReviewDiff
                            pointer={pointer("creation", "pan")}
                          />
                        </label>
                      </div>
                      <p className="text-[10px] leading-4 text-[var(--color-text-tertiary)]">
                        {t("elementDetail.audioMixHint")}
                      </p>
                    </div>
                  );
                })()}
            </section>

            {(creation.type === "r2v" ||
              creation.type === "t2v" ||
              creation.type === "i2v" ||
              creation.type === "s2v") && (
              <section className="rounded-xl border border-[var(--color-border)] p-3">
                <h4 className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-[var(--color-text-primary)]">
                  <Film className="h-3.5 w-3.5 text-[var(--color-accent)]" />
                  {t("elementDetail.generationResult")}
                </h4>
                {outputs.length === 0 ? (
                  <p className="rounded-lg bg-[var(--color-bg-secondary)] p-3 text-xs text-[var(--color-text-tertiary)]">
                    {t("elementDetail.noResult")}
                  </p>
                ) : (
                  <div className="space-y-1.5">
                    {outputs.map((output) => (
                      <div
                        key={output.name}
                        className="flex items-center justify-between gap-2 rounded-lg bg-[var(--color-bg-secondary)]/60 px-3 py-2 text-[11px]"
                      >
                        <b className="text-[var(--color-text-primary)]">
                          {outputLabel(output.name)}
                        </b>
                        <span
                          className={
                            output.selected?.stale
                              ? "text-[var(--color-warning)]"
                              : output.selected
                              ? "text-[var(--color-success)]"
                              : "text-[var(--color-text-tertiary)]"
                          }
                        >
                          {output.selected?.stale
                            ? `${t("elementDetail.generated")} · ${t(
                                "elementDetail.resultStale",
                              )}`
                            : output.selected
                            ? t("elementDetail.generated")
                            : t("elementDetail.notGenerated")}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                <p className="mt-2 text-center text-[10px] text-[var(--color-text-tertiary)]">
                  {t("elementDetail.outputsPreviewHint")}
                </p>
              </section>
            )}
          </div>
        </details>
      </div>

      {(creation.type === "r2v" ||
        creation.type === "t2v" ||
        creation.type === "i2v" ||
        creation.type === "s2v") && (
        <footer className="shrink-0 border-t border-[var(--color-border)] bg-[var(--color-bg-primary)] px-4 py-3">
          <Button
            block
            size="small"
            icon={<ArrowUpRight className="h-3 w-3" />}
            disabled={dirtyCount > 0 || applying}
            onClick={() => onOpenWorkbench(element)}
          >
            {t("elementDetail.enterWorkbench")}
          </Button>
        </footer>
      )}
    </section>
  );
}
