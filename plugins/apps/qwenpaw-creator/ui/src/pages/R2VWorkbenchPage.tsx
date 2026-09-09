import { CreatorHttpError } from "@/api/creator/client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Image, Input, Modal, Select, message } from "antd";
import {
  ArrowLeft,
  Loader2,
  Image as LucideImageIcon,
  Plus,
  X,
} from "lucide-react";
import { navigate, useParams, useSearchParams } from "@/routing/navigation";
import {
  useReviewFieldFocus,
  useReviewMediaFocus,
} from "@/routing/reviewFocus";
import {
  useProjectSnapshotStore,
  type ProjectEditOperation,
} from "@/store/projectSnapshotStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useTimelineStore } from "@/store/timelineStore";
import {
  selectPrimaryTimeline,
  selectTimelineById,
} from "@/selectors/timelineElementSelectors";
import {
  getArtifactVersionMediaUrl,
  getAssetVersionMediaUrl,
  getR2VReferenceOrder,
} from "@/api/creator";
import { dispatchWorkGraphNode } from "@/api/creator/workGraph";
import {
  acceptPromptProposal,
  createPromptProposal,
  getPromptSync,
} from "@/api/creator/promptSync";
import { useWorkGraphStore } from "@/store/workGraphStore";
import { startVisiblePolling } from "@/lib/visiblePolling";
import { taskProgressPercent } from "@/lib/taskPresentation";
import { projectJsonPointer } from "@/lib/projectJsonPointer";
import { presentPromptEntityNames } from "@/lib/promptEntityNames";
import { useProjectDraft } from "@/lib/useProjectDraft";
import { visualVariantLabel } from "@/lib/visualVariants";
import PageSkeleton from "@/components/PageSkeleton";
import PageLoadError from "@/components/PageLoadError";
import InlineReviewDiff from "@/components/agent/InlineReviewDiff";
import ArtifactVersionChips from "@/components/workbench/ArtifactVersionChips";
import PromptRichBlock, {
  RegeneratePill,
  type PromptRichToken,
} from "@/components/workbench/PromptRichBlock";
import RelatedAssetPicker, {
  type PickerCandidate,
} from "@/components/workbench/RelatedAssetPicker";
import {
  EntityGroup,
  SectionLabel,
  referencedEntities,
} from "@/components/blueprint/EpisodeOverviewRail";
import { refImageThumbUrl } from "@/components/workbench/referenceThumbs";
import type {
  ArtifactSlotDocument,
  ArtifactVersionDocument,
  ProjectDocument,
  R2VReferenceOrderResponse,
  TaskView,
  TimelineElementDocument,
  VideoCreationDocument,
  VideoGenerationMode,
} from "@/contracts/creator";
import { useTranslation } from "react-i18next";
import "./R2VWorkbenchPage.css";

const { TextArea } = Input;

// Mode-specific workbench copy: the page serves every video generation
// mode, so its title, hints and reference surfaces must not read as
// reference-to-video when the element declares something else.
export const GENERATION_MODE_META: Record<
  VideoGenerationMode,
  { labelKey: string; subtitleKey: string }
> = {
  r2v: {
    labelKey: "r2v.modeLabel.r2v",
    subtitleKey: "r2v.modeSubtitle.r2v",
  },
  t2v: {
    labelKey: "r2v.modeLabel.t2v",
    subtitleKey: "r2v.modeSubtitle.t2v",
  },
  i2v: {
    labelKey: "r2v.modeLabel.i2v",
    subtitleKey: "r2v.modeSubtitle.i2v",
  },
  s2v: {
    labelKey: "r2v.modeLabel.s2v",
    subtitleKey: "r2v.modeSubtitle.s2v",
  },
};

function Panel({
  title,
  badge,
  children,
}: {
  title: string;
  badge?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]">
      <div className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-2.5">
        <h4 className="text-xs font-bold text-[var(--color-text-secondary)]">
          {title}
        </h4>
        {badge}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function PromptTextArea({
  label,
  value,
  field,
  path,
  disabled = false,
  placeholder,
  onChange,
  onRegenerate,
  regenerating = false,
  regenerateLabel,
}: {
  label: string;
  value: string;
  field: string;
  path: string;
  disabled?: boolean;
  placeholder?: string;
  onChange: (value: string) => void;
  onRegenerate?: () => void;
  regenerating?: boolean;
  regenerateLabel?: string;
}) {
  const { t } = useTranslation();
  return (
    <div
      data-creator-field={field}
      data-creator-path={path}
      data-creator-field-label={label}
    >
      <p className="mb-1 text-[11px] font-medium text-[var(--color-text-tertiary)]">
        {label}
      </p>
      <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)]">
        <TextArea
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          autoSize={{ minRows: 2, maxRows: 10 }}
          placeholder={placeholder ?? t("r2v.generateAndEdit", { label })}
          className="!rounded-none !border-0 !bg-transparent !text-xs !shadow-none"
        />
        {onRegenerate && (
          <div className="flex justify-end gap-3 px-3 pb-3 pt-1.5">
            <RegeneratePill
              field={field}
              label={regenerateLabel ?? ""}
              loading={regenerating}
              disabled={disabled}
              onClick={onRegenerate}
            />
          </div>
        )}
      </div>
      <InlineReviewDiff pointer={path} />
    </div>
  );
}

/**
 * Adaptive media frame: the frame shrink-wraps the image's own aspect ratio
 * with a capped height, so portrait/landscape media never gets letterboxed.
 * Clicking zooms in through the antd Image preview.
 */
function MediaFrame({
  src,
  alt,
  maxHeight,
  anchorVersionId,
}: {
  src: string;
  alt: string;
  maxHeight: string;
  anchorVersionId?: string;
}) {
  return (
    <div
      data-review-media-anchor={anchorVersionId}
      className="mx-auto w-fit max-w-full overflow-hidden rounded-lg border border-[var(--color-border)] bg-[#141210]"
    >
      <Image
        src={src}
        alt={alt}
        preview={{ src }}
        style={{
          display: "block",
          width: "auto",
          height: "auto",
          maxWidth: "100%",
          maxHeight,
        }}
      />
    </div>
  );
}

function versionsOfSlot(
  project: ProjectDocument,
  slot: ArtifactSlotDocument | null,
): ArtifactVersionDocument[] {
  if (!slot) return [];
  return slot.version_ids
    .map((versionId) => project.assets.artifact_versions_by_id[versionId])
    .filter((version): version is ArtifactVersionDocument => Boolean(version));
}

function mediaUrlOf(
  project: ProjectDocument,
  version: ArtifactVersionDocument | null,
  mediaPrefix: string,
): string | null {
  if (!version) return null;
  const file = project.assets.files_by_id[version.file_id];
  return file?.media_type.startsWith(mediaPrefix)
    ? getArtifactVersionMediaUrl(version.version_id)
    : null;
}

function referenceVersionName(
  project: ProjectDocument,
  versionId: string,
): string {
  return (
    project.assets.artifact_versions_by_id[versionId]?.name ??
    project.assets.source_versions_by_id[versionId]?.name ??
    versionId
  );
}

export interface WorkbenchSurfaceProps {
  projectId: string;
  elementId: string;
  /** Parameterized timeline (/t/:timelineId/...); primary timeline when absent. */
  timelineId?: string | null;
  /** Leave the workbench (route page: navigate back to Plan; modal: close). */
  onBack: () => void;
  /** Hosted inside a modal/panel: hide the back button and skip URL state. */
  embedded?: boolean;
  /** Review focus context, read from the URL by the route shell only. */
  reviewMode?: boolean;
  reviewField?: string | null;
  reviewPulse?: string | null;
  versionFromUrl?: string | null;
  /** Lets an embedding host guard its own close action on dirty drafts. */
  onDirtyChange?: (dirty: boolean) => void;
  /** Extra controls rendered at the right end of the top bar. */
  headerExtra?: React.ReactNode;
}

/**
 * The whole workbench UI without any router coupling, reusable from the
 * route page below and from embedding hosts (e.g. the Plan page modal).
 */
