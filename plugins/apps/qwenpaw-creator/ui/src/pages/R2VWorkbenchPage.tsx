import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Input, Modal, Select, Tooltip, message } from "antd";
import { AlertTriangle, ArrowLeft } from "lucide-react";
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
import { selectPrimaryTimeline } from "@/selectors/timelineElementSelectors";
import {
  getArtifactVersionMediaUrl,
  getAssetVersionMediaUrl,
  getResolvedModels,
} from "@/api/creator";
import type { ResolvedModels } from "@/api/creator/models";
import { projectJsonPointer } from "@/lib/projectJsonPointer";
import { useProjectDraft } from "@/lib/useProjectDraft";
import { visualVariantLabel } from "@/lib/visualVariants";
import PageSkeleton from "@/components/PageSkeleton";
import PageLoadError from "@/components/PageLoadError";
import InlineReviewDiff from "@/components/agent/InlineReviewDiff";
import ShotList from "@/components/workbench/ShotList";
import ArtifactVersionChips from "@/components/workbench/ArtifactVersionChips";
import type {
  ArtifactSlotDocument,
  ArtifactVersionDocument,
  ProjectDocument,
  TaskView,
  TimelineElementDocument,
  VideoCreationDocument,
  VideoGenerationMode,
} from "@/contracts/creator";
import { useTranslation } from "react-i18next";

const { TextArea } = Input;

type ReferenceField = "scene" | "characters" | "props" | "sources";

