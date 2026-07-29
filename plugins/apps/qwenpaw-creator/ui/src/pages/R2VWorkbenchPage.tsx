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
import { projectJsonPointer } from "@/lib/projectJsonPointer";
import { useProjectDraft } from "@/lib/useProjectDraft";
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
} from "@/contracts/creator";

const { TextArea } = Input;

type ReferenceField = "scene" | "characters" | "props" | "sources";

const FIELD_LABEL: Record<ReferenceField, string> = {
  scene: "场景",
  characters: "角色",
  props: "道具",
  sources: "素材",
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
  onChange,
}: {
  label: string;
  value: string;
  field: string;
  path: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
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
        placeholder={`生成${label}后可在此编辑…`}
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
  const creation = element?.creation.type === "r2v" ? element.creation : null;
  const [viewedSbId, setViewedSbId] = useState<string | null>(null);
  const [viewedVideoId, setViewedVideoId] = useState<string | null>(null);
  const [resolvedVideoModel, setResolvedVideoModel] = useState<string | null>(
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
        if (!cancelled) setResolvedVideoModel(resolved.video.model || null);
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
      title: "还有未应用的修改",
      content: "返回方案会放弃当前 R2V 页面草稿。",
      okText: "放弃并返回",
      okButtonProps: { danger: true },
      cancelText: "继续编辑",
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
          message={syncError || "Project 无法读取"}
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
            {element
              ? "该时间线内容不是 AI 生成画面，没有独立工作台"
              : "时间线中找不到这项内容"}
          </p>
          <button
            type="button"
            onClick={() => navigate(planPath, true)}
            className="mt-4 rounded border border-[var(--color-border)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-text-primary)] hover:bg-[var(--color-bg-secondary)]"
          >
            返回方案
          </button>
        </div>
      </div>
    );
  }

  const elementLabel = element.label || element.element_id;
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
    try {
      const response = await patchProject(id, elementDraft.operations);
      elementDraft.markApplied();
      if (response.editImpact?.regenerationRequired) {
        message.success("修改已应用；旧生成结果已标记为基于旧方案");
      } else {
        message.success("修改已应用");
      }
    } catch (error) {
      message.error(`应用修改失败：${(error as Error).message}`);
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
    if (videoGenerating) return "任务已提交，等待最新状态";
    const detail =
      videoTask.error?.message ||
      videoTask.error?.detail ||
      videoTask.error?.code;
    return typeof detail === "string" && detail ? detail : "视频生成失败";
  })();

  const spanSeconds = element.span.duration_tick / timeline.ticks_per_second;
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
  const entityThumbVersionId = (entityId: string): string | null => {
    const entity = project.visual.entities.items[entityId];
    if (!entity) return null;
    if (entity.selected_artifact_version_id)
      return entity.selected_artifact_version_id;
    for (const variantId of [...entity.variants.order].reverse()) {
      const generated =
        entity.variants.items[variantId]?.generated_artifact_version_ids ?? [];
      if (generated.length) return generated[generated.length - 1];
    }
    return null;
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
      const versionId = entityThumbVersionId(entityId);
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

  const addShot = () => {
    const shotId = `shot-${Date.now()}`;
    updateElement((draft) => {
      if (draft.creation.type !== "r2v") return;
      draft.creation.shots.items[shotId] = {
        shot_id: shotId,
        description: "",
        camera: "⊙ 静止",
        framing: "中景",
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
            aria-label="返回视频方案"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
          </button>
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold text-[var(--color-text-primary)]">
              {`视频方案 / ${elementLabel} / 制作工作台`}
            </h2>
            <p className="mt-0.5 truncate text-xs text-[var(--color-text-secondary)]">
              AI 生成画面子界面，继承分镜、引用资产和产物版本。
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

      {elementDraft.conflictPaths.length > 0 && (
        <Alert
          type="warning"
          showIcon
          banner
          message="部分字段在编辑期间被其他操作更新"
          description="本地草稿已保留。确认使用本地值覆盖最新数据后再应用。"
          action={
            <Button size="small" onClick={elementDraft.acceptConflicts}>
              使用我的修改
            </Button>
          }
        />
      )}

      <div className="grid min-h-0 flex-1 gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-h-0 space-y-3 overflow-y-auto pr-1">
          <Panel
            title={`Shot 列表（${creation.shots.order.length}）`}
            badge={
              <span
                className={`flex items-center gap-1 text-[11px] font-medium ${
                  overLimit
                    ? "text-[var(--color-danger)]"
                    : "text-[var(--color-text-tertiary)]"
                }`}
              >
                {overLimit && <AlertTriangle className="h-3 w-3" />}
                合计 {totalDuration}s / 区间 {spanSeconds}s
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
            title="分镜Prompt与分镜图"
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
                      可切换为当前分镜版本
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
                      设为当前
                    </Button>
                  </div>
                )}
              <PromptTextArea
                label="分镜图 Prompt"
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
                    alt="分镜图"
                    className="w-full rounded-lg border border-[var(--color-border)]"
                  />
                </div>
              ) : (
                <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-[var(--color-border)] text-xs text-[var(--color-text-tertiary)]">
                  尚无分镜图
                </div>
              )}
              {viewedStoryboard?.stale && (
                <p className="text-[10px] text-[var(--color-warning)]">
                  该分镜图基于旧版方案，需要重新生成。
                </p>
              )}
              <PromptTextArea
                label="视频 Prompt"
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
            title="视频结果"
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
                        R2V 任务生成中…
                      </span>
                      <span>{videoTaskMessage}</span>
                      <Button
                        size="small"
                        onClick={() =>
                          void Promise.all([refreshTasks(id), pollOnce(id)])
                        }
                        className="!text-[11px]"
                      >
                        手动刷新
                      </Button>
                    </>
                  ) : videoFailed ? (
                    <span className="px-3 text-center text-[var(--color-danger)]">
                      {videoTaskMessage}
                    </span>
                  ) : (
                    "尚未生成视频"
                  )}
                </div>
              )}
              {viewedVideo &&
                videoSlot &&
                viewedVideo.version_id !== videoSlot.selected_version_id && (
                  <div className="flex items-center justify-between rounded-lg border border-[var(--color-warning)]/25 bg-[var(--color-warning-soft)] px-2.5 py-1.5">
                    <span className="text-[11px] text-[var(--color-warning)]">
                      可切换为当前视频版本
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
                      设为当前
                    </Button>
                  </div>
                )}
              {viewedVideo?.stale && (
                <p className="text-[10px] text-[var(--color-warning)]">
                  该结果基于旧版方案，需要重新生成。
                </p>
              )}
            </div>
          </Panel>

          <div className="grid grid-cols-3 gap-2">
            {[
              { label: "时长", value: `${totalDuration}s` },
              { label: "画幅", value: project.settings.aspect_ratio },
              {
                label: "模型",
                value: resolvedVideoModel ?? creation.recipe?.model ?? "R2V",
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

          <Panel title={`输入引用（${inputRefs.length}）`}>
            {inputRefs.length === 0 ? (
              <p className="text-xs text-[var(--color-text-tertiary)]">
                暂无引用资产。
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
                        {FIELD_LABEL[item.field]}
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
                            尚未生成可预览的图像，生成后这里会显示缩略图
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

          <Panel title="资产绑定">
            <div className="space-y-3">
              <div>
                <p className="mb-1 text-[11px] font-medium text-[var(--color-text-tertiary)]">
                  场景
                </p>
                <Select
                  size="small"
                  className="!w-full"
                  value={normalizeEntityRef(creation.scene_ref)}
                  disabled={patching}
                  onChange={(value) =>
                    updateElement((draft) => {
                      if (draft.creation.type === "r2v")
                        draft.creation.scene_ref = value ?? null;
                    })
                  }
                  allowClear
                  placeholder="选择场景"
                  options={sceneOptions}
                />
              </div>
              <div>
                <p className="mb-1 text-[11px] font-medium text-[var(--color-text-tertiary)]">
                  角色
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
                    updateElement((draft) => {
                      if (draft.creation.type === "r2v")
                        draft.creation.character_refs = value;
                    })
                  }
                  placeholder="选择角色"
                  options={characterOptions}
                />
              </div>
              <div>
                <p className="mb-1 text-[11px] font-medium text-[var(--color-text-tertiary)]">
                  道具
                </p>
                <Select
                  size="small"
                  mode="multiple"
                  className="!w-full"
                  value={creation.prop_refs.map(
                    (ref) => normalizeEntityRef(ref) ?? ref,
                  )}
                  disabled={patching}
                  onChange={(value) =>
                    updateElement((draft) => {
                      if (draft.creation.type === "r2v")
                        draft.creation.prop_refs = value;
                    })
                  }
                  placeholder="选择道具"
                  options={propOptions}
                />
              </div>
              <div>
                <p className="mb-1 text-[11px] font-medium text-[var(--color-text-tertiary)]">
                  素材
                </p>
                <Select
                  size="small"
                  mode="multiple"
                  className="!w-full"
                  value={materialVersionIds}
                  disabled={patching}
                  onChange={changeMaterialReferences}
                  placeholder="选择素材"
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