export function WorkbenchSurface({
  projectId,
  elementId,
  timelineId = null,
  onBack,
  embedded = false,
  reviewMode = false,
  reviewField = null,
  reviewPulse = null,
  versionFromUrl = null,
  onDirtyChange,
  headerExtra,
}: WorkbenchSurfaceProps) {
  const { t } = useTranslation();
  // Route param wins (parameterized /t/:timelineId/...); the legacy route
  // falls back to the primary timeline.
  const planBase = timelineId
    ? `/project/${projectId}/t/${encodeURIComponent(timelineId)}/plan`
    : `/project/${projectId}/plan`;
  useReviewFieldFocus({
    path: `${planBase}/element/${elementId}`,
    field: reviewField,
    enabled: reviewMode && !embedded,
    pulse: reviewPulse,
  });
  const project = useProjectSnapshotStore((state) =>
    state.projectId === projectId ? state.project : null,
  );
  const syncStatus = useProjectSnapshotStore((state) => state.syncStatus);
  const syncError = useProjectSnapshotStore((state) => state.syncError);
  const patchProject = useProjectSnapshotStore((state) => state.patch);
  const patching = useProjectSnapshotStore((state) => state.patching);
  const pollOnce = useProjectSnapshotStore((state) => state.pollOnce);
  const tasks = useCreatorTaskViewStore((state) => state.tasks);
  const refreshTasks = useCreatorTaskViewStore((state) => state.refresh);
  const [regeneratingNode, setRegeneratingNode] = useState<string | null>(null);
  const [synchronizing, setSynchronizing] = useState(false);
  const [regenerationError, setRegenerationError] = useState("");
  const [preparationSeconds, setPreparationSeconds] = useState(0);
  useEffect(() => {
    setPreparationSeconds(0);
    if (!synchronizing) return;
    const started = Date.now();
    const timer = window.setInterval(
      () => setPreparationSeconds(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [synchronizing]);
  // Drafts persist at an editing boundary, before preparing instructions.
  // applyDraft 定义在守卫分支之后，这里经 ref 引用最新实现。
  const applyDraftRef = useRef<
    ((options?: { notify?: boolean }) => Promise<boolean>) | null
  >(null);
  const activeTimelineId = useTimelineStore((s) => s.activeTimelineId);
  const timeline = useMemo(
    () =>
      timelineId
        ? selectTimelineById(project, timelineId)
        : selectPrimaryTimeline(project, activeTimelineId),
    [project, timelineId, activeTimelineId],
  );
  const promptSyncScope = `${projectId}:${
    timeline?.timeline_id ?? "missing"
  }:${elementId}`;
  const workbenchEpoch = useRef(0);
  const editRevision = useRef(0);
  const regenerationRequest = useRef<symbol | null>(null);
  const regenerationMonitor = useRef<{ stop: () => void } | null>(null);
  const candidateSelectionRevision = useRef({ storyboard: 0, video: 0 });
  const candidateFollow = useRef<
    Partial<
      Record<"storyboard" | "video", { epoch: number; known: Set<string> }>
    >
  >({});
  useEffect(() => {
    workbenchEpoch.current += 1;
    regenerationRequest.current = null;
    candidateFollow.current = {};
    setRegeneratingNode(null);
    setSynchronizing(false);
    setRegenerationError("");
    return () => {
      workbenchEpoch.current += 1;
      regenerationMonitor.current?.stop();
      regenerationMonitor.current = null;
    };
  }, [promptSyncScope]);
  const authorityElement = timeline?.elements_by_id[elementId] ?? null;
  const elementDraft = useProjectDraft<TimelineElementDocument | null>(
    authorityElement,
    `${projectId}:${timeline?.timeline_id ?? "missing"}:${elementId}:r2v`,
    [
      "timelines",
      "items",
      timeline?.timeline_id ?? "missing",
      "elements_by_id",
      elementId,
    ],
  );
  const element = elementDraft.value;
  // Every generated-video creation type owns this workbench route; the
  // narrowed creation drives which mode surface renders below.
  const creation =
    element &&
    (element.creation.type === "r2v" ||
      element.creation.type === "t2v" ||
      element.creation.type === "i2v" ||
      element.creation.type === "s2v")
      ? (element.creation as VideoCreationDocument)
      : null;
  const generationMode: VideoGenerationMode = creation?.type ?? "r2v";
  // 相关资产 rail (design 84:44397): the entity cards this element references.
  const elementEntities = useMemo(
    () => (project && element ? referencedEntities(project, [element]) : []),
    [project, element],
  );
  const openVisualEntity = useCallback((entityId: string) => {
    useCreatorInteractionStore.getState().select(`visual-entity:${entityId}`);
  }, []);
  const [viewedSbId, setViewedSbId] = useState<string | null>(null);
  const [viewedVideoId, setViewedVideoId] = useState<string | null>(null);
  const viewCandidate = (kind: "storyboard" | "video", id: string) => {
    candidateSelectionRevision.current[kind] += 1;
    delete candidateFollow.current[kind];
    (kind === "storyboard" ? setViewedSbId : setViewedVideoId)(id);
  };
  const [stage, setStage] = useState<"sb" | "vd">("sb");
  const requestedVersion = versionFromUrl
    ? project?.assets.artifact_versions_by_id[versionFromUrl]
    : null;
  const requestedMediaType = requestedVersion
    ? project?.assets.files_by_id[requestedVersion.file_id]?.media_type
    : null;
  const requestedVersionStage =
    requestedVersion?.owner_ref !== `element:${elementId}`
      ? null
      : requestedMediaType?.startsWith("video/")
      ? "vd"
      : requestedVersion.kind === "r2v_storyboard_image" ||
        requestedVersion.slot_id.endsWith(":storyboard")
      ? "sb"
      : null;
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const [assetPickerOpen, setAssetPickerOpen] = useState(false);
  // Authoritative [Image N] order from the backend: entity binding and
  // dedup reorder references, so the submit-path preview is the only
  // trustworthy numbering for the video prompt's [Image N] citations.
  const generation = useProjectSnapshotStore((state) =>
    state.projectId === projectId ? state.generation : null,
  );
  const [referenceOrder, setReferenceOrder] =
    useState<R2VReferenceOrderResponse | null>(null);
  const [storyboardReferenceOrder, setStoryboardReferenceOrder] =
    useState<R2VReferenceOrderResponse | null>(null);
  const authorityCreation = authorityElement?.creation;
  const referenceIdentity = JSON.stringify(
    authorityCreation?.type === "r2v" && project
      ? [
          projectId,
          elementId,
          authorityCreation.storyboard_reference_version_ids,
          authorityCreation.video_reference_version_ids,
          authorityCreation.character_refs,
          authorityCreation.scene_ref,
          authorityCreation.prop_refs,
          authorityCreation.visual_variant_refs,
          authorityCreation.cast_lineup_refs,
          Object.values(project.assets.artifact_slots_by_id).map((slot) => [
            slot.slot_id,
            slot.selected_version_id,
          ]),
          project.visual.entities.order.map((id) => {
            const entity = project.visual.entities.items[id];
            return [
              id,
              entity?.selected_artifact_version_id,
              entity?.variants.order.map((variant) => [
                variant,
                entity.variants.items[variant]?.selected_artifact_version_id,
              ]),
            ];
          }),
        ]
      : null,
  );
  const previousReferenceIdentity = useRef(referenceIdentity);
  useEffect(() => {
    if (!projectId || !elementId || generationMode !== "r2v") {
      setReferenceOrder(null);
      setStoryboardReferenceOrder(null);
      return;
    }
    let cancelled = false;
    // Prompt-only edits do not change reference identities. Keep their
    // verified images during refresh; actual binding changes clear them.
    if (previousReferenceIdentity.current !== referenceIdentity) {
      setReferenceOrder(null);
      setStoryboardReferenceOrder(null);
      previousReferenceIdentity.current = referenceIdentity;
    }
    Promise.allSettled([
      getR2VReferenceOrder(projectId, elementId),
      getR2VReferenceOrder(projectId, elementId, "storyboard"),
    ])
      .then(([video, storyboard]) => {
        if (cancelled) return;
        setReferenceOrder(
          video.status === "fulfilled" && Array.isArray(video.value?.references)
            ? video.value
            : null,
        );
        setStoryboardReferenceOrder(
          storyboard.status === "fulfilled" &&
            storyboard.value?.stage === "storyboard" &&
            Array.isArray(storyboard.value.references)
            ? storyboard.value
            : null,
        );
      })
      .catch(() => {
        if (!cancelled) setReferenceOrder(null);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, elementId, generationMode, generation, referenceIdentity]);

  // Reset object-local selection before applying the URL's review/version
  // intent. Otherwise this mount effect hides a video field just opened by
  // the review effect in the same commit.
  useEffect(() => {
    setViewedSbId(null);
    setViewedVideoId(null);
    setStage("sb");
  }, [projectId, elementId, timeline?.timeline_id]);

  useEffect(() => {
    if (!versionFromUrl || !requestedVersionStage) return;
    if (requestedVersionStage === "sb") {
      candidateSelectionRevision.current.storyboard += 1;
      delete candidateFollow.current.storyboard;
      setViewedSbId(versionFromUrl);
      setStage("sb");
      return;
    }
    candidateSelectionRevision.current.video += 1;
    delete candidateFollow.current.video;
    setViewedVideoId(versionFromUrl);
    setStage("vd");
    // A new review click reopens its stage. Snapshot polling must not undo a
    // subsequent manual tab switch or repeatedly scroll away from an edit.
  }, [
    versionFromUrl,
    requestedVersionStage,
    projectId,
    elementId,
    reviewPulse,
  ]);

  useEffect(() => {
    if (!project || !authorityElement) return;
    for (const kind of ["storyboard", "video"] as const) {
      const follow = candidateFollow.current[kind];
      if (!follow || follow.epoch !== workbenchEpoch.current) continue;
      const output =
        kind === "storyboard"
          ? authorityElement.outputs.storyboard
          : authorityElement.outputs.video ?? authorityElement.outputs.main;
      const slot = output
        ? project.assets.artifact_slots_by_id[output.slot_id]
        : null;
      const candidate = versionsOfSlot(project, slot ?? null)
        .filter((version) => !follow.known.has(version.version_id))
        .at(-1);
      if (!candidate) continue;
      delete candidateFollow.current[kind];
      (kind === "storyboard" ? setViewedSbId : setViewedVideoId)(
        candidate.version_id,
      );
    }
  }, [project, authorityElement]);

  // A review pointing at the video prompt lives in the hidden ② tab;
  // switch there so the focus flash lands on a visible field.
  useEffect(() => {
    if (
      reviewField?.includes("video_prompt") ||
      reviewField?.includes("/video_reference_version_ids")
    )
      setStage("vd");
    else if (
      reviewField?.includes("/storyboard_prompt") ||
      reviewField?.includes("/storyboard_reference_version_ids") ||
      reviewField?.includes("/creation/narrative")
    )
      setStage("sb");
  }, [reviewField, reviewPulse]);

  // Wait for the requested version and its stage to commit before scrolling.
  // In the stacked layout changing tabs moves the results vertically, so a
  // scroll from the initial storyboard render would land at an obsolete spot.
  useReviewMediaFocus({
    versionId: versionFromUrl,
    enabled:
      reviewMode &&
      !reviewField &&
      !embedded &&
      requestedVersionStage === stage &&
      (stage === "vd" ? viewedVideoId : viewedSbId) === versionFromUrl,
    pulse: reviewPulse,
  });

  useEffect(() => {
    useCreatorInteractionStore
      .getState()
      .select(element ? `element:${element.element_id}` : null);
  }, [element]);
  useEffect(() => {
    onDirtyChange?.(elementDraft.dirty);
  }, [elementDraft.dirty, onDirtyChange]);
  useEffect(() => {
    if (!elementDraft.dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [elementDraft.dirty]);
  // 自动保存只发生在语义边界：字段失焦（下方 onBlurCapture）、切换页签、
  // 「再次生成」、返回，以及此处的卸载兜底——绝不在打字停顿期间提交，
  // 否则半成品 prompt 会被 unattended 调度器当作最终输入。
  useEffect(
    () => () => {
      void applyDraftRef.current?.({ notify: false });
    },
    [],
  );
  const handleFieldBlurCapture = useCallback((event: React.FocusEvent) => {
    const target = event.target as HTMLElement | null;
    if (!target) return;
    const editable =
      target.tagName === "TEXTAREA" ||
      target.tagName === "INPUT" ||
      target.getAttribute("role") === "combobox";
    if (!editable) return;
    // Let the click that stole focus land its own change first.
    window.setTimeout(
      () => void applyDraftRef.current?.({ notify: false }),
      150,
    );
  }, []);

  const requestBack = useCallback(() => {
    if (!elementDraft.dirty) {
      onBack();
      return;
    }
    void (async () => {
      // Auto-save world: leaving applies the draft; only an unpersistable
      // draft (validation/patch failure) still asks the user to discard.
      if (await applyDraftRef.current?.({ notify: false })) {
        onBack();
        return;
      }
      Modal.confirm({
        title: t("r2v.unsavedChangesTitle"),
        content: t("r2v.unsavedChangesDesc"),
        okText: t("r2v.discardAndBack"),
        okButtonProps: { danger: true },
        cancelText: t("r2v.continueEditing"),
        onOk: () => {
          elementDraft.discard();
          onBack();
        },
      });
    })();
  }, [elementDraft, onBack, t]);

  if (!project || !timeline) {
    if (syncStatus === "invalid" || syncStatus === "not_found") {
      return (
        <PageLoadError
          message={syncError || t("assets.projectReadError")}
          retry={() => void pollOnce(projectId)}
        />
      );
    }
    return <PageSkeleton type="editor" />;
  }
  if (!element || !creation) {
    return (
      <div className="flex h-full items-center justify-center bg-[var(--color-bg-layout)] px-6">
        <div className="max-w-sm text-center">
          <p className="text-sm font-semibold text-[var(--color-text-primary)]">
            {element ? t("r2v.notAIGenerated") : t("r2v.elementNotFound")}
          </p>
          <button
            type="button"
            onClick={onBack}
            className="mt-4 rounded border border-[var(--color-border)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-text-primary)] hover:bg-[var(--color-bg-secondary)] dark:bg-[var(--color-bg-primary)]"
          >
            {t("r2v.backToPlan")}
          </button>
        </div>
      </div>
    );
  }

  const elementLabel = element.label || element.element_id;
  const modeMeta = GENERATION_MODE_META[generationMode];
  const elementPointer = (...segments: Array<string | number>) =>
    projectJsonPointer(
      "timelines",
      "items",
      timeline.timeline_id,
      "elements_by_id",
      element.element_id,
      ...segments,
    );
  const patchOps = (operations: ProjectEditOperation[]) =>
    patchProject(projectId, operations).catch((error) => {
      message.error((error as Error).message);
      throw error;
    });
  const updateElement = (mutator: (draft: TimelineElementDocument) => void) => {
    setRegenerationError("");
    editRevision.current += 1;
    elementDraft.update((draft) => {
      if (draft) mutator(draft);
    });
  };
  const applyDraft = async ({
    notify = true,
  }: { notify?: boolean } = {}): Promise<boolean> => {
    if (elementDraft.conflictPaths.length) {
      if (notify) message.warning(t("r2v.conflictTitle"));
      return false;
    }
    if (!elementDraft.operations.length) return true;
    try {
      await patchProject(projectId, elementDraft.operations);
      elementDraft.markApplied();
      if (notify) message.success(t("r2v.applySuccessShort"));
      return true;
    } catch (error) {
      message.error(t("r2v.applyFailed", { detail: (error as Error).message }));
      return false;
    }
  };
  applyDraftRef.current = applyDraft;
  // 离散动作（增删引用、全屏编辑「完成」）本身即语义边界：等本次 React
  // 提交后静默落盘（与字段 blur 的自动保存共用一条管线）。
  const scheduleSilentApply = () =>
    window.setTimeout(
      () => void applyDraftRef.current?.({ notify: false }),
      50,
    );

  // Apply the draft and verify its synchronization before dispatching. The
  // response distinguishes an existing running task from an up-to-date result;
  // a newly dispatched request can finish only after provider execution.
  const regenerateNode = async (kind: "storyboard" | "video") => {
    if (regenerationRequest.current) {
      message.info(t("r2v.regenRunning"));
      return;
    }
    const request = Symbol("regeneration");
    regenerationRequest.current = request;
    const nodeId = `${kind}:${element.element_id}`;
    const epoch = workbenchEpoch.current;
    const revision = editRevision.current;
    const selectionRevision = candidateSelectionRevision.current[kind];
    const isCurrent = () =>
      epoch === workbenchEpoch.current &&
      revision === editRevision.current &&
      regenerationRequest.current === request;
    const inputSignature = () => {
      const latest = useProjectSnapshotStore.getState();
      if (latest.projectId !== projectId) return null;
      const target =
        latest.project?.timelines.items[timeline.timeline_id]?.elements_by_id[
          element.element_id
        ];
      return target ? JSON.stringify([target.creation, target.span]) : null;
    };
    let finishMonitor: (() => Promise<void>) | null = null;
    setRegeneratingNode(nodeId);
    setRegenerationError("");
    try {
      if (elementDraft.dirty && !(await applyDraft())) return;
      if (!isCurrent()) return;
      let submittedInput = inputSignature();
      if (creation.type === "r2v") {
        const scope = {
          projectId,
          timelineId: timeline.timeline_id,
          elementId: element.element_id,
        };
        let sync = await getPromptSync(scope);
        if (!isCurrent() || submittedInput !== inputSignature()) return;
        if (sync.validationMessage) throw new Error(sync.validationMessage);
        if (
          sync.status === "needs_update" ||
          sync.status === "needs_confirmation"
        ) {
          setSynchronizing(true);
          const proposal = await createPromptProposal(
            scope,
            sync.suggestedSource ??
              (sync.narrative.trim() ? "currentPlan" : "videoPrompt"),
          );
          // A new edit or route change cancels this generation intent before
          // the proposal can publish. The backend also checks its saved baseline.
          if (!isCurrent() || submittedInput !== inputSignature()) return;
          await acceptPromptProposal(scope, proposal.proposalId);
          if (!isCurrent()) return;
          await pollOnce(projectId);
          if (!isCurrent()) return;
          submittedInput = inputSignature();
          sync = await getPromptSync(scope);
          if (!isCurrent() || submittedInput !== inputSignature()) return;
          // Dispatch only the exact synchronized content returned by this
          // operation; an unrelated concurrent edit must not inherit its click.
          if (
            sync.status !== "current" ||
            sync.storyboardPrompt !== proposal.storyboardPrompt ||
            sync.videoPrompt !== proposal.videoPrompt ||
            sync.narrative !== proposal.narrative
          )
            throw new Error(t("r2v.sync.changedBeforeGeneration"));
          setSynchronizing(false);
        }
      }
      // This endpoint can remain pending through the provider execution.
      // Discover real durable activity immediately; once discovered, the
      // project shell's active poll takes over, including after navigation.
      let disposed = false;
      let inFlight: Promise<void> | null = null;
      const sameScope = () => !disposed && epoch === workbenchEpoch.current;
      const readProgress = (force = false): Promise<void> => {
        if (!sameScope()) return Promise.resolve();
        if (inFlight) return inFlight;
        const taskStore = useCreatorTaskViewStore.getState();
        const graphStore = useWorkGraphStore.getState();
        inFlight = Promise.allSettled([
          force || !taskStore.loading
            ? refreshTasks(projectId)
            : Promise.resolve(),
          force || !graphStore.loading
            ? graphStore.refresh(projectId)
            : Promise.resolve(),
          pollOnce(projectId),
        ])
          .then(() => undefined)
          .finally(() => {
            inFlight = null;
          });
        return inFlight;
      };
      const stopTicks = startVisiblePolling(() => {
        if (!sameScope()) return;
        const taskStore = useCreatorTaskViewStore.getState();
        const graphStore = useWorkGraphStore.getState();
        const active =
          taskStore.projectId === projectId &&
          taskStore.tasks.some(
            (task) => task.status === "RUNNING" || task.status === "QUEUED",
          );
        if (
          active ||
          (graphStore.projectId === projectId &&
            (graphStore.graph?.counts?.running ?? 0) > 0)
        ) {
          stopTicks();
          return;
        }
        void readProgress();
      }, 3_000);
      const monitor = {
        stop: () => {
          disposed = true;
          stopTicks();
        },
      };
      regenerationMonitor.current = monitor;
      finishMonitor = async () => {
        stopTicks();
        if (inFlight) await inFlight;
        if (sameScope()) await readProgress(true);
        monitor.stop();
        if (regenerationMonitor.current === monitor)
          regenerationMonitor.current = null;
      };
      // A manual version choice during save/sync preflight also takes
      // precedence over automatic result following once dispatch begins.
      if (candidateSelectionRevision.current[kind] === selectionRevision)
        candidateFollow.current[kind] = {
          epoch,
          known: new Set(
            (kind === "storyboard" ? storyboardVersions : videoVersions).map(
              (version) => version.version_id,
            ),
          ),
        };
      const dispatched = dispatchWorkGraphNode(projectId, nodeId);
      void readProgress();
      const result = await dispatched;
      if (epoch !== workbenchEpoch.current) return;
      await finishMonitor();
      finishMonitor = null;
      if (epoch !== workbenchEpoch.current) return;
      if (result.dispatched) {
        message.success(t("r2v.regenProcessed"));
      } else if (result.status === "running") {
        message.info(t("r2v.regenRunning"));
      } else {
        delete candidateFollow.current[kind];
        message.info(t("r2v.regenUpToDate"));
      }
    } catch (error) {
      if (epoch === workbenchEpoch.current)
        delete candidateFollow.current[kind];
      if (isCurrent()) {
        const detail =
          error instanceof CreatorHttpError
            ? error.userMessage
            : (error as Error).message;
        setRegenerationError(detail);
        message.error(detail);
      }
    } finally {
      await finishMonitor?.();
      if (regenerationRequest.current === request) {
        regenerationRequest.current = null;
        if (epoch === workbenchEpoch.current) {
          setRegeneratingNode(null);
          setSynchronizing(false);
        }
      }
    }
  };

  const slotOf = (name: string): ArtifactSlotDocument | null => {
    const output = element.outputs[name];
    return output
      ? project.assets.artifact_slots_by_id[output.slot_id] ?? null
      : null;
  };
  const storyboardSlot = slotOf("storyboard");
  const videoSlot =
    slotOf("video") ??
    slotOf("main") ??
    Object.keys(element.outputs)
      .filter((name) => name !== "storyboard")
      .map(slotOf)
      .find(Boolean) ??
    null;
  const storyboardVersions = versionsOfSlot(project, storyboardSlot);
  const videoVersions = versionsOfSlot(project, videoSlot);
  const effectiveSbId =
    viewedSbId ??
    storyboardSlot?.selected_version_id ??
    storyboardVersions.at(-1)?.version_id ??
    null;
  const effectiveVideoId =
    viewedVideoId ??
    videoSlot?.selected_version_id ??
    videoVersions.at(-1)?.version_id ??
    null;
  const viewedStoryboard =
    storyboardVersions.find(
      (version) => version.version_id === effectiveSbId,
    ) ?? null;
  const viewedVideo =
    videoVersions.find((version) => version.version_id === effectiveVideoId) ??
    null;
  const storyboardUrl = mediaUrlOf(project, viewedStoryboard, "image/");
  const videoUrl = mediaUrlOf(project, viewedVideo, "video/");
  const setCurrentVersion = (
    slot: ArtifactSlotDocument,
    version: ArtifactVersionDocument,
  ) => {
    const kind =
      slot.slot_id === storyboardSlot?.slot_id ? "storyboard" : "video";
    candidateSelectionRevision.current[kind] += 1;
    delete candidateFollow.current[kind];
    return patchOps([
      {
        op: "replace",
        path: projectJsonPointer(
          "assets",
          "artifact_slots_by_id",
          slot.slot_id,
          "selected_version_id",
        ),
        before: slot.selected_version_id,
        value: version.version_id,
      },
    ]);
  };

  const elementRef = `element:${element.element_id}`;
  const latestStageTask = (kind: TaskView["kind"]) =>
    [...tasks]
      .filter(
        (task: TaskView) =>
          task.projectId === projectId &&
          task.targetRef === elementRef &&
          task.kind === kind,
      )
      .sort(
        (left, right) =>
          Date.parse(right.createdAt || right.updatedAt || "") -
          Date.parse(left.createdAt || left.updatedAt || ""),
      )[0];
  const videoTask = latestStageTask("r2v_generation");
  const storyboardTask = latestStageTask("image_generation");
  const videoGenerating =
    videoTask?.status === "RUNNING" || videoTask?.status === "QUEUED";
  const videoFailed =
    videoTask &&
    ["FAILED", "CANCELLED", "QUARANTINED"].includes(videoTask.status);
  const videoTaskMessage = (() => {
    if (!videoTask) return "";
    return t(`r2v.stageTask.video.${videoTask.status}`);
  })();
  const stageTaskStatus = (
    kind: "storyboard" | "video",
    task: TaskView | undefined,
  ) => {
    if (!task || task.status === "SUCCEEDED") return null;
    const active = task.status === "QUEUED" || task.status === "RUNNING";
    const progress =
      task.status === "RUNNING" ? taskProgressPercent(task.progress) : null;
    return (
      <p
        data-stage-task={kind}
        data-task-status={task.status}
        role="status"
        className={`text-xs leading-5 ${
          active
            ? "text-[var(--color-text-secondary)]"
            : "text-[var(--color-error)]"
        }`}
      >
        {t(`r2v.stageTask.${kind}.${task.status}`)}
        {progress != null && progress > 0 ? ` · ${progress}%` : ""}
      </p>
    );
  };

  const spanSeconds = element.span.duration_tick / timeline.ticks_per_second;

  const topBarActions = (
    <div className="flex flex-wrap items-center gap-2">{headerExtra}</div>
  );
  const topBar = (
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]/60 px-5 py-3 backdrop-blur">
      <div className="flex min-w-0 items-center gap-2">
        {!embedded && (
          <button
            type="button"
            onClick={requestBack}
            className="icon-button shrink-0"
            aria-label={t("nav.backToPlan")}
          >
            <ArrowLeft className="h-3.5 w-3.5" />
          </button>
        )}
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-[var(--color-text-primary)]">
            {t("r2v.title", { element: elementLabel })}
            <span
              data-generation-mode={generationMode}
              className="ml-2 inline-block rounded-full border border-[var(--color-border-secondary)] px-2 py-[1px] align-middle text-[10px] font-medium text-[var(--color-text-secondary)]"
            >
              {t(modeMeta.labelKey)}
            </span>
          </h2>
          <p className="mt-0.5 truncate text-xs text-[var(--color-text-secondary)]">
            {t(modeMeta.subtitleKey)}
          </p>
        </div>
      </div>
      {topBarActions}
    </div>
  );
  const conflictBanner = elementDraft.conflictPaths.length > 0 && (
    <Alert
      type="warning"
      showIcon
      banner
      message={t("r2v.conflictTitle")}
      description={t("r2v.conflictDesc")}
      action={
        <Button size="small" onClick={elementDraft.acceptConflicts}>
          {t("r2v.useMyChanges")}
        </Button>
      }
    />
  );
  // creation.intent / creation.continuity are global coherence anchors;
  // read-only, hidden entirely when both are empty.
  const contextIntent = presentPromptEntityNames(
    creation.intent?.trim() ?? "",
    project,
  );
  const contextContinuity = presentPromptEntityNames(
    (creation.type === "s2v" ? "" : creation.continuity?.trim()) ?? "",
    project,
  );
  const contextCard = (contextIntent || contextContinuity) && (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-lg border border-dashed border-[var(--color-border-strong)] bg-[var(--color-bg-secondary)]/45 px-2.5 py-1.5 text-[10.5px] leading-relaxed text-[var(--color-text-secondary)]">
      {contextIntent && (
        <>
          <span className="shrink-0 font-bold text-[var(--color-text-tertiary)]">
            {t("r2v.ctxIntent")}
          </span>
          <span className="min-w-0">{contextIntent}</span>
        </>
      )}
      {contextContinuity && (
        <>
          <span className="shrink-0 font-bold text-[var(--color-text-tertiary)]">
            {t("r2v.ctxContinuity")}
          </span>
          <span className="min-w-0">{contextContinuity}</span>
        </>
      )}
    </div>
  );
  const lightbox = lightboxSrc && (
    <Image
      style={{ display: "none" }}
      src={lightboxSrc}
      preview={{
        visible: true,
        src: lightboxSrc,
        onVisibleChange: (visible) => {
          if (!visible) setLightboxSrc(null);
        },
      }}
    />
  );

  // ── Mode-specific workbenches ─────────────────────────────────────────
  // t2v/i2v/s2v carry none of the shot/storyboard/reference machinery, so
  // they render a content-hugging single surface built from exactly the
  // provider inputs.
  if (creation.type !== "r2v") {
    const modeCreation = creation;
    const imageOptions = [
      ...Object.values(project.assets.artifact_versions_by_id)
        .filter(
          (version) =>
            project.assets.files_by_id[version.file_id]?.media_type.startsWith(
              "image/",
            ),
        )
        .map((version) => ({
          value: version.version_id,
          label: version.name || version.version_id,
          url: getArtifactVersionMediaUrl(version.version_id),
        })),
      ...Object.values(project.assets.source_versions_by_id)
        .filter((version) => version.media_kind === "image")
        .map((version) => ({
          value: version.version_id,
          label: version.name || version.version_id,
          url: getAssetVersionMediaUrl(version.version_id),
        })),
    ];
    const audioOptions = [
      ...Object.values(project.assets.source_versions_by_id)
        .filter((version) => version.media_kind === "audio")
        .map((version) => ({
          value: version.version_id,
          label: version.name || version.version_id,
          url: getAssetVersionMediaUrl(version.version_id),
        })),
      ...Object.values(project.assets.artifact_versions_by_id)
        .filter(
          (version) =>
            project.assets.files_by_id[version.file_id]?.media_type.startsWith(
              "audio/",
            ),
        )
        .map((version) => ({
          value: version.version_id,
          label: version.name || version.version_id,
          url: getArtifactVersionMediaUrl(version.version_id),
        })),
    ];
    const imageUrlOf = (versionId: string | null) =>
      imageOptions.find((option) => option.value === versionId)?.url ?? null;
    const audioUrlOf = (versionId: string | null) =>
      audioOptions.find((option) => option.value === versionId)?.url ?? null;
    const updateModeField = (field: string, value: string | null) =>
      updateElement((draft) => {
        (draft.creation as unknown as Record<string, unknown>)[field] = value;
      });
    const imagePicker = (
      value: string | null,
      field: string,
      placeholder: string,
      alt: string,
    ) => (
      <div className="space-y-2">
        <Select
          size="small"
          className="!w-full"
          placeholder={placeholder}
          value={value}
          disabled={patching}
          options={imageOptions}
          onChange={(next) => updateModeField(field, next ?? null)}
          allowClear
        />
        {imageUrlOf(value) ? (
          <MediaFrame src={imageUrlOf(value)!} alt={alt} maxHeight="260px" />
        ) : (
          <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-[var(--color-border)] text-xs text-[var(--color-text-tertiary)]">
            {t("r2v.notSelected")}
          </div>
        )}
      </div>
    );

    return (
      <div
        data-mode-workbench={modeCreation.type}
        onBlurCapture={handleFieldBlurCapture}
        className="flex h-full flex-col overflow-hidden bg-[var(--color-bg-layout)]"
      >
        {topBar}
        {conflictBanner}

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <div className="mx-auto grid w-full max-w-[1100px] items-start gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div className="space-y-3">
              {contextCard}
              {modeCreation.type === "s2v" ? (
                <>
                  <Panel title={t("r2v.s2vPortrait")}>
                    {imagePicker(
                      modeCreation.portrait_version_id,
                      "portrait_version_id",
                      t("r2v.s2vPortraitPlaceholder"),
                      t("r2v.s2vPortrait"),
                    )}
                  </Panel>
                  <Panel title={t("r2v.s2vScript")}>
                    <PromptTextArea
                      label={t("r2v.s2vScriptLabel")}
                      placeholder={t("r2v.s2vScriptPlaceholder")}
                      value={modeCreation.script}
                      field="script"
                      path={elementPointer("creation", "script")}
                      disabled={patching}
                      onChange={(value) => updateModeField("script", value)}
                      onRegenerate={() => void regenerateNode("video")}
                      regenerating={
                        regeneratingNode === `video:${element.element_id}`
                      }
                      regenerateLabel={t("r2v.regenerateVideo")}
                    />
                  </Panel>
                  <Panel title={t("r2v.s2vAudio")}>
                    <div className="space-y-2">
                      <Select
                        size="small"
                        className="!w-full"
                        placeholder={t("r2v.s2vAudioPlaceholder")}
                        value={modeCreation.audio_version_id}
                        disabled={patching}
                        options={audioOptions}
                        onChange={(value) =>
                          updateModeField("audio_version_id", value ?? null)
                        }
                        allowClear
                      />
                      {audioUrlOf(modeCreation.audio_version_id) ? (
                        <audio
                          controls
                          preload="metadata"
                          src={audioUrlOf(modeCreation.audio_version_id)!}
                          className="h-10 w-full"
                        />
                      ) : (
                        <div className="flex h-10 items-center justify-center rounded-lg border border-dashed border-[var(--color-border)] text-xs text-[var(--color-text-tertiary)]">
                          {t("r2v.notSelected")}
                        </div>
                      )}
                    </div>
                  </Panel>
                </>
              ) : (
                <>
                  {modeCreation.type === "i2v" && (
                    <Panel title={t("r2v.i2vFirstFrame")}>
                      {imagePicker(
                        modeCreation.first_frame_version_id,
                        "first_frame_version_id",
                        t("r2v.i2vFirstFramePlaceholder"),
                        t("r2v.i2vFirstFrame"),
                      )}
                    </Panel>
                  )}
                  <Panel title={t("r2v.videoPrompt")}>
                    <PromptTextArea
                      label={t("r2v.videoPromptLabel")}
                      placeholder={t("r2v.videoPromptPlaceholder")}
                      value={modeCreation.video_prompt}
                      field="video_prompt"
                      path={elementPointer("creation", "video_prompt")}
                      disabled={patching}
                      onChange={(value) =>
                        updateModeField("video_prompt", value)
                      }
                      onRegenerate={() => void regenerateNode("video")}
                      regenerating={
                        regeneratingNode === `video:${element.element_id}`
                      }
                      regenerateLabel={t("r2v.regenerateVideo")}
                    />
                  </Panel>
                </>
              )}
            </div>

            <div data-workbench-overview className="space-y-5">
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <SectionLabel text={t("r2v.videoGenResult")} />
                  <ArtifactVersionChips
                    versions={videoVersions}
                    currentId={videoSlot?.selected_version_id}
                    viewingId={effectiveVideoId}
                    onView={(id) => viewCandidate("video", id)}
                  />
                </div>
                {videoUrl ? (
                  <div
                    data-review-media-anchor={viewedVideo?.version_id}
                    className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[#141210]"
                  >
                    <video
                      src={videoUrl}
                      controls
                      className="aspect-video w-full"
                    />
                  </div>
                ) : (
                  <div className="flex aspect-video w-full items-center justify-center rounded-lg border border-dashed border-[var(--color-border)] text-xs text-[var(--color-text-tertiary)]">
                    {t("r2v.noVideoResult")}
                  </div>
                )}
                {videoTask && (videoGenerating || videoFailed) && (
                  <p
                    className={`text-[11px] ${
                      videoFailed
                        ? "text-[var(--color-error)]"
                        : "text-[var(--color-text-tertiary)]"
                    }`}
                  >
                    {videoTaskMessage}
                  </p>
                )}
                {viewedVideo &&
                  videoSlot &&
                  viewedVideo.version_id !== videoSlot.selected_version_id && (
                    <Button
                      size="small"
                      type="primary"
                      disabled={elementDraft.dirty || patching}
                      onClick={() =>
                        void setCurrentVersion(videoSlot, viewedVideo)
                      }
                      className="!text-[11px]"
                    >
                      {t("r2v.setAsCurrent")}
                    </Button>
                  )}
              </div>

              {elementEntities.some(
                (entity) => entity.kind === "character",
              ) && (
                <span className="block text-sm font-medium text-[var(--color-text-primary)]">
                  {t("r2v.relatedAssets")}
                </span>
              )}
              <EntityGroup
                label={t("blueprint.entityKinds.character")}
                entities={elementEntities.filter(
                  (entity) => entity.kind === "character",
                )}
                onOpen={openVisualEntity}
              />
            </div>
          </div>
        </div>
        {lightbox}
      </div>
    );
  }

  // Input references: aggregated from the R2V creation's reference fields,
  // matching origin/main's resolvedRefs. If a material version is itself the
  // generated image of an already-referenced visual entity (scene/character/
  // prop), don't show it again under "materials" — avoids the semantic
  // duplication of "scene" vs "scene visual image".
  const referencedEntityIds = new Set(
    [creation.scene_ref, ...creation.character_refs, ...creation.prop_refs]
      .filter((ref): ref is string => Boolean(ref))
      .map((ref) => ref.replace(/^visual-entity:/, "")),
  );
  const materialVersionIds =
    stage === "sb"
      ? creation.storyboard_reference_version_ids
      : creation.video_reference_version_ids;
  // Historical data carries entity ownership under several prefixes
  // (visual-entity: / asset: / bare); if the normalized ID hits a visual
  // entity, treat the artifact as that entity's output.
  const ownerEntityId = (ownerRef: string): string | null => {
    const entityId = ownerRef.replace(/^(?:visual-entity|asset):/, "");
    return project.visual.entities.items[entityId] ? entityId : null;
  };
  const isReferencedEntityArtifact = (versionId: string) => {
    const owner =
      project.assets.artifact_versions_by_id[versionId]?.owner_ref ?? "";
    const entityId = ownerEntityId(owner);
    return entityId !== null && referencedEntityIds.has(entityId);
  };
  // ── 相关资产 rail editing ────────────────────────────────────────────
  // Only assets bound here feed the prompt reference tokens (sbTokens /
  // vdTokens below aggregate from these same creation fields), so adding or
  // removing a card directly widens/narrows what prompts may cite.
  const normalizeVisualEntityId = (ref: string) =>
    ref.replace(/^visual-entity:/, "");
  // Add/remove is a discrete action — itself a semantic boundary — so the
  // draft is persisted right after the click, like a field blur.
  const commitReferenceEdit = (mutate: () => void) => {
    mutate();
    scheduleSilentApply();
  };
  const changeEntityReferences = (
    field: "scene" | "characters" | "props",
    nextRefs: string[],
  ) =>
    updateElement((draft) => {
      if (draft.creation.type !== "r2v") return;
      const nextEntityIds = nextRefs.map(normalizeVisualEntityId);
      const previousEntityIds =
        field === "scene"
          ? draft.creation.scene_ref
            ? [normalizeVisualEntityId(draft.creation.scene_ref)]
            : []
          : field === "characters"
          ? draft.creation.character_refs.map(normalizeVisualEntityId)
          : draft.creation.prop_refs.map(normalizeVisualEntityId);
      for (const entityId of previousEntityIds) {
        if (nextEntityIds.includes(entityId)) continue;
        delete draft.creation.visual_variant_refs[entityId];
        delete draft.creation.visual_variant_refs[`visual-entity:${entityId}`];
      }
      if (field === "scene") {
        draft.creation.scene_ref = nextEntityIds[0] ?? null;
      } else if (field === "characters") {
        draft.creation.character_refs = nextEntityIds;
      } else {
        draft.creation.prop_refs = nextEntityIds;
      }
      for (const entityId of nextEntityIds) {
        const entity = project.visual.entities.items[entityId];
        if (
          entity?.variants.order.length === 1 &&
          !draft.creation.visual_variant_refs[entityId]
        ) {
          draft.creation.visual_variant_refs[entityId] =
            entity.variants.order[0];
        }
      }
    });
  const changeMaterialReferences = (next: string[]) =>
    updateElement((draft) => {
      if (draft.creation.type !== "r2v") return;
      if (stage === "sb")
        draft.creation.storyboard_reference_version_ids = next;
      else draft.creation.video_reference_version_ids = next;
    });
  const entityKindRefs = (kind: "character" | "scene" | "prop"): string[] =>
    kind === "character"
      ? creation.character_refs
      : kind === "prop"
      ? creation.prop_refs
      : creation.scene_ref
      ? [creation.scene_ref]
      : [];
  const removeEntityRef = (kind: "character" | "scene" | "prop", id: string) =>
    commitReferenceEdit(() => {
      const field =
        kind === "scene"
          ? ("scene" as const)
          : kind === "character"
          ? ("characters" as const)
          : ("props" as const);
      changeEntityReferences(
        field,
        entityKindRefs(kind).filter(
          (ref) => normalizeVisualEntityId(ref) !== id,
        ),
      );
    });
  const isAutomaticStoryboardReference = (versionId: string) =>
    stage === "vd" &&
    Boolean(
      storyboardSlot &&
        (storyboardSlot.version_ids.includes(versionId) ||
          project.assets.artifact_versions_by_id[versionId]?.slot_id ===
            storyboardSlot.slot_id),
    );
  // Video inputs bind the current image from this exact storyboard slot.
  // Historical self references are not extra materials; keep other shots'
  // storyboard versions available as explicit references.
  // Materials (素材): loose image/video versions referenced alongside the
  // entities. Cards hide versions already represented by an entity above.
  const materialCards = materialVersionIds
    .filter(
      (versionId) =>
        !isReferencedEntityArtifact(versionId) &&
        !isAutomaticStoryboardReference(versionId),
    )
    .map((versionId) => ({
      versionId,
      name: referenceVersionName(project, versionId),
      thumbUrl: refImageThumbUrl(
        project,
        creation,
        project.assets.artifact_versions_by_id[versionId]
          ? `artifact-version:${versionId}`
          : `asset-version:${versionId}`,
      ),
    }));
  const materialCandidates = [
    ...Object.values(project.assets.source_versions_by_id).filter((version) =>
      ["image", "video"].includes(version.media_kind ?? ""),
    ),
    ...Object.values(project.assets.artifact_versions_by_id).filter(
      (version) => {
        const mediaType =
          project.assets.files_by_id[version.file_id]?.media_type ?? "";
        return (
          (mediaType.startsWith("image/") || mediaType.startsWith("video/")) &&
          version.owner_ref !== `element:${element.element_id}` &&
          !ownerEntityId(version.owner_ref ?? "")
        );
      },
    ),
  ].filter((version) => !materialVersionIds.includes(version.version_id));
  const removeMaterialRef = (versionId: string) =>
    commitReferenceEdit(() =>
      changeMaterialReferences(
        materialVersionIds.filter((id) => id !== versionId),
      ),
    );
  // 缩略版资产库 candidates: every visual entity plus every loose material
  // version (bound ones included so they open pre-selected).
  const pickerCandidates: PickerCandidate[] = [
    ...project.visual.entities.order
      .map((entityId) => project.visual.entities.items[entityId])
      .filter(Boolean)
      .map((entity) => ({
        id: entity.entity_id,
        kind: entity.kind as PickerCandidate["kind"],
        name: entity.name,
        thumbUrl: refImageThumbUrl(project, creation, entity.entity_id),
      })),
    ...materialCards.map((card) => ({
      id: card.versionId,
      kind: "material" as const,
      name: card.name,
      thumbUrl: card.thumbUrl,
    })),
    ...materialCandidates.map((version) => ({
      id: version.version_id,
      kind: "material" as const,
      name: version.name || version.version_id,
      thumbUrl: refImageThumbUrl(
        project,
        creation,
        project.assets.artifact_versions_by_id[version.version_id]
          ? `artifact-version:${version.version_id}`
          : `asset-version:${version.version_id}`,
      ),
    })),
  ];
  const pickerBoundIds = [
    ...entityKindRefs("character").map(normalizeVisualEntityId),
    ...entityKindRefs("scene").map(normalizeVisualEntityId),
    ...entityKindRefs("prop").map(normalizeVisualEntityId),
    ...materialCards.map((card) => card.versionId),
  ];
  const handlePickerConfirm = (selectedIds: string[]) => {
    const selectedSet = new Set(selectedIds);
    const idsOfKind = (kind: PickerCandidate["kind"]) =>
      pickerCandidates
        .filter(
          (candidate) =>
            candidate.kind === kind && selectedSet.has(candidate.id),
        )
        .map((candidate) => candidate.id);
    // Keep the existing binding order for refs that stay selected — the
    // order feeds [Image N] numbering, so an unchanged pick must be a
    // byte-identical no-op (no PATCH, no stale marks, no paid re-dispatch).
    const mergeKeepingOrder = (previous: string[], next: string[]) => {
      const nextSet = new Set(next);
      return [
        ...previous.filter((id) => nextSet.has(id)),
        ...next.filter((id) => !previous.includes(id)),
      ];
    };
    const sameList = (a: string[], b: string[]) =>
      a.length === b.length && a.every((value, index) => value === b[index]);
    const previousCharacters = entityKindRefs("character").map(
      normalizeVisualEntityId,
    );
    const previousProps = entityKindRefs("prop").map(normalizeVisualEntityId);
    const previousScene = entityKindRefs("scene").map(normalizeVisualEntityId);
    const nextCharacters = mergeKeepingOrder(
      previousCharacters,
      idsOfKind("character"),
    );
    const nextProps = mergeKeepingOrder(previousProps, idsOfKind("prop"));
    const nextScene = idsOfKind("scene");
    // Materials not shown in the picker (an entity's own artifact riding in
    // the reference arrays) are preserved verbatim.
    const pickableMaterialIds = new Set(
      pickerCandidates
        .filter((candidate) => candidate.kind === "material")
        .map((candidate) => candidate.id),
    );
    const nextMaterials = [
      ...materialVersionIds.filter(
        (id) => !pickableMaterialIds.has(id) || selectedSet.has(id),
      ),
      ...idsOfKind("material").filter((id) => !materialVersionIds.includes(id)),
    ];
    const changed =
      !sameList(previousCharacters, nextCharacters) ||
      !sameList(previousProps, nextProps) ||
      !sameList(previousScene, nextScene) ||
      !sameList(materialVersionIds, nextMaterials);
    if (changed) {
      commitReferenceEdit(() => {
        changeEntityReferences("characters", nextCharacters);
        changeEntityReferences("scene", nextScene);
        changeEntityReferences("props", nextProps);
        changeMaterialReferences(nextMaterials);
      });
    }
    setAssetPickerOpen(false);
  };

  // A dirty reference binding has no verified provider order yet. Prompt
  // Prompt edits keep the current reference mapping intact.
  const referenceDraftChanged = elementDraft.dirtyPaths.some((path) =>
    /\/creation\/(?:storyboard_reference_version_ids|video_reference_version_ids|scene_ref|character_refs|prop_refs|visual_variant_refs|cast_lineup_refs)(?:\/|$)/.test(
      path,
    ),
  );

  // The storyboard the backend will lock as [Image 1] is the *selected*
  // version, not whichever one is being viewed.
  const currentStoryboard =
    storyboardVersions.find(
      (version) => version.version_id === storyboardSlot?.selected_version_id,
    ) ?? null;
  const currentStoryboardUrl = mediaUrlOf(project, currentStoryboard, "image/");
  const currentStoryboardLabel = currentStoryboard
    ? `v${storyboardVersions.indexOf(currentStoryboard) + 1}`
    : "";

  const tokensForOrder = (
    order: R2VReferenceOrderResponse | null,
  ): PromptRichToken[] => {
    if (
      referenceDraftChanged ||
      !order ||
      order.elementId !== element.element_id
    )
      return [];
    return order.references.map((item) => {
      const artifact = project.assets.artifact_versions_by_id[item.versionId];
      const source = project.assets.source_versions_by_id[item.versionId];
      const available =
        item.available !== false &&
        (source?.media_kind === "image" ||
          Boolean(
            artifact &&
              project.assets.files_by_id[
                artifact.file_id
              ]?.media_type.startsWith("image/"),
          ));
      return {
        index: item.index,
        referenceId: item.versionId,
        name: item.name,
        kind: item.kind,
        missing: !available,
        thumbUrl: !available
          ? null
          : source
          ? getAssetVersionMediaUrl(item.versionId)
          : getArtifactVersionMediaUrl(item.versionId),
      };
    });
  };
  const sbTokens = tokensForOrder(storyboardReferenceOrder);
  const vdTokens = tokensForOrder(referenceOrder);

  const stageTabs = (
    <div className="flex shrink-0 flex-wrap gap-0.5 border-b border-[var(--color-border)] px-3">
      {[
        {
          key: "sb" as const,
          step: 1,
          title: t("r2v.stageStoryboard"),
          sub: t("r2v.stageStoryboardSub"),
        },
        {
          key: "vd" as const,
          step: 2,
          title: t("r2v.stageVideo"),
          sub: t("r2v.stageVideoSub"),
        },
      ].map((tab) => {
        const active = stage === tab.key;
        return (
          <button
            key={tab.key}
            type="button"
            data-stage-tab={tab.key}
            onClick={() => setStage(tab.key)}
            className={`-mb-px flex items-center gap-1.5 border-b-2 px-3.5 pb-2 pt-2.5 text-xs font-bold transition-colors ${
              active
                ? "border-[var(--color-accent)] text-[var(--color-accent)]"
                : "border-transparent text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]"
            }`}
          >
            <span
              className={`flex h-4 w-4 items-center justify-center rounded-full border text-[9px] font-bold ${
                active
                  ? "border-[var(--color-accent)] bg-[var(--color-accent)] text-white"
                  : "border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-tertiary)]"
              }`}
            >
              {tab.step}
            </span>
            {tab.title}
            <span className="text-[9.5px] font-normal text-[var(--color-text-tertiary)]">
              {tab.sub}
            </span>
          </button>
        );
      })}
    </div>
  );

  return (
    <div
      data-r2v-workbench={element.element_id}
      onBlurCapture={handleFieldBlurCapture}
      className="r2v-workbench-root flex h-full min-w-0 flex-col overflow-hidden bg-[var(--color-bg-layout)]"
    >
      {topBar}
      {conflictBanner}

      <div data-workbench-layout className="r2v-workbench-layout">
        {/* Prompt and storyboard workspace */}
        <div
          data-workbench-pane="prompt"
          className="r2v-workbench-prompt flex min-w-0 flex-col"
        >
          <section className="flex min-h-0 flex-1 flex-col rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)]">
            {stageTabs}
            {synchronizing && (
              <div className="r2v-generation-preparing" role="status">
                <Loader2
                  size={14}
                  className="motion-safe:animate-spin"
                  aria-hidden
                />
                <span>
                  {t("r2v.sync.automaticWaiting", {
                    seconds: preparationSeconds,
                  })}
                </span>
              </div>
            )}
            {regenerationError && (
              <Alert
                className="mx-3 mt-2"
                type="warning"
                showIcon
                message={regenerationError}
              />
            )}
            {contextCard && <div className="px-3.5 pt-2.5">{contextCard}</div>}
            <details
              className="r2v-narrative mx-3.5 mt-2.5"
              open={reviewField?.includes("/creation/narrative") || undefined}
            >
              <summary className="cursor-pointer text-xs font-medium text-[var(--color-text-secondary)]">
                {t("r2v.narrativeTitle")}
              </summary>
              <div className="mt-2">
                <PromptRichBlock
                  label={t("r2v.narrativeTitle")}
                  value={creation.narrative}
                  field={`element:${element.element_id}/creation/narrative`}
                  path={elementPointer("creation", "narrative")}
                  disabled={patching}
                  tokens={[]}
                  collapseHeight={150}
                  onEditComplete={scheduleSilentApply}
                  onChange={(value) =>
                    updateElement((draft) => {
                      if (draft.creation.type === "r2v")
                        draft.creation.narrative = value;
                    })
                  }
                />
              </div>
            </details>
            <div className="r2v-workbench-prompt-body min-w-0 flex-1 p-4">
              {/* Stage ①: storyboard prompt + versions. Both stages stay
                  mounted (hidden attr) so field anchors and review focus
                  keep resolving regardless of the visible tab. */}
              <div hidden={stage !== "sb"} data-stage-panel="sb">
                <div className="space-y-3">
                  {reviewMode &&
                    reviewField ===
                      elementPointer(
                        "creation",
                        "storyboard_reference_version_ids",
                      ) && (
                      <section
                        data-creator-path={elementPointer(
                          "creation",
                          "storyboard_reference_version_ids",
                        )}
                        data-review-reference-field="storyboard"
                      >
                        <SectionLabel
                          text={t("fileReview.public.referenceImages")}
                        />
                        <InlineReviewDiff
                          pointer={elementPointer(
                            "creation",
                            "storyboard_reference_version_ids",
                          )}
                        />
                      </section>
                    )}
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-[10px] text-[var(--color-text-tertiary)]">
                      {t("r2v.storyboardVersions")}
                    </span>
                    <ArtifactVersionChips
                      versions={storyboardVersions}
                      currentId={storyboardSlot?.selected_version_id}
                      viewingId={effectiveSbId}
                      onView={(id) => viewCandidate("storyboard", id)}
                    />
                  </div>
                  {storyboardUrl ? (
                    <MediaFrame
                      src={storyboardUrl}
                      alt={t("lib.storyboard")}
                      maxHeight="min(320px, 34vh)"
                      anchorVersionId={viewedStoryboard?.version_id}
                    />
                  ) : (
                    <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-[var(--color-border)] text-xs text-[var(--color-text-tertiary)]">
                      {t("r2v.noStoryboard")}
                    </div>
                  )}
                  {viewedStoryboard?.stale && (
                    <p className="text-[10px] text-[var(--color-warning)]">
                      {t("r2v.storyboardStale")}
                    </p>
                  )}
                  {viewedStoryboard &&
                    storyboardSlot &&
                    viewedStoryboard.version_id !==
                      storyboardSlot.selected_version_id && (
                      <div className="flex items-center justify-between rounded-lg border border-[var(--color-warning)]/25 bg-[var(--color-warning-soft)] px-2.5 py-1.5">
                        <span className="text-[11px] text-[var(--color-warning)]">
                          {t("r2v.switchToStoryboard")}
                        </span>
                        <Button
                          size="small"
                          type="primary"
                          disabled={elementDraft.dirty || patching}
                          onClick={() =>
                            void setCurrentVersion(
                              storyboardSlot,
                              viewedStoryboard,
                            )
                          }
                          className="!text-[11px]"
                        >
                          {t("r2v.setAsCurrent")}
                        </Button>
                      </div>
                    )}
                  {storyboardReferenceOrder?.ready === false && (
                    <Alert
                      type="warning"
                      showIcon
                      message={t("r2v.referencesNeedReview")}
                    />
                  )}
                  <PromptRichBlock
                    label={t("r2v.storyboardPrompt")}
                    value={creation.storyboard_prompt}
                    field={`element:${element.element_id}/creation/storyboard_prompt`}
                    path={elementPointer("creation", "storyboard_prompt")}
                    disabled={patching}
                    tokens={sbTokens}
                    regenerateDisabled={
                      referenceDraftChanged ||
                      storyboardReferenceOrder?.ready === false
                    }
                    collapseHeight={230}
                    onRegenerate={() => void regenerateNode("storyboard")}
                    regenerating={
                      regeneratingNode === `storyboard:${element.element_id}`
                    }
                    regenerateLabel={t("r2v.regenerateImage")}
                    onEditComplete={scheduleSilentApply}
                    onChange={(value) =>
                      updateElement((draft) => {
                        if (draft.creation.type === "r2v")
                          draft.creation.storyboard_prompt = value;
                      })
                    }
                  />
                </div>
              </div>

              {/* Stage ②: video prompt with a compact storyboard context bar. */}
              <div hidden={stage !== "vd"} data-stage-panel="vd">
                <div className="space-y-3">
                  {reviewMode &&
                    reviewField ===
                      elementPointer(
                        "creation",
                        "video_reference_version_ids",
                      ) && (
                      <section
                        data-creator-path={elementPointer(
                          "creation",
                          "video_reference_version_ids",
                        )}
                        data-review-reference-field="video"
                      >
                        <SectionLabel
                          text={t("fileReview.public.referenceImages")}
                        />
                        <InlineReviewDiff
                          pointer={elementPointer(
                            "creation",
                            "video_reference_version_ids",
                          )}
                        />
                      </section>
                    )}
                  {currentStoryboardUrl && (
                    <button
                      type="button"
                      data-vd-context
                      onClick={() => setLightboxSrc(currentStoryboardUrl)}
                      className="flex w-full items-center gap-2.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/60 px-2.5 py-2 text-left transition-colors hover:border-[var(--color-border-strong)]"
                    >
                      <img
                        src={currentStoryboardUrl}
                        alt={t("lib.storyboard")}
                        className="w-[74px] shrink-0 rounded border border-[var(--color-border)]"
                      />
                      <span className="min-w-0 text-[11px] font-semibold text-[var(--color-text-primary)]">
                        {t("r2v.vdContextTitle", {
                          version: currentStoryboardLabel,
                        })}
                        <span className="mt-0.5 block text-[9.5px] font-normal text-[var(--color-text-tertiary)]">
                          {t("r2v.vdContextLocked")}
                        </span>
                      </span>
                    </button>
                  )}
                  <PromptRichBlock
                    label={t("r2v.videoPrompt")}
                    value={creation.video_prompt}
                    field={`element:${element.element_id}/creation/video_prompt`}
                    path={elementPointer("creation", "video_prompt")}
                    disabled={patching}
                    tokens={vdTokens}
                    collapseHeight={460}
                    onRegenerate={() => void regenerateNode("video")}
                    regenerating={
                      regeneratingNode === `video:${element.element_id}`
                    }
                    regenerateLabel={t("r2v.regenerateVideo")}
                    onEditComplete={scheduleSilentApply}
                    onChange={(value) =>
                      updateElement((draft) => {
                        if (draft.creation.type === "r2v")
                          draft.creation.video_prompt = value;
                      })
                    }
                  />
                </div>
              </div>
            </div>
          </section>
        </div>

        {/* ── Right rail: generation results, then 相关资产 ─────────────── */}
        <aside
          data-workbench-overview
          data-workbench-pane="results"
          className="r2v-workbench-results flex min-w-0 flex-col gap-5 pr-0.5"
        >
          <div
            data-result-stage="video"
            className="space-y-2"
            style={{ order: stage === "vd" ? 0 : 1 }}
          >
            <div className="flex items-center justify-between gap-2">
              <SectionLabel text={t("r2v.videoGenResult")} />
              <ArtifactVersionChips
                versions={videoVersions}
                currentId={videoSlot?.selected_version_id}
                viewingId={effectiveVideoId}
                onView={(id) => viewCandidate("video", id)}
              />
            </div>
            {stageTaskStatus("video", videoTask)}
            {videoUrl && viewedVideo ? (
              // <video> can't host ::after; put the review flash anchor on the wrapper.
              <div
                data-review-media-anchor={viewedVideo.version_id}
                className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-[#141210]"
              >
                <video
                  key={viewedVideo.version_id}
                  src={videoUrl}
                  controls
                  className="aspect-video w-full"
                />
              </div>
            ) : (
              <div className="flex aspect-video w-full flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed border-[var(--color-border)] text-xs text-[var(--color-text-tertiary)]">
                {videoGenerating ? (
                  <>
                    <span className="font-medium text-[var(--color-warning)]">
                      {t("r2v.r2vGenerating")}
                    </span>
                    <span>{videoTaskMessage}</span>
                    <Button
                      size="small"
                      onClick={() =>
                        void Promise.all([
                          refreshTasks(projectId),
                          pollOnce(projectId),
                        ])
                      }
                      className="!text-[11px]"
                    >
                      {t("r2v.manualRefresh")}
                    </Button>
                  </>
                ) : videoFailed ? (
                  <span className="px-3 text-center text-[var(--color-danger)]">
                    {videoTaskMessage}
                  </span>
                ) : (
                  t("r2v.noVideoYet")
                )}
              </div>
            )}
            {viewedVideo &&
              videoSlot &&
              viewedVideo.version_id !== videoSlot.selected_version_id && (
                <div className="flex items-center justify-between rounded-lg border border-[var(--color-warning)]/25 bg-[var(--color-warning-soft)] px-2.5 py-1.5">
                  <span className="text-[11px] text-[var(--color-warning)]">
                    {t("r2v.switchToVideo")}
                  </span>
                  <Button
                    size="small"
                    type="primary"
                    disabled={elementDraft.dirty || patching}
                    onClick={() =>
                      void setCurrentVersion(videoSlot, viewedVideo)
                    }
                    className="!text-[11px]"
                  >
                    {t("r2v.setAsCurrent")}
                  </Button>
                </div>
              )}
            {viewedVideo?.stale && (
              <p className="text-[10px] text-[var(--color-warning)]">
                {t("r2v.videoStale")}
              </p>
            )}
          </div>

          <div
            data-result-stage="storyboard"
            className="space-y-2"
            style={{ order: stage === "sb" ? 0 : 1 }}
          >
            <div className="flex items-center justify-between gap-2">
              <SectionLabel text={t("r2v.sbGenResult")} />
              <ArtifactVersionChips
                versions={storyboardVersions}
                currentId={storyboardSlot?.selected_version_id}
                viewingId={effectiveSbId}
                onView={(id) => viewCandidate("storyboard", id)}
              />
            </div>
            {stageTaskStatus("storyboard", storyboardTask)}
            {storyboardUrl ? (
              <button
                type="button"
                onClick={() => setLightboxSrc(storyboardUrl)}
                className="block w-full overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)]"
              >
                <img
                  src={storyboardUrl}
                  alt={t("lib.storyboard")}
                  className="aspect-video w-full object-cover"
                />
              </button>
            ) : (
              <div className="flex aspect-video w-full items-center justify-center rounded-lg border border-dashed border-[var(--color-border)] text-xs text-[var(--color-text-tertiary)]">
                {t("r2v.noStoryboard")}
              </div>
            )}
          </div>

          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-[var(--color-text-primary)]">
              {t("r2v.relatedAssets")}
            </span>
            <button
              type="button"
              data-add-asset
              disabled={patching}
              aria-label={t("r2v.addReference")}
              title={t("r2v.addReference")}
              onClick={() => setAssetPickerOpen(true)}
              className="flex h-6 w-6 items-center justify-center rounded-md border border-[var(--color-border)] text-[var(--color-text-secondary)] transition-colors hover:border-[var(--color-border-strong)] hover:text-[var(--color-text-primary)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>

          <EntityGroup
            label={t("blueprint.entityKinds.character")}
            entities={elementEntities.filter(
              (entity) => entity.kind === "character",
            )}
            onOpen={openVisualEntity}
            onRemove={(entityId) => removeEntityRef("character", entityId)}
          />
          <EntityGroup
            label={t("blueprint.entityKinds.scene")}
            entities={elementEntities.filter(
              (entity) => entity.kind === "scene",
            )}
            onOpen={openVisualEntity}
            onRemove={(entityId) => removeEntityRef("scene", entityId)}
          />
          <EntityGroup
            label={t("blueprint.entityKinds.prop")}
            entities={elementEntities.filter(
              (entity) => entity.kind === "prop",
            )}
            onOpen={openVisualEntity}
            onRemove={(entityId) => removeEntityRef("prop", entityId)}
          />

          {materialCards.length > 0 && (
            <div className="space-y-2">
              <SectionLabel text={t("r2v.fieldLabels.sources")} />
              <div className="grid grid-cols-2 gap-2.5">
                {materialCards.map((card) => (
                  <div
                    key={card.versionId}
                    data-material-version={card.versionId}
                    className="group/card relative"
                  >
                    <span
                      className={`relative block aspect-video w-full overflow-hidden rounded-lg border ${
                        card.thumbUrl
                          ? "border-[var(--color-border)] bg-[var(--color-bg-secondary)]"
                          : "border-dashed border-[var(--color-border-strong)] bg-[var(--color-bg-secondary)]/50"
                      }`}
                    >
                      {card.thumbUrl ? (
                        <img
                          src={card.thumbUrl}
                          alt=""
                          loading="lazy"
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <span className="flex h-full w-full flex-col items-center justify-center gap-1">
                          <LucideImageIcon className="h-5 w-5 text-[var(--color-text-tertiary)]" />
                          <span className="text-[10px] text-[var(--color-text-tertiary)]">
                            {t("blueprint.notGenerated")}
                          </span>
                        </span>
                      )}
                      <span className="absolute right-1 top-1 rounded bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white">
                        {t("r2v.fieldLabels.sources")}
                      </span>
                    </span>
                    <span className="mt-1 block truncate text-xs text-[var(--color-text-primary)]">
                      {card.name}
                    </span>
                    <button
                      type="button"
                      aria-label={t("blueprint.removeEntity")}
                      title={t("blueprint.removeEntity")}
                      onClick={() => removeMaterialRef(card.versionId)}
                      className="absolute -right-1.5 -top-1.5 hidden h-5 w-5 items-center justify-center rounded-full border border-[var(--color-border)] bg-[var(--color-bg-primary)] text-[var(--color-text-secondary)] shadow-sm hover:text-[var(--color-error)] group-hover/card:flex"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </aside>
      </div>
      <RelatedAssetPicker
        open={assetPickerOpen}
        candidates={pickerCandidates}
        boundIds={pickerBoundIds}
        onCancel={() => setAssetPickerOpen(false)}
        onConfirm={handlePickerConfirm}
      />
      {lightbox}
    </div>
  );
}

/** Route shell: owns router state (params, review query) and back navigation. */
export default function R2VWorkbenchPage() {
  const { id = "", elementId = "", timelineId: timelineIdParam } = useParams();
  const query = useSearchParams();
  const reviewMode = query.get("review") === "1";
  const reviewField = query.get("field");
  const reviewPulse = query.get("reviewPulse");
  const versionFromUrl = query.get("version");
  const onBack = useCallback(() => {
    // Route param wins (parameterized /t/:timelineId/...); the legacy route
    // falls back to the primary timeline.
    const planPath = timelineIdParam
      ? `/project/${id}/t/${encodeURIComponent(timelineIdParam)}/plan`
      : `/project/${id}/plan`;
    navigate(
      elementId
        ? `${planPath}?element=${encodeURIComponent(elementId)}`
        : planPath,
    );
  }, [id, elementId, timelineIdParam]);
  return (
    <WorkbenchSurface
      projectId={id}
      elementId={elementId}
      timelineId={timelineIdParam ?? null}
      onBack={onBack}
      reviewMode={reviewMode}
      reviewField={reviewField}
      reviewPulse={reviewPulse}
      versionFromUrl={versionFromUrl}
    />
  );
}