const FIELD_LABEL_KEYS: Record<ReferenceField, string> = {
  scene: "r2v.fieldLabels.scene",
  characters: "r2v.fieldLabels.characters",
  props: "r2v.fieldLabels.props",
  sources: "r2v.fieldLabels.sources",
};

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
}: {
  label: string;
  value: string;
  field: string;
  path: string;
  disabled?: boolean;
  placeholder?: string;
  onChange: (value: string) => void;
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
      <TextArea
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        autoSize={{ minRows: 2, maxRows: 10 }}
        placeholder={placeholder ?? t("r2v.generateAndEdit", { label })}
        className="!rounded-lg !border-[var(--color-border)] !bg-[var(--color-bg-secondary)] !text-xs"
      />
      <InlineReviewDiff pointer={path} />
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

function visualEntityName(project: ProjectDocument, ref: string): string {
  const entityId = ref.replace(/^visual-entity:/, "");
  return project.visual.entities.items[entityId]?.name ?? ref;
}

/** Normalize either a UI-prefixed ref or a canonical bare ID to an entity ID. */
function normalizeVisualEntityId(ref: string): string {
  return ref.replace(/^visual-entity:/, "");
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

export default function R2VWorkbenchPage() {
  const { t } = useTranslation();
  const { id = "", elementId = "" } = useParams();
  const query = useSearchParams();
  const reviewMode = query.get("review") === "1";
  const reviewField = query.get("field");
  const reviewPulse = query.get("reviewPulse");
  const versionFromUrl = query.get("version");
  useReviewFieldFocus({
    path: `/project/${id}/plan/element/${elementId}`,
    field: reviewField,
    enabled: reviewMode,
    pulse: reviewPulse,
  });
  // "View generation detail" for media reviews has no field pointer; flash the
  // preview block anchored by the version awaiting review.
  useReviewMediaFocus({
    versionId: versionFromUrl,
    enabled: reviewMode && !reviewField,
    pulse: reviewPulse,
  });
  const project = useProjectSnapshotStore((state) =>
    state.projectId === id ? state.project : null,
  );
  const syncStatus = useProjectSnapshotStore((state) => state.syncStatus);
  const syncError = useProjectSnapshotStore((state) => state.syncError);
  const patchProject = useProjectSnapshotStore((state) => state.patch);
  const patching = useProjectSnapshotStore((state) => state.patching);
  const pollOnce = useProjectSnapshotStore((state) => state.pollOnce);
  const tasks = useCreatorTaskViewStore((state) => state.tasks);
  const refreshTasks = useCreatorTaskViewStore((state) => state.refresh);
  const timeline = useMemo(() => selectPrimaryTimeline(project), [project]);
  const authorityElement = timeline?.elements_by_id[elementId] ?? null;
  const elementDraft = useProjectDraft<TimelineElementDocument | null>(
    authorityElement,
    `${id}:${timeline?.timeline_id ?? "missing"}:${elementId}:r2v`,
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
  const [viewedSbId, setViewedSbId] = useState<string | null>(null);
  const [viewedVideoId, setViewedVideoId] = useState<string | null>(null);
  const [resolvedModels, setResolvedModels] = useState<ResolvedModels | null>(
    null,
  );

  useEffect(() => {
    if (!versionFromUrl || !project) return;
    const version = project.assets.artifact_versions_by_id[versionFromUrl];
    if (!version || version.owner_ref !== `element:${elementId}`) return;
    if (
      version.kind === "r2v_storyboard_image" ||
      version.slot_id.endsWith(":storyboard")
    ) {
      setViewedSbId(versionFromUrl);
      return;
    }
    setViewedVideoId(versionFromUrl);
  }, [versionFromUrl, project, elementId]);

  useEffect(() => {
    let cancelled = false;
    getResolvedModels()
      .then((resolved) => {
        if (!cancelled) setResolvedModels(resolved);
      })
      .catch(() => {
        /* best-effort: fall back to recipe.model below */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    useCreatorInteractionStore
      .getState()
      .select(element ? `element:${element.element_id}` : null);
  }, [element]);
  useEffect(() => {
    setViewedSbId(null);
    setViewedVideoId(null);
  }, [elementId]);
  useEffect(() => {
    if (!elementDraft.dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [elementDraft.dirty]);

  const planPath = `/project/${id}/plan`;
  const backToPlan = useCallback(() => {
    const navigateBack = () =>
      navigate(
        element
          ? `${planPath}?element=${encodeURIComponent(element.element_id)}`
          : planPath,
      );
    if (!elementDraft.dirty) {
      navigateBack();
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
        navigateBack();
      },
    });
  }, [element, elementDraft, planPath]);

  if (!project || !timeline) {
    if (syncStatus === "invalid" || syncStatus === "not_found") {
      return (
        <PageLoadError
          message={syncError || t("assets.projectReadError")}
          retry={() => void pollOnce(id)}
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
            onClick={() => navigate(planPath, true)}
            className="mt-4 rounded border border-[var(--color-border)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-text-primary)] hover:bg-[var(--color-bg-secondary)]"
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
    patchProject(id, operations).catch((error) => {
      message.error((error as Error).message);
      throw error;
    });
  const updateElement = (mutator: (draft: TimelineElementDocument) => void) =>
    elementDraft.update((draft) => {
      if (draft) mutator(draft);
    });
  const applyDraft = async () => {
    if (!elementDraft.operations.length) return;
    if (creation.type === "r2v") {
      const invalidShot = creation.shots.order
        .map((shotId) => creation.shots.items[shotId])
        .find(
          (shot) =>
            !shot ||
            !shot.description.trim() ||
            !shot.camera?.trim() ||
            !shot.framing?.trim() ||
            shot.duration_seconds == null ||
            shot.duration_seconds <= 0,
        );
      if (invalidShot) {
        message.error("每个 Shot 都需要描述、运镜、景别和有效时长");
        return;
      }
    }
    try {
      const response = await patchProject(id, elementDraft.operations);
      elementDraft.markApplied();
      if (response.editImpact?.regenerationRequired) {
        message.success(t("r2v.applySuccess"));
      } else {
        message.success(t("r2v.applySuccessShort"));
      }
    } catch (error) {
      message.error(t("r2v.applyFailed", { detail: (error as Error).message }));
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
  ) =>
    patchOps([
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

  const elementRef = `element:${element.element_id}`;
  const videoTask = [...tasks]
    .filter((task: TaskView) => task.targetRef === elementRef)
    .sort(
      (left, right) =>
        Date.parse(right.updatedAt || right.createdAt || "") -
        Date.parse(left.updatedAt || left.createdAt || ""),
    )[0];
  const videoGenerating =
    videoTask?.status === "RUNNING" || videoTask?.status === "QUEUED";
  const videoFailed =
    videoTask &&
    ["FAILED", "CANCELLED", "QUARANTINED"].includes(videoTask.status);
  const videoTaskMessage = (() => {
    if (!videoTask) return "";
    if (videoGenerating) return t("r2v.taskSubmitted");
    const detail =
      videoTask.error?.message ||
      videoTask.error?.detail ||
      videoTask.error?.code;
    return typeof detail === "string" && detail
      ? detail
      : t("r2v.videoGenFailed");
  })();

  const spanSeconds = element.span.duration_tick / timeline.ticks_per_second;

  // ── Mode-specific workbenches ─────────────────────────────────────────
  // t2v/i2v/s2v carry none of the shot/storyboard/reference machinery, so
  // they render their own surface built from exactly the provider inputs.
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
    const modeModel =
      (modeCreation.type === "s2v"
        ? resolvedModels?.s2v?.model
        : resolvedModels?.video?.byMode?.[modeCreation.type] ??
          resolvedModels?.video?.model) ??
      modeCreation.recipe?.model ??
      "—";
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
          <img
            src={imageUrlOf(value)!}
            alt={alt}
            className="max-h-64 w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] object-contain"
          />
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
        className="flex h-full flex-col overflow-hidden bg-[var(--color-bg-layout)]"
      >
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]/60 px-5 py-3 backdrop-blur">
          <div className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              onClick={backToPlan}
              className="icon-button shrink-0"
              aria-label="返回视频方案"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
            </button>
            <div className="min-w-0">
              <h2 className="truncate text-sm font-semibold text-[var(--color-text-primary)]">
                {t("r2v.title", { element: elementLabel })}
                <span
                  data-generation-mode={modeCreation.type}
                  className="ml-2 inline-block rounded-full border border-[var(--color-border-secondary)] px-2 py-[1px] align-middle text-[10px] font-medium text-[var(--color-text-secondary)]"
                >
                  {t(GENERATION_MODE_META[modeCreation.type].labelKey)}
                </span>
              </h2>
              <p className="mt-0.5 truncate text-xs text-[var(--color-text-secondary)]">
                {t(GENERATION_MODE_META[modeCreation.type].subtitleKey)}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="small"
              disabled={!elementDraft.dirty || patching}
              onClick={elementDraft.discard}
              className="!h-[22px] !px-2 !font-[inherit] !text-[11px] !font-semibold !leading-[20px]"
            >
              放弃修改
            </Button>
            <Button
              size="small"
              type="primary"
              loading={patching}
              disabled={
                !elementDraft.dirty || elementDraft.conflictPaths.length > 0
              }
              onClick={() => void applyDraft()}
              className="!h-[22px] !px-2 !font-[inherit] !text-[11px] !font-semibold !leading-[20px]"
            >
              {elementDraft.dirty
                ? `应用修改（${elementDraft.dirtyCount}）`
                : "应用修改"}
            </Button>
          </div>
        </div>

        <div className="grid min-h-0 flex-1 gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="min-h-0 space-y-3 overflow-y-auto pr-1">
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
                    onChange={(value) => updateModeField("video_prompt", value)}
                  />
                </Panel>
              </>
            )}
          </div>

          <div className="min-h-0 space-y-3 overflow-y-auto pr-1">
            <Panel
              title={t("r2v.videoResult")}
              badge={
                <ArtifactVersionChips
                  versions={videoVersions}
                  currentId={videoSlot?.selected_version_id}
                  viewingId={effectiveVideoId}
                  onView={setViewedVideoId}
                />
              }
            >
              <div className="space-y-2">
                {videoUrl ? (
                  <video
                    src={videoUrl}
                    controls
                    className="max-h-72 w-full rounded-lg border border-[var(--color-border)] bg-black"
                  />
                ) : (
                  <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-[var(--color-border)] text-xs text-[var(--color-text-tertiary)]">
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
            </Panel>

            <div className="grid grid-cols-3 gap-2">
              {[
                { label: t("r2v.duration"), value: `${spanSeconds}s` },
                {
                  label: t("r2v.frameSize"),
                  value: project.settings.aspect_ratio,
                },
                {
                  label: t("r2v.modelLabel"),
                  value: modeModel,
                },
              ].map((cell) => (
                <div
                  key={cell.label}
                  className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-3 text-center"
                >
                  <p className="text-[10px] text-[var(--color-text-tertiary)]">
                    {cell.label}
                  </p>
                  <p
                    title={cell.value}
                    className="mt-1 truncate text-xs font-semibold text-[var(--color-text-primary)]"
                  >
                    {cell.value}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  const totalDuration = creation.shots.order.length
    ? creation.shots.order.reduce(
        (total, shotId) =>
          total + (creation.shots.items[shotId]?.duration_seconds ?? 0),
        0,
      )
    : spanSeconds;
  const overLimit = totalDuration > spanSeconds;

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
  const materialVersionIds = [
    ...new Set([
      ...creation.storyboard_reference_version_ids,
      ...creation.video_reference_version_ids,
    ]),
  ];
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
  // Historical data has entity refs in two formats (scene:night_room vs
  // visual-entity:scene:night_room). Normalize to the prefixed form so the
  // Select's current value matches an option (shows the real name and avoids
  // duplicate fallback entries).
  const normalizeEntityRef = (ref: string | null | undefined) => {
    if (!ref) return undefined;
    const entityId = ref.replace(/^visual-entity:/, "");
    return project.visual.entities.items[entityId]
      ? `visual-entity:${entityId}`
      : ref;
  };
  const entityThumbVersionId = (
    entityRef: string,
    entityId: string,
  ): string | null => {
    const entity = project.visual.entities.items[entityId];
    if (!entity) return null;
    const variantId =
      creation.visual_variant_refs[entityRef] ??
      creation.visual_variant_refs[entityId] ??
      (entity.variants.order.length === 1 ? entity.variants.order[0] : null);
    if (variantId) {
      return (
        entity.variants.items[variantId]?.selected_artifact_version_id ?? null
      );
    }
    return entity.variants.order.length === 0
      ? entity.selected_artifact_version_id
      : null;
  };
  const versionMediaKind = (versionId: string): "image" | "video" | null => {
    const artifact = project.assets.artifact_versions_by_id[versionId];
    if (artifact) {
      const mediaType =
        (artifact.file_id &&
          project.assets.files_by_id[artifact.file_id]?.media_type) ||
        "";
      if (mediaType.startsWith("video") || `${artifact.kind}`.includes("video"))
        return "video";
      return "image";
    }
    const source = project.assets.source_versions_by_id[versionId];
    if (source) {
      if (source.media_kind === "video") return "video";
      if (source.media_kind === "image") return "image";
      return null;
    }
    return null;
  };
  /** Storyboard image produced by the same element; video thumbnails prefer it over keyframes. */
  const storyboardOfOwner = (ownerRef: string): string | null => {
    if (!ownerRef.startsWith("element:")) return null;
    const candidates = Object.values(
      project.assets.artifact_versions_by_id,
    ).filter(
      (version) =>
        version.owner_ref === ownerRef &&
        `${version.kind}`.includes("storyboard"),
    );
    if (!candidates.length) return null;
    return candidates[candidates.length - 1].version_id;
  };
  interface RefThumb {
    kind: "image" | "video";
    url: string;
  }
  /** Hover preview for a reference: images render directly; videos use the sibling storyboard image or a keyframe; null when nothing was produced. */
  const refThumbInfo = (ref: string): RefThumb | null => {
    const entityId = ref.replace(/^visual-entity:/, "");
    if (project.visual.entities.items[entityId]) {
      const versionId = entityThumbVersionId(ref, entityId);
      return versionId
        ? { kind: "image", url: getArtifactVersionMediaUrl(versionId) }
        : null;
    }
    const versionId = ref.replace(/^artifact-version:/, "");
    const media = versionMediaKind(versionId);
    if (!media) return null;
    const artifact = project.assets.artifact_versions_by_id[versionId];
    const url = artifact
      ? getArtifactVersionMediaUrl(versionId)
      : getAssetVersionMediaUrl(versionId);
    if (media === "video") {
      const storyboardId = artifact
        ? storyboardOfOwner(artifact.owner_ref ?? "")
        : null;
      if (storyboardId)
        return {
          kind: "image",
          url: getArtifactVersionMediaUrl(storyboardId),
        };
      return { kind: "video", url };
    }
    return { kind: "image", url };
  };
  const inputRefs: Array<{ ref: string; field: ReferenceField; name: string }> =
    [
      ...(creation.scene_ref
        ? [
            {
              ref: creation.scene_ref,
              field: "scene" as const,
              name: visualEntityName(project, creation.scene_ref),
            },
          ]
        : []),
      ...creation.character_refs.map((ref) => ({
        ref,
        field: "characters" as const,
        name: visualEntityName(project, ref),
      })),
      ...creation.prop_refs.map((ref) => ({
        ref,
        field: "props" as const,
        name: visualEntityName(project, ref),
      })),
      ...materialVersionIds
        .filter((versionId) => !isReferencedEntityArtifact(versionId))
        .map((versionId) => ({
          ref: `artifact-version:${versionId}`,
          field: "sources" as const,
          name: referenceVersionName(project, versionId),
        })),
    ];

  // Both Select options and the current value use real names; if the current
  // value is missing from the options (historical data / different prefix
  // format), add a fallback option with the real name to avoid showing raw IDs
  // like scene:night_room.
  const withValueFallback = (
    options: Array<{ value: string; label: string }>,
    refs: Array<string | null | undefined>,
    labelOf: (ref: string) => string,
  ) => {
    const known = new Set(options.map((option) => option.value));
    refs
      .map((ref) => normalizeEntityRef(ref))
      .filter((ref): ref is string => Boolean(ref))
      .forEach((ref) => {
        if (known.has(ref)) return;
        known.add(ref);
        options.push({ value: ref, label: labelOf(ref) });
      });
    return options;
  };
  const entityOptions = (kind: "scene" | "character" | "prop") =>
    Object.values(project.visual.entities.items)
      .filter((entity) => entity.kind === kind)
      .map((entity) => ({
        value: `visual-entity:${entity.entity_id}`,
        label: entity.name || entity.entity_id,
      }));
  const sceneOptions = withValueFallback(
    entityOptions("scene"),
    [creation.scene_ref],
    (ref) => visualEntityName(project, ref),
  );
  const characterOptions = withValueFallback(
    entityOptions("character"),
    creation.character_refs,
    (ref) => visualEntityName(project, ref),
  );
  const propOptions = withValueFallback(
    entityOptions("prop"),
    creation.prop_refs,
    (ref) => visualEntityName(project, ref),
  );
  const materialOptions = withValueFallback(
    [
      ...Object.values(project.assets.source_versions_by_id).map((version) => ({
        value: version.version_id,
        label: version.name || version.version_id,
      })),
      ...Object.values(project.assets.artifact_versions_by_id)
        .filter((version) => version.owner_ref !== elementRef)
        .map((version) => ({
          value: version.version_id,
          label: version.name || version.version_id,
        })),
    ],
    materialVersionIds,
    (versionId) => referenceVersionName(project, versionId),
  );
  const changeMaterialReferences = (next: string[]) =>
    updateElement((draft) => {
      if (draft.creation.type !== "r2v") return;
      draft.creation.storyboard_reference_version_ids = next;
      draft.creation.video_reference_version_ids = next;
    });
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
        // Schema v3 persists bare entity IDs. Also clean prefixed keys from
        // pre-validation UI drafts so they cannot survive a reference edit.
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
  const referencedVisualEntities = [
    creation.scene_ref,
    ...creation.character_refs,
    ...creation.prop_refs,
  ]
    .filter((ref): ref is string => Boolean(ref))
    .map(normalizeVisualEntityId)
    .filter((entityId, index, all) => all.indexOf(entityId) === index)
    .map((entityId) => project.visual.entities.items[entityId])
    .filter((entity) => Boolean(entity));
  const changeVariantBinding = (
    entityId: string,
    variantId: string | undefined,
  ) =>
    updateElement((draft) => {
      if (draft.creation.type !== "r2v") return;
      delete draft.creation.visual_variant_refs[`visual-entity:${entityId}`];
      if (variantId) {
        draft.creation.visual_variant_refs[entityId] = variantId;
      } else {
        delete draft.creation.visual_variant_refs[entityId];
      }
    });

  const addShot = () => {
    const shotId = `shot-${Date.now()}`;
    updateElement((draft) => {
      if (draft.creation.type !== "r2v") return;
      draft.creation.shots.items[shotId] = {
        shot_id: shotId,
        description: "",
        camera: t("r2v.defaultCamera"),
        framing: t("r2v.defaultFraming"),
        duration_seconds: 3,
      };
      draft.creation.shots.order.push(shotId);
    });
  };
  const deleteShot = (shot: { shot_id: string }) =>
    updateElement((draft) => {
      if (draft.creation.type !== "r2v") return;
      delete draft.creation.shots.items[shot.shot_id];
      draft.creation.shots.order = draft.creation.shots.order.filter(
        (item) => item !== shot.shot_id,
      );
    });

  return (
    <div
      data-r2v-workbench={element.element_id}
      className="flex h-full flex-col overflow-hidden bg-[var(--color-bg-layout)]"
    >
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]/60 px-5 py-3 backdrop-blur">
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            onClick={backToPlan}
            className="icon-button shrink-0"
            aria-label={t("nav.backToPlan")}
          >
            <ArrowLeft className="h-3.5 w-3.5" />
          </button>
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
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="small"
            disabled={!elementDraft.dirty || patching}
            onClick={elementDraft.discard}
            className="!h-[22px] !px-2 !font-[inherit] !text-[11px] !font-semibold !leading-[20px]"
          >
            {t("r2v.discardChanges")}
          </Button>
          <Button
            size="small"
            type="primary"
            loading={patching}
            disabled={
              !elementDraft.dirty || elementDraft.conflictPaths.length > 0
            }
            onClick={() => void applyDraft()}
            className="!h-[22px] !px-2 !font-[inherit] !text-[11px] !font-semibold !leading-[20px]"
          >
            {elementDraft.dirty
              ? t("r2v.applyChangesCount", { count: elementDraft.dirtyCount })
              : t("r2v.applyChanges")}
          </Button>
        </div>
      </div>

      {elementDraft.conflictPaths.length > 0 && (
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
      )}

      <div className="grid min-h-0 flex-1 gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-h-0 space-y-3 overflow-y-auto pr-1">
          <Panel
            title={t("r2v.shotList", { count: creation.shots.order.length })}
            badge={
              <span
                className={`flex items-center gap-1 text-[11px] font-medium ${
                  overLimit
                    ? "text-[var(--color-danger)]"
                    : "text-[var(--color-text-tertiary)]"
                }`}
              >
                {overLimit && <AlertTriangle className="h-3 w-3" />}
                {t("r2v.totalDuration", {
                  total: totalDuration,
                  span: spanSeconds,
                })}
              </span>
            }
          >
            <ShotList
              shots={creation.shots}
              elementId={element.element_id}
              disabled={patching}
              shotPointer={(shotId, field) =>
                elementPointer("creation", "shots", "items", shotId, field)
              }
              onChangeField={(shotId, field, value) =>
                updateElement((draft) => {
                  if (draft.creation.type !== "r2v") return;
                  const shot = draft.creation.shots.items[shotId];
                  if (shot) Object.assign(shot, { [field]: value });
                })
              }
              onAdd={addShot}
              onDelete={deleteShot}
            />
          </Panel>

          <Panel
            title={t("r2v.storyboardPromptAndImage")}
            badge={
              <ArtifactVersionChips
                versions={storyboardVersions}
                currentId={storyboardSlot?.selected_version_id}
                viewingId={effectiveSbId}
                onView={setViewedSbId}
              />
            }
          >
            <div className="space-y-3">
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
                        void setCurrentVersion(storyboardSlot, viewedStoryboard)
                      }
                      className="!text-[11px]"
                    >
                      {t("r2v.setAsCurrent")}
                    </Button>
                  </div>
                )}
              <PromptTextArea
                label={t("r2v.storyboardPrompt")}
                value={creation.storyboard_prompt}
                field={`element:${element.element_id}/creation/storyboard_prompt`}
                path={elementPointer("creation", "storyboard_prompt")}
                disabled={patching}
                onChange={(value) =>
                  updateElement((draft) => {
                    if (draft.creation.type === "r2v")
                      draft.creation.storyboard_prompt = value;
                  })
                }
              />
              {storyboardUrl ? (
                // <img> can't host ::after; put the review flash anchor on the wrapper.
                <div
                  data-review-media-anchor={viewedStoryboard?.version_id}
                  className="rounded-lg"
                >
                  <img
                    src={storyboardUrl}
                    alt={t("lib.storyboard")}
                    className="w-full rounded-lg border border-[var(--color-border)]"
                  />
                </div>
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
              <PromptTextArea
                label={t("r2v.videoPrompt")}
                value={creation.video_prompt}
                field={`element:${element.element_id}/creation/video_prompt`}
                path={elementPointer("creation", "video_prompt")}
                disabled={patching}
                onChange={(value) =>
                  updateElement((draft) => {
                    if (draft.creation.type === "r2v")
                      draft.creation.video_prompt = value;
                  })
                }
              />
            </div>
          </Panel>
        </div>

        <aside className="min-h-0 space-y-3 overflow-y-auto pr-1">
          <Panel
            title={t("r2v.videoResult")}
            badge={
              <ArtifactVersionChips
                versions={videoVersions}
                currentId={videoSlot?.selected_version_id}
                viewingId={effectiveVideoId}
                onView={setViewedVideoId}
              />
            }
          >
            <div className="space-y-2">
              {videoUrl && viewedVideo ? (
                // <video> can't host ::after; put the review flash anchor on the wrapper.
                <div
                  data-review-media-anchor={viewedVideo.version_id}
                  className="rounded-lg"
                >
                  <video
                    key={viewedVideo.version_id}
                    src={videoUrl}
                    controls
                    className="w-full rounded-lg border border-[var(--color-border)]"
                  />
                </div>
              ) : (
                <div className="flex h-32 flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed border-[var(--color-border)] text-xs text-[var(--color-text-tertiary)]">
                  {videoGenerating ? (
                    <>
                      <span className="font-medium text-[var(--color-warning)]">
                        {t("r2v.r2vGenerating")}
                      </span>
                      <span>{videoTaskMessage}</span>
                      <Button
                        size="small"
                        onClick={() =>
                          void Promise.all([refreshTasks(id), pollOnce(id)])
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
          </Panel>

          <div className="grid grid-cols-3 gap-2">
            {[
              { label: t("r2v.duration"), value: `${totalDuration}s` },
              {
                label: t("r2v.frameSize"),
                value: project.settings.aspect_ratio,
              },
              {
                label: t("r2v.modelLabel"),
                value:
                  resolvedModels?.video?.byMode?.r2v ??
                  resolvedModels?.video?.model ??
                  creation.recipe?.model ??
                  "R2V",
              },
            ].map((cell) => (
              <div
                key={cell.label}
                className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-card)] p-3 text-center"
              >
                <p className="text-[10px] text-[var(--color-text-tertiary)]">
                  {cell.label}
                </p>
                <p
                  title={cell.value}
                  className="mt-1 truncate text-xs font-semibold text-[var(--color-text-primary)]"
                >
                  {cell.value}
                </p>
              </div>
            ))}
          </div>

          <Panel title={t("r2v.inputRefs", { count: inputRefs.length })}>
            {inputRefs.length === 0 ? (
              <p className="text-xs text-[var(--color-text-tertiary)]">
                {t("r2v.noRefs")}
              </p>
            ) : (
              <div className="space-y-1.5">
                {inputRefs.map((item) => {
                  const thumb = refThumbInfo(item.ref);
                  const row = (
                    <button
                      type="button"
                      onClick={() =>
                        useCreatorInteractionStore.getState().select(item.ref)
                      }
                      className="flex w-full items-center gap-2 rounded-lg bg-[var(--color-bg-secondary)]/60 px-2.5 py-1.5 text-left transition-colors hover:bg-[var(--color-bg-secondary)]"
                    >
                      <span className="shrink-0 rounded border border-[var(--color-border)] bg-[var(--color-bg-primary)] px-1.5 py-px text-[10px] text-[var(--color-text-tertiary)]">
                        {t(FIELD_LABEL_KEYS[item.field])}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-xs font-medium text-[var(--color-accent)]">
                        @{item.name}
                      </span>
                    </button>
                  );
                  return (
                    <Tooltip
                      key={item.ref}
                      placement="left"
                      title={
                        thumb ? (
                          thumb.kind === "video" ? (
                            <video
                              src={thumb.url}
                              muted
                              preload="metadata"
                              className="max-h-40 max-w-[220px] rounded object-contain"
                            />
                          ) : (
                            <img
                              src={thumb.url}
                              alt={item.name}
                              className="max-h-40 max-w-[220px] rounded object-contain"
                            />
                          )
                        ) : (
                          <span className="text-xs">
                            {t("r2v.noPreviewYet")}
                          </span>
                        )
                      }
                    >
                      {row}
                    </Tooltip>
                  );
                })}
              </div>
            )}
          </Panel>

          <Panel title={t("r2v.assetBinding")}>
            <div className="space-y-3">
              <div>
                <p className="mb-1 text-[11px] font-medium text-[var(--color-text-tertiary)]">
                  {t("r2v.sceneLabel")}
                </p>
                <Select
                  size="small"
                  className="!w-full"
                  value={normalizeEntityRef(creation.scene_ref)}
                  disabled={patching}
                  onChange={(value) =>
                    changeEntityReferences("scene", value ? [value] : [])
                  }
                  allowClear
                  placeholder={t("r2v.selectScene")}
                  options={sceneOptions}
                />
              </div>
              <div>
                <p className="mb-1 text-[11px] font-medium text-[var(--color-text-tertiary)]">
                  {t("r2v.charactersLabel")}
                </p>
                <Select
                  size="small"
                  mode="multiple"
                  className="!w-full"
                  value={creation.character_refs.map(
                    (ref) => normalizeEntityRef(ref) ?? ref,
                  )}
                  disabled={patching}
                  onChange={(value) =>
                    changeEntityReferences("characters", value)
                  }
                  placeholder={t("r2v.selectCharacters")}
                  options={characterOptions}
                />
              </div>
              <div>
                <p className="mb-1 text-[11px] font-medium text-[var(--color-text-tertiary)]">
                  {t("r2v.propsLabel")}
                </p>
                <Select
                  size="small"
                  mode="multiple"
                  className="!w-full"
                  value={creation.prop_refs.map(
                    (ref) => normalizeEntityRef(ref) ?? ref,
                  )}
                  disabled={patching}
                  onChange={(value) => changeEntityReferences("props", value)}
                  placeholder={t("r2v.selectProps")}
                  options={propOptions}
                />
              </div>
              {referencedVisualEntities.length > 0 && (
                <div className="border-t border-[var(--color-border)] pt-3">
                  <p className="mb-2 text-[11px] font-medium text-[var(--color-text-tertiary)]">
                    {t("r2v.visualVariant")}
                  </p>
                  <div className="space-y-2">
                    {referencedVisualEntities.map((entity) => {
                      const entityId = entity.entity_id;
                      const selectedVariantId =
                        creation.visual_variant_refs[entityId] ??
                        creation.visual_variant_refs[
                          `visual-entity:${entityId}`
                        ] ??
                        (entity.variants.order.length === 1
                          ? entity.variants.order[0]
                          : undefined);
                      return (
                        <div key={entityId} className="flex items-center gap-2">
                          <span className="w-20 shrink-0 truncate text-[11px] text-[var(--color-text-secondary)]">
                            {entity.name || entityId}
                          </span>
                          <Select
                            size="small"
                            className="min-w-0 flex-1"
                            aria-label={`${entity.name || entityId} Variant`}
                            value={selectedVariantId}
                            disabled={patching}
                            allowClear={entity.variants.order.length > 1}
                            placeholder={
                              entity.variants.order.length
                                ? t("r2v.selectVariant")
                                : t("r2v.noVariantDefined")
                            }
                            onChange={(variantId) =>
                              changeVariantBinding(entityId, variantId)
                            }
                            options={entity.variants.order.map((variantId) => {
                              const variant = entity.variants.items[variantId];
                              return {
                                value: variantId,
                                label: variant
                                  ? visualVariantLabel(variant)
                                  : variantId,
                              };
                            })}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
              <div>
                <p className="mb-1 text-[11px] font-medium text-[var(--color-text-tertiary)]">
                  {t("r2v.materialsLabel")}
                </p>
                <Select
                  size="small"
                  mode="multiple"
                  className="!w-full"
                  value={materialVersionIds}
                  disabled={patching}
                  onChange={changeMaterialReferences}
                  placeholder={t("r2v.selectMaterials")}
                  options={materialOptions}
                />
              </div>
            </div>
          </Panel>
        </aside>
      </div>
    </div>
  );
}
